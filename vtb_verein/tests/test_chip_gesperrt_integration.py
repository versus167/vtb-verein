"""Ein gesperrter/verlorener Chip muss auch AN SEINEN TÜREN als gesperrt zu sehen sein.

Bis v106 stand an jeder Berechtigung eines verlorenen Chips weiter „aktiv": Der
Sync-Status beantwortet nur „ist der Cloud-Write durch?", und der war es ja. Für den
Leser der Türliste war das die falsche Auskunft — die Karte liegt zwar noch am
Schloss, trägt dort aber ein abgelaufenes Fenster und öffnet nichts.

Geprüft wird, was sich nur an der Datenbank zeigt:
- der Chip-Status kommt mit jeder Berechtigungszeile mit (Anzeige-JOIN),
- `update_period` schreibt eine gesperrte Zeile nicht auf „aktiv" zurück,
- die Migration v106→v107 zieht die Zeilen aus der Zeit davor nach,
- der Self-Service-Check lässt einen gesperrten Chip nicht durch.

Läuft nur mit ``VTB_TEST_DATABASE_URL`` (leere Wegwerf-DB).
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # Repo-Root für backend.*

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

_MARKE = 'CHIPSPERR'


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-chipsperr-uploads")
    yield d
    d.close()


def _aufraeumen(db):
    """Nur die eigenen Spuren – die Wegwerf-DB teilen sich alle Integrationstests.

    Auch NACH dem Test: Andere Module räumen die Chip-Tabelle komplett leer und
    scheiterten sonst am Fremdschlüssel aus unserer Berechtigung.
    """
    wie = (f'{_MARKE}%',)
    eigene = "SELECT id FROM schluessel_chip WHERE kartennummer LIKE %s"
    with db.cursor() as cur:
        for tbl in ("tuer_berechtigung_history", "tuer_berechtigung"):
            cur.execute(f"DELETE FROM {tbl} WHERE chip_id IN ({eigene})", wie)
        cur.execute("DELETE FROM schluessel_chip_history WHERE kartennummer LIKE %s", wie)
        cur.execute("DELETE FROM schluessel_chip WHERE kartennummer LIKE %s", wie)
        cur.execute("DELETE FROM tuer_credential WHERE schloss_id IN "
                    "(SELECT id FROM tuer_schloss WHERE name LIKE %s)", wie)
        cur.execute("DELETE FROM tuer_schloss_history WHERE name LIKE %s", wie)
        cur.execute("DELETE FROM tuer_schloss WHERE name LIKE %s", wie)
        # Zuletzt der Chip-Inhaber (der Chip zeigt per FK auf ihn).
        cur.execute("DELETE FROM users_history WHERE username LIKE %s", wie)
        cur.execute("DELETE FROM users WHERE username LIKE %s", wie)


@pytest.fixture()
def bestand(db):
    """Ein Schloss, ein Chip, eine angelernte Berechtigung (Karte liegt am Schloss)."""
    from app.models.schliessanlage import SchluesselChip, TuerBerechtigung
    _aufraeumen(db)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO tuer_schloss (ttlock_lock_id, name, created_by, updated_by) "
            "VALUES (%s,%s,'test','test') RETURNING id", (7311, f"{_MARKE} Halle"))
        schloss_id = cur.fetchone()['id']
    chip = db.schluessel_chips.create(
        SchluesselChip(kartennummer=f"{_MARKE}-KN1", bezeichnung="Chip blau"), "test")
    ber = db.tuer_berechtigungen.create(
        TuerBerechtigung(chip_id=chip.id, schloss_id=schloss_id, ttlock_card_id=4711,
                         sync_status='aktiv'), "test")
    yield {"schloss_id": schloss_id, "chip": chip, "ber": ber}
    _aufraeumen(db)


def _sperren(db, chip, status='verloren'):
    chip.status = status
    return db.schluessel_chips.update(chip, "test")


class TestChipStatusAnDerTuer:
    def test_status_kommt_mit_jeder_berechtigungszeile(self, db, bestand):
        _sperren(db, bestand["chip"])
        fuer_chip = db.tuer_berechtigungen.list_for_chip(bestand["chip"].id)
        fuer_schloss = db.tuer_berechtigungen.list_for_schloss(bestand["schloss_id"])
        einzeln = db.tuer_berechtigungen.get(bestand["ber"].id)
        assert [b.chip_status for b in fuer_chip] == ['verloren']
        assert [b.chip_status for b in fuer_schloss] == ['verloren']
        assert einzeln.chip_status == 'verloren'

    def test_gueltigkeit_pflegen_laesst_die_sperre_stehen(self, db, bestand):
        """Sonst stünde nach einer Terminkorrektur wieder „aktiv" an der Tür."""
        db.tuer_berechtigungen.set_sync(bestand["ber"].id, ttlock_card_id=4711,
                                        sync_status='gesperrt', sync_fehler=None, by="test")
        _sperren(db, bestand["chip"])
        aktualisiert = db.tuer_berechtigungen.update_period(
            bestand["ber"].id, gueltig_von=None, gueltig_bis="2027-06-30T22:00:00+00:00",
            by="test", sync_status='gesperrt')
        assert aktualisiert.sync_status == 'gesperrt'
        assert aktualisiert.gueltig_bis == "2027-06-30T22:00:00+00:00"


class TestMigrationV107:
    def test_altbestand_wird_nachgezogen(self, db, bestand):
        """Vor v107 gesperrte Chips tragen an ihren Türen noch „aktiv"."""
        _sperren(db, bestand["chip"])
        with db.cursor() as cur:
            cur.execute("UPDATE schema_version SET version = 106 WHERE id = 1")

        db._database._migrate_v106_to_v107()

        assert db.tuer_berechtigungen.get(bestand["ber"].id).sync_status == 'gesperrt'
        with db.cursor() as cur:
            cur.execute("SELECT version FROM schema_version WHERE id = 1")
            assert cur.fetchone()['version'] == 107

    def test_aktiver_chip_bleibt_unberuehrt(self, db, bestand):
        db._database._migrate_v106_to_v107()
        assert db.tuer_berechtigungen.get(bestand["ber"].id).sync_status == 'aktiv'

    def test_migration_ist_wiederholbar(self, db, bestand):
        _sperren(db, bestand["chip"])
        db._database._migrate_v106_to_v107()
        vorher = db.tuer_berechtigungen.get(bestand["ber"].id).version
        db._database._migrate_v106_to_v107()
        # Zweiter Lauf findet nichts mehr – sonst wüchse die History bei jedem Start.
        assert db.tuer_berechtigungen.get(bestand["ber"].id).version == vorher


class TestSelfService:
    def test_gesperrter_chip_oeffnet_im_self_service_nicht(self, db, bestand):
        """`user_has_valid_for_schloss` trägt die Entscheidung „darf per App öffnen"."""
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO users (username, password_hash, role, active, created_by, "
                "updated_by) VALUES (%s,'x','mitglied',1,'test','test') RETURNING id",
                (f"{_MARKE}-platzwart",))
            user_id = cur.fetchone()['id']
            cur.execute("UPDATE schluessel_chip SET user_id = %s WHERE id = %s",
                        (user_id, bestand["chip"].id))
        assert db.tuer_berechtigungen.user_has_valid_for_schloss(
            user_id, bestand["schloss_id"])
        _sperren(db, db.schluessel_chips.get(bestand["chip"].id))
        assert not db.tuer_berechtigungen.user_has_valid_for_schloss(
            user_id, bestand["schloss_id"])
