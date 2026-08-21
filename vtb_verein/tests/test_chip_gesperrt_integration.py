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


class TestAbgleichAbfragen:
    """Soll und Ist für den Abgleich – beide Seiten müssen dieselben Schlösser meinen."""

    def _schloss(self, db, name, *, lock_id, aktiv=True):
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO tuer_schloss (ttlock_lock_id, name, aktiv, created_by, "
                "updated_by) VALUES (%s,%s,%s,'test','test') RETURNING id",
                (lock_id, f"{_MARKE} {name}", aktiv))
            return cur.fetchone()['id']

    def test_nur_aktive_cloud_schloesser_zaehlen(self, db, bestand):
        """Ein externes oder stillgelegtes Schloss liefert keinen Mirror – seine Zeilen
        sähen sonst reihenweise wie „Karte fehlt am Schloss" aus."""
        from app.models.schliessanlage import TuerBerechtigung
        for name, lock_id, aktiv in (("Tor", None, True), ("Alt", 7312, False)):
            sid = self._schloss(db, name, lock_id=lock_id, aktiv=aktiv)
            db.tuer_berechtigungen.create(
                TuerBerechtigung(chip_id=bestand["chip"].id, schloss_id=sid,
                                 ttlock_card_id=4712, sync_status='aktiv'), "test")

        schloesser = {b.schloss_id for b in db.tuer_berechtigungen.list_fuer_abgleich()}
        assert schloesser == {bestand["schloss_id"]}      # von dreien bleibt eines

    def test_ist_liefert_nur_ic_karten(self, db, bestand):
        from app.models.schliessanlage import CRED_IC, CRED_PASSCODE, TuerCredential
        db.tuer_credentials.replace_for_schloss_typ(bestand["schloss_id"], CRED_IC, [
            TuerCredential(schloss_id=bestand["schloss_id"], typ=CRED_IC,
                           ttlock_credential_id=4711, detail="CHIPSPERR-KN1",
                           gesehen_am="2026-08-21T06:00:00+00:00")])
        db.tuer_credentials.replace_for_schloss_typ(bestand["schloss_id"], CRED_PASSCODE, [
            TuerCredential(schloss_id=bestand["schloss_id"], typ=CRED_PASSCODE,
                           ttlock_credential_id=55, name="Putzdienst")])
        karten = db.tuer_credentials.list_fuer_abgleich(CRED_IC)
        assert [k.ttlock_credential_id for k in karten] == [4711]

    def test_gesperrter_chip_mit_gueltiger_karte_faellt_auf(self, db, bestand):
        """Der ganze Weg an echten Daten: Chip verloren, Karte am Schloss unbefristet."""
        from app.models.schliessanlage import CRED_IC, TuerCredential
        from app.services import zutritt_abgleich_service as abgleich_service
        db.tuer_credentials.replace_for_schloss_typ(bestand["schloss_id"], CRED_IC, [
            TuerCredential(schloss_id=bestand["schloss_id"], typ=CRED_IC,
                           ttlock_credential_id=4711, detail="CHIPSPERR-KN1",
                           gesehen_am="2026-08-21T06:00:00+00:00")])
        _sperren(db, bestand["chip"])

        ergebnis = abgleich_service.abgleich(db)

        eigene = [b for b in ergebnis['befunde'] if b['schloss_id'] == bestand["schloss_id"]]
        assert [b['art'] for b in eigene] == [abgleich_service.BEFUND_SPERRE_OFFEN]
        assert ergebnis['stand'] is not None


