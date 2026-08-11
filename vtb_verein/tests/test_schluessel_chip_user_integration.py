"""
Integrationstest: Chip auf ein Benutzerkonto statt auf ein Mitglied (Schema v91).

Wer einen Chip bekommt, ist nicht zwangsläufig Mitglied — Platzwart, Hausmeister,
Betreuer eines Gastvereins haben ein App-Konto, aber keinen Mitgliedsdatensatz.
Geprüft wird hier alles, was daran in SQL hängt und Fakes nicht abbilden können:
die neue Spalte samt History-Trigger, die Namensauflösung im Log und in der
Auswertung, der Self-Service-Check am Schloss und die eigene Zutrittsliste.

Läuft nur, wenn ``VTB_TEST_DATABASE_URL`` auf eine LEERE Wegwerf-DB zeigt
(VereinsDB legt das Schema beim Connect an). Beispiel:
    docker run -d --name vtb-pg-chipuser -e POSTGRES_PASSWORD=test \\
        -e POSTGRES_DB=chipuser -p 55432:5432 postgres:18
    VTB_TEST_DATABASE_URL=postgresql://postgres:test@localhost:55432/chipuser \\
        ./venv/bin/python -m pytest vtb_verein/tests/test_schluessel_chip_user_integration.py
"""
import os

import pytest

from app.models.schliessanlage import SchluesselChip, TuerZutrittLog, QUELLE_EXTERN
from app.services import zutritt_auswertung_service

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-chipuser-uploads")
    yield d
    d.close()


@pytest.fixture(autouse=True)
def clean(db):
    with db.conn.cursor() as cur:
        cur.execute("DELETE FROM tuer_zutritt_log")
        cur.execute("DELETE FROM tuer_berechtigung_history")
        cur.execute("DELETE FROM tuer_berechtigung")
        cur.execute("DELETE FROM tuer_schloss_status_log")
        cur.execute("DELETE FROM tuer_schloss_history")
        cur.execute("DELETE FROM tuer_schloss")
        cur.execute("DELETE FROM schluessel_chip_history")
        cur.execute("DELETE FROM schluessel_chip")
        # Eigene Testdaten wieder wegräumen: andere Integrationstests zählen
        # Mitglieder bzw. User und stolpern sonst über unsere Zeilen.
        cur.execute("DELETE FROM mitglied WHERE vorname = 'CHIPUSER'")
        cur.execute("DELETE FROM users WHERE username LIKE 'chipuser-%'")
    db.conn.commit()
    yield


def _user(db, username, *, mitglied=False):
    """Benutzerkonto anlegen – wahlweise mit verknüpftem Mitgliedsdatensatz."""
    with db.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (username, email, password_hash, role, created_by, updated_by) "
            "VALUES (%s, %s, 'x', 'mitglied', 't', 't') RETURNING id",
            (username, f"{username}@example.invalid"))
        uid = cur.fetchone()['id']
        if mitglied:
            cur.execute(
                "INSERT INTO mitglied (vorname, nachname, zahlungsart, user_id, "
                "created_by, updated_by) VALUES ('CHIPUSER', %s, 'lastschrift', %s, 't', 't')",
                (username, uid))
    db.conn.commit()
    return uid


def _schloss(db, name="Tor"):
    return db.tuer_schloesser.create_extern(name=name, by="tester")


def _log(db, schloss, zeit_utc, *, chip_id=None, mitglied_id=None, konto=None):
    db.tuer_zutritt_logs.insert_extern_if_new(TuerZutrittLog(
        schloss_id=schloss.id, quelle=QUELLE_EXTERN, extern_konto=konto,
        record_type=7, methode="IC-Karte", erfolg=True,
        chip_id=chip_id, mitglied_id=mitglied_id, lock_date=zeit_utc))


def test_chip_laeuft_auf_ein_benutzerkonto_und_liefert_dessen_namen(db):
    uid = _user(db, "chipuser-platzwart")
    chip = db.schluessel_chips.create(
        SchluesselChip(kartennummer="4711", bezeichnung="Chip blau", user_id=uid), "t")

    geladen = db.schluessel_chips.get(chip.id)
    assert (geladen.user_id, geladen.mitglied_id) == (uid, None)
    assert geladen.user_username == "chipuser-platzwart"
    assert [c.id for c in db.schluessel_chips.list_for_user(uid)] == [chip.id]


def test_history_haelt_den_inhaberwechsel_fest(db):
    """Der Audit-Trigger muss die neue Spalte mitschreiben – sonst wäre in der
    History nie zu sehen, wem der Chip vorher gehörte."""
    uid = _user(db, "chipuser-hausmeister")
    chip = db.schluessel_chips.create(
        SchluesselChip(kartennummer="4712", bezeichnung="Chip rot", user_id=uid), "t")
    chip.user_id = None
    chip.aufbewahrungsort = "Geschäftsstelle"
    db.schluessel_chips.update(chip, "t")

    with db.conn.cursor() as cur:
        cur.execute("SELECT version, user_id FROM schluessel_chip_history "
                    "WHERE id = %s ORDER BY version", (chip.id,))
        verlauf = [(r['version'], r['user_id']) for r in cur.fetchall()]
    assert verlauf == [(1, uid), (2, None)]


