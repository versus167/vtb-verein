"""Erinnerung an fehlende Termin-Meldungen (#95-Nachgang) gegen echtes PostgreSQL.

Zwei Dinge lassen sich nur hier prüfen, weil beide in genau einer Abfrage stecken:
**wer** als „hat noch nicht gemeldet" gilt (`list_offene_user_ids` – Kader am
Termin-Datum, eingeladene Gäste, zurückgenommene Antworten, Mitglieder ohne
Benutzerkonto) und **welche Termine** überhaupt anstehen
(`list_geplante_im_fenster`). Dazu der Lauf als Ganzes: dass er die Stufe
protokolliert und beim zweiten Mal schweigt.

Läuft nur mit ``VTB_TEST_DATABASE_URL`` auf einer (leeren) Wegwerf-DB – VereinsDB legt
das Schema beim Connect an (Beispiel siehe test_termin_zusage_integration.py).
"""
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # Repo-Root für backend.*

from app.models.termin import TerminErinnerungEinstellungen  # noqa: E402
from app.services import notification_service as ns  # noqa: E402
from app.services import termin_erinnerung_service as erin  # noqa: E402

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

HEUTE = date.today()
LASTWEEK = (HEUTE - timedelta(days=7)).isoformat()
YESTERDAY = (HEUTE - timedelta(days=1)).isoformat()


def tag(in_tagen: int) -> str:
    return (HEUTE + timedelta(days=in_tagen)).isoformat()


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-termin-erinnerung-uploads")
    yield d
    d.close()


def _aufraeumen(db):
    with db.cursor() as cur:
        cur.execute(
            "TRUNCATE termin_serie, termin_serie_history, "
            "termin_zusage, termin_zusage_history, termine, termine_history, "
            "mitglied_mannschaft, mitglied_mannschaft_history, "
            "mannschaft, mannschaft_history RESTART IDENTITY CASCADE"
        )
        cur.execute("DELETE FROM mitglied WHERE vorname='Erinner'")
        cur.execute("DELETE FROM users WHERE username LIKE 'erinner_%'")
        cur.execute("DELETE FROM abteilung WHERE name='Erinner-Abt'")
        cur.execute("DELETE FROM access_log WHERE event_type = %s",
                    (erin.EVENT_ERINNERUNG,))
        # Vorlauf auf die Vorgaben zurück – ein Test, der ihn verstellt, darf den
        # nächsten nicht mitziehen.
        cur.execute("DELETE FROM termin_erinnerung_einstellungen_history")
        cur.execute("DELETE FROM termin_erinnerung_einstellungen")
        cur.execute("INSERT INTO termin_erinnerung_einstellungen (id) VALUES (1)")


@pytest.fixture(autouse=True)
def clean(db):
    # Vor UND nach dem Test aufräumen: Nur davor zu putzen lässt die Zeilen im
    # geteilten Wegwerf-Postgres stehen, wo vereinsweite Auswertungen anderer
    # Module sie mitzählen.
    _aufraeumen(db)
    yield
    _aufraeumen(db)


@pytest.fixture()
def gesendet(monkeypatch):
    """Versand abfangen: [(user_id, titel, text, url), …]."""
    raus = []

    def _fake(user, title, message, push_service=None, url='/'):
        raus.append((user.id, title, message, url))
        return True

    monkeypatch.setattr(ns.NotificationService, "send_notification", staticmethod(_fake))
    return raus


# ------------------------------------------------------------------- Bausteine
def _make_mannschaft(db, name="Erste", abteilung="Erinner-Abt"):
    with db.cursor() as cur:
        cur.execute("SELECT id FROM abteilung WHERE name=%s AND deleted_at IS NULL",
                    (abteilung,))
        row = cur.fetchone()
        aid = row['id'] if row else None
        if aid is None:
            cur.execute("INSERT INTO abteilung (name,created_by,updated_by) "
                        "VALUES (%s,'t','t') RETURNING id", (abteilung,))
            aid = cur.fetchone()['id']
        cur.execute("INSERT INTO mannschaft (abteilung_id,name,saison,created_by,updated_by) "
                    "VALUES (%s,%s,'2026/27','t','t') RETURNING id", (aid, name))
        return cur.fetchone()['id']