class TestSpiegelNachziehen:
    """Was wir selbst ans Schloss geschrieben haben, gehört sofort in den Ist-Spiegel.

    Sonst hielte der Abgleich bis zum nächsten Sync (viermal am Tag) die Abweichung
    hoch, die der Klick gerade beseitigt hat — beim Sperren das kritische „öffnet
    noch" für eine Karte, die am Schloss längst gelöscht ist.
    """

    def _karte(self, db, schloss_id, *, gesehen_am=None, card_id=4711):
        from app.models.schliessanlage import CRED_IC, TuerCredential
        db.tuer_credentials.replace_for_schloss_typ(schloss_id, CRED_IC, [
            TuerCredential(schloss_id=schloss_id, typ=CRED_IC,
                           ttlock_credential_id=card_id, detail=f"{_MARKE}-KN1",
                           gesehen_am=gesehen_am or "2026-08-21T06:00:00+00:00")])

    def _ic(self, db, schloss_id):
        from app.models.schliessanlage import CRED_IC
        return [c for c in db.tuer_credentials.list_for_schloss(schloss_id)
                if c.typ == CRED_IC]

    def test_geloeschte_karte_verschwindet_sofort_aus_dem_spiegel(self, db, bestand):
        self._karte(db, bestand["schloss_id"])

        db.tuer_credentials.ic_karte_entfernt(bestand["schloss_id"], 4711)

        assert self._ic(db, bestand["schloss_id"]) == []

    def test_angelernte_karte_steht_sofort_im_spiegel(self, db, bestand):
        db.tuer_credentials.ic_karte_gesetzt(
            bestand["schloss_id"], credential_id=9001, name="Chip blau",
            kartennummer=f"{_MARKE}-KN1", gueltig_von=None,
            gueltig_bis="2026-12-31T23:00:00+00:00")

        karten = self._ic(db, bestand["schloss_id"])
        assert [(k.ttlock_credential_id, k.detail, k.gueltig_bis) for k in karten] == [
            (9001, f"{_MARKE}-KN1", "2026-12-31T23:00:00+00:00")]

    def test_zweiter_schreibvorgang_zieht_nach_statt_zu_doppeln(self, db, bestand):
        self._karte(db, bestand["schloss_id"])

        db.tuer_credentials.ic_karte_gesetzt(
            bestand["schloss_id"], credential_id=4711, name="Chip blau",
            kartennummer=f"{_MARKE}-KN1", gueltig_von=None,
            gueltig_bis="2027-06-30T22:00:00+00:00")

        karten = self._ic(db, bestand["schloss_id"])
        assert len(karten) == 1
        assert karten[0].gueltig_bis == "2027-06-30T22:00:00+00:00"
        # Der Stand des Schlosses bleibt, wo er war – wir haben nichts gelesen.
        assert karten[0].gesehen_am == "2026-08-21T06:00:00+00:00"

    def test_neue_zeile_erbt_den_stand_des_schlosses(self, db, bestand):
        """Ein frischer Zeitstempel machte jedes ANDERE Schloss zum veralteten
        Spiegel (`_veraltet`) und entwertete dort echte Befunde."""
        self._karte(db, bestand["schloss_id"], gesehen_am="2026-08-20T06:00:00+00:00")

        db.tuer_credentials.ic_karte_gesetzt(
            bestand["schloss_id"], credential_id=9002, name="Chip blau",
            kartennummer=f"{_MARKE}-KN2", gueltig_von=None, gueltig_bis=None)

        neu = [k for k in self._ic(db, bestand["schloss_id"])
               if k.ttlock_credential_id == 9002]
        assert [k.gesehen_am for k in neu] == ["2026-08-20T06:00:00+00:00"]

    def test_sperren_beendet_den_kritischen_befund_ohne_sync(self, db, bestand):
        """Der ganze Weg: verlorener Chip mit gültiger Karte am Schloss meldet sich
        kritisch – nach dem Löschen der Karte ist der Befund weg, nicht erst morgen."""
        from app.services import zutritt_abgleich_service as abgleich_service
        self._karte(db, bestand["schloss_id"])
        _sperren(db, bestand["chip"])
        vorher = [b for b in abgleich_service.abgleich(db)['befunde']
                  if b['schloss_id'] == bestand["schloss_id"]]
        assert [b['art'] for b in vorher] == [abgleich_service.BEFUND_SPERRE_OFFEN]

        db.tuer_credentials.ic_karte_entfernt(bestand["schloss_id"], 4711)
        # Beides gehört zusammen, und der Service tut es auch zusammen: Bliebe die
        # cardId an der Zeile stehen, meldete der Abgleich statt „öffnet noch" ein
        # „Karte fehlt am Schloss" – wieder ein Befund, den niemand braucht.
        db.tuer_berechtigungen.set_sync(bestand["ber"].id, ttlock_card_id=None,
                                        sync_status='gesperrt', sync_fehler=None,
                                        by="test")

        nachher = [b for b in abgleich_service.abgleich(db)['befunde']
                   if b['schloss_id'] == bestand["schloss_id"]]
        assert nachher == []


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
