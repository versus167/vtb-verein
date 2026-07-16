"""Integrationstests Termin-Gäste (#95): Abteilungs-Mitglieder als Gäste eines
Termins. Gast = aktive Zu-/Absage eines Mitglieds, das am Termin-Datum NICHT im
Kader der Termin-Mannschaft steht — keine eigene Tabelle. Gast-Kreis ist die
ABTEILUNGS-Mitgliedschaft (mitglied_abteilung), eine eigene Kader-Zugehörigkeit
ist keine Voraussetzung.

Prüft die Repository-Schicht: Abteilungs-Check (is_mitglied_in_abteilung),
Gast-Kandidaten, Gäste-Liste des Termins, Gast-Zugriff (has_active_zusage),
Gast-Termine in „Meine Termine" (gast-Flag) und den Benachrichtigungs-
Empfängerkreis (list_user_ids_mit_zusage).

Läuft nur, wenn ``VTB_TEST_DATABASE_URL`` auf eine (leere) Wegwerf-DB zeigt.
"""
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # Repo-Root für backend.*

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

LASTWEEK = (date.today() - timedelta(days=7)).isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()
TOMORROW = (date.today() + timedelta(days=1)).isoformat()


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-gaeste-uploads")
    yield d
    d.close()


@pytest.fixture(autouse=True)
def clean(db):
    with db.cursor() as cur:
        cur.execute(
            "TRUNCATE termin_zusage, termin_zusage_history, termine, termine_history, "
            "mitglied_mannschaft, mitglied_mannschaft_history, "
            "mannschaft, mannschaft_history RESTART IDENTITY CASCADE"
        )
        cur.execute("DELETE FROM mitglied_abteilung WHERE mitglied_id IN "
                    "(SELECT id FROM mitglied WHERE vorname='Gast')")
        cur.execute("DELETE FROM mitglied WHERE vorname='Gast'")
        cur.execute("DELETE FROM users WHERE username LIKE 'gasttester%'")
        cur.execute("DELETE FROM abteilung WHERE name LIKE 'Gast-Abt%'")
    yield


def _make_mannschaft(db, name="Erste", abteilung="Gast-Abt-Fussball"):
    with db.cursor() as cur:
        cur.execute("SELECT id FROM abteilung WHERE name=%s AND deleted_at IS NULL", (abteilung,))
        row = cur.fetchone()
        aid = row['id'] if row else None
        if aid is None:
            cur.execute("INSERT INTO abteilung (name,created_by,updated_by) "
                        "VALUES (%s,'t','t') RETURNING id", (abteilung,))
            aid = cur.fetchone()['id']
        cur.execute("INSERT INTO mannschaft (abteilung_id,name,saison,created_by,updated_by) "
                    "VALUES (%s,%s,'2026/27','t','t') RETURNING id", (aid, name))
        return cur.fetchone()['id']


def _make_mitglied(db, username="gasttester", nachname="Tester", mit_user=True):
    """User (optional) + Mitglied ohne Zuordnungen. Gibt (user_id | None, mitglied_id)."""
    with db.cursor() as cur:
        uid = None
        if mit_user:
            cur.execute("INSERT INTO users (username,email,password_hash,role,active,created_by,updated_by) "
                        "VALUES (%s,%s,'x','mitglied',1,'t','t') RETURNING id",
                        (username, f"{username}@x.de"))
            uid = cur.fetchone()['id']
        cur.execute("INSERT INTO mitglied (vorname,nachname,zahlungsart,user_id,created_by,updated_by) "
                    "VALUES ('Gast',%s,'lastschrift',%s,'t','t') RETURNING id", (nachname, uid))
        mid = cur.fetchone()['id']
    return uid, mid


def _add_abteilung(db, mitglied_id, mannschaft_id, von=LASTWEEK, bis=None):
    """Abteilungs-Mitgliedschaft in der Abteilung der Mannschaft (von/bis optional)."""
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO mitglied_abteilung (mitglied_id,abteilung_id,von,bis,created_by,updated_by) "
            "SELECT %s, abteilung_id, %s, %s, 't', 't' FROM mannschaft WHERE id=%s",
            (mitglied_id, von, bis, mannschaft_id))


def _add_kader(db, mitglied_id, mannschaft_id, rolle="spieler", von=LASTWEEK, bis=None):
    with db.cursor() as cur:
        cur.execute("INSERT INTO mitglied_mannschaft (mitglied_id,mannschaft_id,rolle,von,bis,created_by,updated_by) "
                    "VALUES (%s,%s,%s,%s,%s,'t','t')", (mitglied_id, mannschaft_id, rolle, von, bis))


def _make_kader_mitglied(db, mannschaft_id, rolle="spieler", von=LASTWEEK, bis=None,
                         username="gasttester", nachname="Tester", mit_user=True):
    """User (optional) + Mitglied + Abteilungs- und Kader-Zuordnung der Mannschaft."""
    uid, mid = _make_mitglied(db, username=username, nachname=nachname, mit_user=mit_user)
    _add_abteilung(db, mid, mannschaft_id)
    _add_kader(db, mid, mannschaft_id, rolle=rolle, von=von, bis=bis)
    return uid, mid


def _termin(db, mannschaft_id, beginn=f"{TOMORROW}T19:00"):
    return db.termine.create(mannschaft_id, 'training', beginn, None, None, None,
                             None, None, None, None, 't')