def _make_mitglied(db, username, nachname="Tester", mit_user=True, aktiv=True):
    """User (optional) + Mitglied. Gibt (user_id | None, mitglied_id)."""
    with db.cursor() as cur:
        uid = None
        if mit_user:
            cur.execute(
                "INSERT INTO users (username,email,password_hash,role,active,"
                "created_by,updated_by) VALUES (%s,%s,'x','mitglied',%s,'t','t') "
                "RETURNING id", (username, f"{username}@x.de", 1 if aktiv else 0))
            uid = cur.fetchone()['id']
        cur.execute("INSERT INTO mitglied (vorname,nachname,zahlungsart,user_id,"
                    "created_by,updated_by) VALUES ('Erinner',%s,'lastschrift',%s,'t','t') "
                    "RETURNING id", (nachname, uid))
        return uid, cur.fetchone()['id']


def _in_kader(db, mitglied_id, mannschaft_id, rolle="spieler", von=LASTWEEK, bis=None):
    with db.cursor() as cur:
        cur.execute("INSERT INTO mitglied_mannschaft (mitglied_id,mannschaft_id,rolle,"
                    "von,bis,created_by,updated_by) VALUES (%s,%s,%s,%s,%s,'t','t')",
                    (mitglied_id, mannschaft_id, rolle, von, bis))


def _platz(db):
    """Platzhalter „Kein Vereinsgelände" – seit v80 ist die Spielstätte Pflicht."""
    with db.cursor() as cur:
        cur.execute("SELECT id FROM spielstaette WHERE platzhalter = 'auswaerts'")
        return cur.fetchone()['id']


def _termin(db, mannschaft_id, in_tagen=3, typ='training'):
    return db.termine.create(mannschaft_id, typ, f"{tag(in_tagen)}T19:00", None, None,
                             None, None, None, None, None, 't',
                             spielstaette_id=_platz(db))


@pytest.fixture()
def team(db):
    """Mannschaft mit einem Kader-Spieler (mit Konto) und einem Termin in 3 Tagen."""
    mid = _make_mannschaft(db)
    uid, mitglied_id = _make_mitglied(db, "erinner_spieler")
    _in_kader(db, mitglied_id, mid)
    return {"mannschaft_id": mid, "user_id": uid, "mitglied_id": mitglied_id,
            "termin": _termin(db, mid)}


# --------------------------------------------------- Wer hat noch nicht gemeldet?
class TestOffeneEmpfaenger:
    def test_kader_ohne_antwort_ist_offen(self, db, team):
        assert db.termin_zusagen.list_offene_user_ids(team["termin"].id) == [team["user_id"]]

    @pytest.mark.parametrize("antwort", ['zu', 'ab', 'vielleicht'])
    def test_jede_antwort_beendet_die_erinnerung(self, db, team, antwort):
        """Auch „vielleicht" ist eine Meldung – mehr weiß der Spieler selbst nicht."""
        db.termin_zusagen.set_antwort(team["termin"].id, team["mitglied_id"], antwort,
                                      None, 't')
        assert db.termin_zusagen.list_offene_user_ids(team["termin"].id) == []

    def test_zurueckgenommene_antwort_ist_wieder_offen(self, db, team):
        db.termin_zusagen.set_antwort(team["termin"].id, team["mitglied_id"], 'zu',
                                      None, 't')
        db.termin_zusagen.remove_antwort(team["termin"].id, team["mitglied_id"], 't')
        assert db.termin_zusagen.list_offene_user_ids(team["termin"].id) == [team["user_id"]]

    def test_einladung_ohne_antwort_bleibt_offen(self, db, team):
        """Eingeladen heißt nicht geantwortet – die Zeile hat `antwort IS NULL`."""
        db.termin_zusagen.lade_ein(team["termin"].id, team["mitglied_id"], 't')
        assert db.termin_zusagen.list_offene_user_ids(team["termin"].id) == [team["user_id"]]

    def test_eingeladener_gast_wird_mit_erinnert(self, db, team):
        gast_uid, gast_mid = _make_mitglied(db, "erinner_gast", nachname="Gast")
        db.termin_zusagen.lade_ein(team["termin"].id, gast_mid, 't')
        assert sorted(db.termin_zusagen.list_offene_user_ids(team["termin"].id)) == \
            sorted([team["user_id"], gast_uid])

    def test_gast_mit_antwort_hoert_nichts(self, db, team):
        _, gast_mid = _make_mitglied(db, "erinner_gast2", nachname="Gast")
        db.termin_zusagen.set_antwort(team["termin"].id, gast_mid, 'zu', None, 't')
        assert db.termin_zusagen.list_offene_user_ids(team["termin"].id) == [team["user_id"]]

    def test_ohne_benutzerkonto_kein_kanal(self, db, team):
        _, ohne_konto = _make_mitglied(db, "erinner_ohne", mit_user=False)
        _in_kader(db, ohne_konto, team["mannschaft_id"])
        assert db.termin_zusagen.list_offene_user_ids(team["termin"].id) == [team["user_id"]]

    def test_wer_am_termintag_nicht_mehr_im_kader_ist_bleibt_aussen_vor(self, db, team):
        _, weg = _make_mitglied(db, "erinner_weg")
        _in_kader(db, weg, team["mannschaft_id"], bis=YESTERDAY)
        assert db.termin_zusagen.list_offene_user_ids(team["termin"].id) == [team["user_id"]]

    def test_doppelrolle_erinnert_nur_einmal(self, db, team):
        _in_kader(db, team["mitglied_id"], team["mannschaft_id"], rolle="betreuer")
        assert db.termin_zusagen.list_offene_user_ids(team["termin"].id) == [team["user_id"]]