def test_log_zeigt_den_benutzer_statt_nur_der_chip_bezeichnung(db):
    uid = _user(db, "chipuser-platzwart")
    tor = _schloss(db)
    chip = db.schluessel_chips.create(
        SchluesselChip(kartennummer="4711", bezeichnung="Chip blau", user_id=uid), "t")
    _log(db, tor, "2026-07-01T08:00:00+00:00", chip_id=chip.id, konto="Chip blau")

    zeile = db.tuer_zutritt_logs.list_for_schloss(tor.id)[0]
    assert zeile.chip_user_username == "chipuser-platzwart"
    assert zeile.mitglied_vorname is None       # die Zeile selbst kennt kein Mitglied


def test_auswertung_zaehlt_den_benutzer_als_person(db):
    """Ohne diese Auflösung stünde in der Rangliste die Chip-Bezeichnung – ein
    Chip als „häufigster Öffner" hilft niemandem."""
    uid = _user(db, "chipuser-platzwart")
    tor = _schloss(db)
    chip = db.schluessel_chips.create(
        SchluesselChip(kartennummer="4711", bezeichnung="Chip blau", user_id=uid), "t")
    for tag in (1, 2, 3):
        _log(db, tor, f"2026-07-0{tag}T08:00:00+00:00", chip_id=chip.id)

    personen = zutritt_auswertung_service.bericht(db, tage=0)['personen']
    assert [(p['wer'], p['anzahl']) for p in personen] == [("chipuser-platzwart", 3)]


def test_mitglied_gewinnt_vor_dem_benutzerkonto(db):
    """Steht in der Log-Zeile ein Mitglied, bleibt es die Wahrheit – auch wenn am
    Chip zusätzlich ein Konto hinge (Altdaten aus der Zeit vor der Normalisierung)."""
    uid = _user(db, "chipuser-doppelt", mitglied=True)
    tor = _schloss(db)
    with db.conn.cursor() as cur:
        cur.execute("SELECT id FROM mitglied WHERE user_id = %s", (uid,))
        mid = cur.fetchone()['id']
    db.conn.commit()
    chip = db.schluessel_chips.create(
        SchluesselChip(kartennummer="4711", bezeichnung="Chip blau",
                       mitglied_id=mid, user_id=uid), "t")
    _log(db, tor, "2026-07-01T08:00:00+00:00", chip_id=chip.id, mitglied_id=mid)

    personen = zutritt_auswertung_service.bericht(db, tage=0)['personen']
    assert [p['wer'] for p in personen] == ["CHIPUSER chipuser-doppelt"]


def test_self_service_am_schloss_gilt_auch_ohne_mitgliedsdatensatz(db):
    """Wer den Chip hat, muss die Tür auch über die App aufbekommen."""
    uid = _user(db, "chipuser-platzwart")
    fremder = _user(db, "chipuser-fremder")
    tor = _schloss(db)
    chip = db.schluessel_chips.create(
        SchluesselChip(kartennummer="4711", bezeichnung="Chip blau", user_id=uid), "t")
    with db.conn.cursor() as cur:
        cur.execute("INSERT INTO tuer_berechtigung (chip_id, schloss_id, sync_status, "
                    "created_by, updated_by) VALUES (%s, %s, 'ok', 't', 't')",
                    (chip.id, tor.id))
    db.conn.commit()

    assert db.tuer_berechtigungen.user_has_valid_for_schloss(uid, tor.id) is True
    assert db.tuer_berechtigungen.user_has_valid_for_schloss(fremder, tor.id) is False


def test_eigene_zutritte_kommen_ueber_mitglied_und_ueber_chip(db):
    uid = _user(db, "chipuser-platzwart")
    mit_uid = _user(db, "chipuser-mitglied", mitglied=True)
    tor = _schloss(db)
    with db.conn.cursor() as cur:
        cur.execute("SELECT id FROM mitglied WHERE user_id = %s", (mit_uid,))
        mid = cur.fetchone()['id']
    db.conn.commit()
    chip = db.schluessel_chips.create(
        SchluesselChip(kartennummer="4711", bezeichnung="Chip blau", user_id=uid), "t")
    _log(db, tor, "2026-07-01T08:00:00+00:00", chip_id=chip.id)
    _log(db, tor, "2026-07-02T08:00:00+00:00", mitglied_id=mid, konto="mitglied")

    ueber_chip = db.tuer_zutritt_logs.list_selbstauskunft(chip_ids=(chip.id,))
    assert [z.chip_id for z in ueber_chip] == [chip.id]
    ueber_mitglied = db.tuer_zutritt_logs.list_selbstauskunft(mitglied_id=mid)
    assert [z.mitglied_id for z in ueber_mitglied] == [mid]
    # Ohne Anhaltspunkt gibt es nichts zu zeigen – und vor allem nicht alles.
    assert db.tuer_zutritt_logs.list_selbstauskunft() == []
    assert db.tuer_zutritt_logs.list_selbstauskunft(chip_ids=()) == []