# ------------------------------------------------------------ Abteilungs-Check
def test_is_mitglied_in_abteilung(db):
    erste = _make_mannschaft(db, "Erste")
    _make_mannschaft(db, "AH")
    handball = _make_mannschaft(db, "Handball1", abteilung="Gast-Abt-Handball")
    _, hb_mid = _make_kader_mitglied(db, handball, username="gasttester2")
    # Abteilungs-Mitglied OHNE jede Kader-Zugehörigkeit genügt
    _, ohne_team_mid = _make_mitglied(db, username="gasttester1")
    _add_abteilung(db, ohne_team_mid, erste)
    # abgelaufene Abteilungs-Mitgliedschaft
    _, alt_mid = _make_mitglied(db, username="gasttester3")
    _add_abteilung(db, alt_mid, erste, bis=YESTERDAY)

    assert db.termine.is_mitglied_in_abteilung(ohne_team_mid, erste)
    assert not db.termine.is_mitglied_in_abteilung(hb_mid, erste)      # fremde Abteilung
    assert not db.termine.is_mitglied_in_abteilung(alt_mid, erste)     # abgelaufen
    assert db.termine.is_mitglied_in_abteilung(alt_mid, erste, YESTERDAY)  # Stichtag


def test_list_gast_kandidaten(db):
    erste = _make_mannschaft(db, "Erste")
    ah = _make_mannschaft(db, "AH")
    handball = _make_mannschaft(db, "Handball1", abteilung="Gast-Abt-Handball")
    _, ah_mid = _make_kader_mitglied(db, ah, nachname="Aushilfe", username="gasttester1")
    _, kader_mid = _make_kader_mitglied(db, erste, nachname="Stamm", username="gasttester2")
    _make_kader_mitglied(db, handball, nachname="Fremd", username="gasttester3")
    # In AH UND Erste → kein Kandidat (steht ja schon im Kader)
    _, doppel_mid = _make_kader_mitglied(db, ah, nachname="Doppel", username="gasttester4")
    _add_kader(db, doppel_mid, erste)
    # Abteilungs-Mitglied ganz ohne Mannschaft ist ebenfalls Kandidat
    _, frei_mid = _make_mitglied(db, nachname="Ohneteam", username="gasttester5")
    _add_abteilung(db, frei_mid, erste)

    kandidaten = db.termine.list_gast_kandidaten(erste)
    assert [k['mitglied_id'] for k in kandidaten] == [ah_mid, frei_mid]
    assert kandidaten[0]['name'] == 'Gast Aushilfe'
    assert kandidaten[0]['mannschaften'] == 'AH'
    assert kandidaten[1]['mannschaften'] is None
    assert kader_mid not in [k['mitglied_id'] for k in kandidaten]


# ------------------------------------------------------------------- Gast-Flow
def test_gast_flow_zusage_sichtbarkeit_und_empfaenger(db):
    erste = _make_mannschaft(db, "Erste")
    ah = _make_mannschaft(db, "AH")
    gast_uid, gast_mid = _make_kader_mitglied(db, ah, nachname="Aushilfe",
                                              username="gasttester1")
    kader_uid, kader_mid = _make_kader_mitglied(db, erste, nachname="Stamm",
                                                username="gasttester2")
    t = _termin(db, erste)
    ah_termin = _termin(db, ah, beginn=f"{TOMORROW}T20:00")

    # Verwalter trägt den AH-Spieler als Gast ein (Zusage ohne Kader)
    db.termin_zusagen.set_antwort(t.id, gast_mid, 'zu', None, 'trainer')
    db.termin_zusagen.set_antwort(t.id, kader_mid, 'zu', None, 'trainer')

    gaeste = db.termin_zusagen.list_gaeste_with_zusage(t.id)
    assert [g['mitglied_id'] for g in gaeste] == [gast_mid]
    assert gaeste[0]['antwort'] == 'zu'
    # Kader-Liste bleibt gast-frei, Kader-Mitglied taucht nicht als Gast auf
    kader = db.termin_zusagen.list_kader_with_zusage(t.id)
    assert [p['mitglied_id'] for p in kader] == [kader_mid]

    # Gast-Zugriff auf genau diesen Termin
    assert db.termin_zusagen.has_active_zusage(t.id, gast_uid)
    assert not db.termin_zusagen.has_active_zusage(ah_termin.id, gast_uid)

    # „Meine Termine" des Gastes: eigener AH-Termin + Gast-Termin (lesen, gast=True)
    meine = db.termine.list_for_user(gast_uid, von=date.today().isoformat())
    assert {m['id']: m['gast'] for m in meine} == {t.id: True, ah_termin.id: False}
    gast_eintrag = next(m for m in meine if m['id'] == t.id)
    assert gast_eintrag['zugriff'] == 'lesen'

    # Benachrichtigungs-Empfänger: Kader + Gast (Dedupe macht der Versand)
    assert sorted(db.termin_zusagen.list_user_ids_mit_zusage(t.id)) == \
        sorted([gast_uid, kader_uid])

    # Zurücknehmen beendet den Gast-Status
    db.termin_zusagen.remove_antwort(t.id, gast_mid, 'trainer')
    assert not db.termin_zusagen.has_active_zusage(t.id, gast_uid)
    assert db.termin_zusagen.list_gaeste_with_zusage(t.id) == []
    meine = db.termine.list_for_user(gast_uid, von=date.today().isoformat())
    assert [m['id'] for m in meine] == [ah_termin.id]


def test_kader_mitglied_ist_kein_gast(db):
    erste = _make_mannschaft(db, "Erste")
    uid, mid = _make_kader_mitglied(db, erste, username="gasttester1")
    t = _termin(db, erste)
    db.termin_zusagen.set_antwort(t.id, mid, 'zu', None, 't')
    assert db.termin_zusagen.list_gaeste_with_zusage(t.id) == []
    meine = db.termine.list_for_user(uid, von=date.today().isoformat())
    assert meine[0]['gast'] is False