# ------------------------------------------------------- Welche Termine stehen an?
class TestFenster:
    def test_nur_termine_im_vorlauf(self, db, team):
        _termin(db, team["mannschaft_id"], in_tagen=9)     # zu weit weg
        _termin(db, team["mannschaft_id"], in_tagen=-1)    # vorbei
        gefunden = db.termine.list_geplante_im_fenster(tag(1), tag(3))
        assert [t.id for t in gefunden] == [team["termin"].id]

    def test_abgesagte_termine_fallen_raus(self, db, team):
        db.termine.set_status(team["termin"].id, 'abgesagt', 't',
                              expected_version=team["termin"].version)
        assert db.termine.list_geplante_im_fenster(tag(1), tag(3)) == []

    def test_geloeschte_termine_fallen_raus(self, db, team):
        db.termine.mark_deleted(team["termin"].id, 't')
        assert db.termine.list_geplante_im_fenster(tag(1), tag(3)) == []

    def test_mannschaftsname_kommt_mit(self, db, team):
        gefunden = db.termine.list_geplante_im_fenster(tag(1), tag(3))
        assert gefunden[0].mannschaft_name == "Erste"


# ---------------------------------------------------------------------- Der Lauf
class TestLauf:
    def test_erinnert_und_merkt_es_sich(self, db, team, gesendet):
        res = erin.erinnern(db)
        assert res == {"anstehend": 1, "erinnert": 1, "empfaenger": 1}
        (user_id, titel, text, url), = gesendet
        assert user_id == team["user_id"]
        assert titel == "Rückmeldung fehlt – Erste"
        assert "in 3 Tagen" in text
        assert url == f"/termine?termin={team['termin'].id}"

        # Zweiter Lauf am selben Tag: dieselbe Stufe geht nicht erneut raus.
        gesendet.clear()
        assert erin.erinnern(db)["erinnert"] == 0
        assert gesendet == []

    def test_wer_gemeldet_hat_hoert_nichts(self, db, team, gesendet):
        db.termin_zusagen.set_antwort(team["termin"].id, team["mitglied_id"], 'zu',
                                      None, 't')
        assert erin.erinnern(db)["erinnert"] == 0
        assert gesendet == []

    def test_ohne_offene_meldung_bleibt_die_stufe_unvermerkt(self, db, team, gesendet):
        """Damit die Erinnerung noch kommt, wenn jemand seine Antwort zurücknimmt."""
        db.termin_zusagen.set_antwort(team["termin"].id, team["mitglied_id"], 'zu',
                                      None, 't')
        erin.erinnern(db)
        db.termin_zusagen.remove_antwort(team["termin"].id, team["mitglied_id"], 't')
        assert erin.erinnern(db)["erinnert"] == 1
        assert len(gesendet) == 1

    def test_zweite_stufe_kommt_am_vortag(self, db, team, gesendet):
        morgen = _termin(db, team["mannschaft_id"], in_tagen=1)
        erin.erinnern(db)
        assert len(gesendet) == 2                      # beide Termine, je eine Meldung
        assert any("der Termin ist morgen." in text for _, _, text, _ in gesendet)
        with db.cursor() as cur:
            cur.execute("SELECT detail FROM access_log WHERE event_type=%s ORDER BY detail",
                        (erin.EVENT_ERINNERUNG,))
            details = [r['detail'] for r in cur.fetchall()]
        assert details == sorted([f"{team['termin'].id}:3", f"{morgen.id}:1"])

    def test_abgeschaltet_laeuft_gar_nicht(self, db, team, gesendet):
        db.termin_erinnerung_einstellungen.update(
            TerminErinnerungEinstellungen(aktiv=False), 't')
        assert erin.erinnern(db) == {"anstehend": 0, "erinnert": 0, "empfaenger": 0}
        assert gesendet == []

    def test_serientermine_werden_vorher_materialisiert(self, db, team, gesendet):
        """Der Lauf darf nicht davon abhängen, dass vorher jemand die App geöffnet
        hat – Serien-Instanzen entstehen sonst nie von selbst."""
        db.termin_serien.create(
            team["mannschaft_id"], 'training', "19:00", None, None, None, None, None,
            tag(1), tag(1), 't', spielstaette_id=_platz(db))
        assert db.termine.list_geplante_im_fenster(tag(1), tag(1)) == []   # noch nichts
        erin.erinnern(db)
        assert any("der Termin ist morgen." in text for _, _, text, _ in gesendet)

    def test_gesperrtes_konto_wird_uebersprungen(self, db, team, gesendet):
        with db.cursor() as cur:
            cur.execute("UPDATE users SET active=0 WHERE id=%s", (team["user_id"],))
        res = erin.erinnern(db)
        assert (res["erinnert"], res["empfaenger"]) == (1, 0)
        assert gesendet == []


# ------------------------------------------------------------------ Einstellungen
class TestEinstellungen:
    def test_vorgabe_ist_drei_und_ein_tag(self, db):
        e = db.termin_erinnerung_einstellungen.get()
        assert (e.aktiv, e.erste_stufe_tage, e.zweite_stufe_tage) == (True, 3, 1)

    def test_update_schreibt_history(self, db):
        db.termin_erinnerung_einstellungen.update(
            TerminErinnerungEinstellungen(erste_stufe_tage=5, zweite_stufe_tage=2), 'chef')
        e = db.termin_erinnerung_einstellungen.get()
        assert (e.erste_stufe_tage, e.zweite_stufe_tage, e.version, e.updated_by) == \
            (5, 2, 2, 'chef')
        with db.cursor() as cur:
            cur.execute("SELECT version, erste_stufe_tage FROM "
                        "termin_erinnerung_einstellungen_history ORDER BY version")
            # Version 1 schreibt schon der INSERT-Trigger (Ausgangsstand),
            # Version 2 ist die Änderung.
            assert [(r['version'], r['erste_stufe_tage']) for r in cur.fetchall()] == \
                [(1, 3), (2, 5)]

    def test_eigener_vorlauf_wirkt_im_lauf(self, db, team, gesendet):
        _termin(db, team["mannschaft_id"], in_tagen=6)
        # Mit der Vorgabe (3/1) liegt der Termin in sechs Tagen außerhalb …
        assert erin.erinnern(db)["erinnert"] == 1
        assert not any("in 6 Tagen" in text for _, _, text, _ in gesendet)
        gesendet.clear()
        # … mit sechs Tagen Vorlauf ist er dran. (Der Termin in drei Tagen kommt
        # nochmals mit: Für die neue Stufe ist er noch nicht vermerkt – der Preis
        # dafür, dass eine Umstellung sofort greift, und einmalig.)
        db.termin_erinnerung_einstellungen.update(
            TerminErinnerungEinstellungen(erste_stufe_tage=6, zweite_stufe_tage=0), 't')
        erin.erinnern(db)
        assert any("in 6 Tagen" in text for _, _, text, _ in gesendet)
