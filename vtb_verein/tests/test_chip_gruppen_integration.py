"""Chip-Rechtegruppen (#169) gegen echtes PostgreSQL: Repository, Schema, Prune.

Geprüft wird, was sich nur an der Datenbank zeigt:
- Soft-Delete + History der drei neuen Tabellen (Fresh-Schema),
- der partielle Unique-Index (ein Name je lebender Gruppe, ein Paar je Zuordnung),
- die SOLL-Abfrage über mehrere Gruppen hinweg,
- die Migration v92→v93 auf einem Schema, das die Tabellen noch nicht kennt,
- die Prune-Registry: jede neue Soft-Delete-Tabelle muss aufräumbar sein.

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


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-gruppen-uploads")
    yield d
    d.close()


# Eigene Spuren erkennbar machen: Die Wegwerf-DB wird von allen Integrationstests
# geteilt, deshalb räumt die Fixture nur auf, was sie selbst angelegt hat – ein
# `DELETE FROM tuer_schloss` risse beim zweiten Lauf fremde Log-Zeilen mit.
_MARKE = 'GRPTEST'


@pytest.fixture()
def bestand(db):
    """Drei Schlösser und zwei Chips, auf denen die Gruppen arbeiten können."""
    from app.models.schliessanlage import SchluesselChip
    wie = (f'{_MARKE}%',)
    eigene_chips = ("SELECT id FROM schluessel_chip WHERE kartennummer LIKE %s", wie)
    with db.cursor() as cur:
        # Reihenfolge: erst die Berechtigungen (zeigen per gruppe_id auf die Gruppe),
        # dann die Gruppen-Tabellen, dann Chips/Schlösser.
        for tbl in ("tuer_berechtigung_history", "tuer_berechtigung"):
            cur.execute(f"DELETE FROM {tbl} WHERE chip_id IN ({eigene_chips[0]})", wie)
        # Gruppen legt nur dieses Modul an – die dürfen komplett weg.
        for tbl in ("chip_gruppe_zuordnung_history", "chip_gruppe_zuordnung",
                    "chip_gruppe_schloss_history", "chip_gruppe_schloss",
                    "chip_gruppe_history", "chip_gruppe"):
            cur.execute(f"DELETE FROM {tbl}")
        cur.execute("DELETE FROM schluessel_chip_history WHERE kartennummer LIKE %s", wie)
        cur.execute("DELETE FROM schluessel_chip WHERE kartennummer LIKE %s", wie)
        cur.execute("DELETE FROM tuer_schloss_history WHERE name LIKE %s", wie)
        cur.execute("DELETE FROM tuer_schloss WHERE name LIKE %s", wie)
        schloesser = []
        for nr in (1, 2, 3):
            cur.execute(
                "INSERT INTO tuer_schloss (ttlock_lock_id, name, created_by, updated_by) "
                "VALUES (%s,%s,'test','test') RETURNING id",
                (7000 + nr, f"{_MARKE} Tür {nr}"))
            schloesser.append(cur.fetchone()['id'])
    chips = [db.schluessel_chips.create(
        SchluesselChip(kartennummer=f"{_MARKE}-KN{nr}", bezeichnung=f"Chip {nr}"), "test").id
        for nr in (1, 2)]
    return {"schloesser": schloesser, "chips": chips}


class TestGruppeRepository:
    def test_anlegen_und_lesen(self, db, bestand):
        from app.models.schliessanlage import ChipGruppe
        g = db.chip_gruppen.create(ChipGruppe(name="Übungsleiter",
                                              beschreibung="Halle + Geräteraum"), "test")
        gelesen = db.chip_gruppen.get(g.id)
        assert gelesen.name == "Übungsleiter"
        assert gelesen.schloss_ids == []
        assert gelesen.anzahl_schloesser == 0 and gelesen.anzahl_chips == 0

    def test_name_nur_einmal_unter_den_lebenden(self, db, bestand):
        """LOWER(): „übungsleiter" wäre beim Zuordnen nicht von „Übungsleiter"
        zu unterscheiden."""
        import psycopg
        from app.models.schliessanlage import ChipGruppe
        db.chip_gruppen.create(ChipGruppe(name="Platzwarte"), "test")
        with pytest.raises(psycopg.errors.UniqueViolation):
            db.chip_gruppen.create(ChipGruppe(name="platzwarte"), "test")

    def test_geloeschte_gruppe_gibt_den_namen_frei(self, db, bestand):
        from app.models.schliessanlage import ChipGruppe
        alt = db.chip_gruppen.create(ChipGruppe(name="Vorstand"), "test")
        db.chip_gruppen.soft_delete(alt.id, "test")
        neu = db.chip_gruppen.create(ChipGruppe(name="Vorstand"), "test")
        assert neu.id != alt.id
        assert db.chip_gruppen.get(alt.id) is None

    def test_tueren_setzen_ist_eine_differenz(self, db, bestand):
        from app.models.schliessanlage import ChipGruppe
        s = bestand["schloesser"]
        g = db.chip_gruppen.create(ChipGruppe(name="Übungsleiter"), "test")
        db.chip_gruppen.set_schloesser(g.id, [s[0], s[1]], "test")
        assert db.chip_gruppen.schloss_ids(g.id) == sorted([s[0], s[1]])
        db.chip_gruppen.set_schloesser(g.id, [s[1], s[2]], "test")
        assert db.chip_gruppen.schloss_ids(g.id) == sorted([s[1], s[2]])

    def test_erneutes_zuordnen_belebt_dieselbe_zeile(self, db, bestand):
        """Sonst bekäme die History für jedes Hin und Her eine neue id-Reihe."""
        from app.models.schliessanlage import ChipGruppe
        s, c = bestand["schloesser"], bestand["chips"]
        g = db.chip_gruppen.create(ChipGruppe(name="Übungsleiter"), "test")
        db.chip_gruppen.set_schloesser(g.id, [s[0]], "test")
        db.chip_gruppen.chip_zuordnen(g.id, c[0], "test")
        with db.cursor() as cur:
            cur.execute("SELECT id FROM chip_gruppe_zuordnung WHERE gruppe_id=%s", (g.id,))
            erste_id = cur.fetchone()['id']
        db.chip_gruppen.chip_entfernen(g.id, c[0], "test")
        db.chip_gruppen.chip_zuordnen(g.id, c[0], "test")
        with db.cursor() as cur:
            cur.execute("SELECT id, version, deleted_at FROM chip_gruppe_zuordnung "
                        "WHERE gruppe_id=%s", (g.id,))
            zeilen = cur.fetchall()
        assert len(zeilen) == 1
        assert zeilen[0]['id'] == erste_id and zeilen[0]['deleted_at'] is None
        assert zeilen[0]['version'] == 3          # anlegen → löschen → beleben

    def test_jede_aenderung_landet_in_der_history(self, db, bestand):
        from app.models.schliessanlage import ChipGruppe
        c = bestand["chips"]
        g = db.chip_gruppen.create(ChipGruppe(name="Übungsleiter"), "test")
        db.chip_gruppen.chip_zuordnen(g.id, c[0], "test")
        db.chip_gruppen.chip_entfernen(g.id, c[0], "test")
        with db.cursor() as cur:
            cur.execute("SELECT version, deleted_at FROM chip_gruppe_zuordnung_history "
                        "WHERE gruppe_id=%s ORDER BY version", (g.id,))
            eintraege = cur.fetchall()
        assert [e['version'] for e in eintraege] == [1, 2]
        assert eintraege[-1]['deleted_at'] is not None

    def test_soll_vereinigt_die_gruppen_des_chips(self, db, bestand):
        from app.models.schliessanlage import ChipGruppe
        s, c = bestand["schloesser"], bestand["chips"]
        a = db.chip_gruppen.create(ChipGruppe(name="Abteilungsleiter"), "test")
        b = db.chip_gruppen.create(ChipGruppe(name="Übungsleiter"), "test")
        db.chip_gruppen.set_schloesser(a.id, [s[0], s[1]], "test")
        db.chip_gruppen.set_schloesser(b.id, [s[1], s[2]], "test")
        db.chip_gruppen.chip_zuordnen(a.id, c[0], "test")
        db.chip_gruppen.chip_zuordnen(b.id, c[0], "test")
        assert db.chip_gruppen.soll_schloss_ids_fuer_chip(c[0]) == sorted(s)
        assert db.chip_gruppen.soll_schloss_ids_fuer_chip(c[1]) == []

    def test_geloeschtes_schloss_zaehlt_nicht_mehr_zum_soll(self, db, bestand):
        """Sonst versuchte der Abgleich, eine abgebaute Tür anzulernen."""
        from app.models.schliessanlage import ChipGruppe
        s, c = bestand["schloesser"], bestand["chips"]
        g = db.chip_gruppen.create(ChipGruppe(name="Übungsleiter"), "test")
        db.chip_gruppen.set_schloesser(g.id, [s[0], s[1]], "test")
        db.chip_gruppen.chip_zuordnen(g.id, c[0], "test")
        with db.cursor() as cur:
            cur.execute("UPDATE tuer_schloss SET deleted_at=CURRENT_TIMESTAMP, "
                        "deleted_by='test', version=version+1 WHERE id=%s", (s[0],))
        assert db.chip_gruppen.soll_schloss_ids_fuer_chip(c[0]) == [s[1]]

    def test_quelle_gruppe_nennt_eine_fordernde_gruppe(self, db, bestand):
        from app.models.schliessanlage import ChipGruppe
        s, c = bestand["schloesser"], bestand["chips"]
        a = db.chip_gruppen.create(ChipGruppe(name="Abteilungsleiter"), "test")
        db.chip_gruppen.set_schloesser(a.id, [s[0]], "test")
        db.chip_gruppen.chip_zuordnen(a.id, c[0], "test")
        assert db.chip_gruppen.quelle_gruppe(c[0], s[0]) == a.id
        assert db.chip_gruppen.quelle_gruppe(c[0], s[1]) is None

    def test_gruppen_fuer_chip_und_zaehler(self, db, bestand):
        from app.models.schliessanlage import ChipGruppe
        s, c = bestand["schloesser"], bestand["chips"]
        g = db.chip_gruppen.create(ChipGruppe(name="Übungsleiter"), "test")
        db.chip_gruppen.set_schloesser(g.id, [s[0], s[1]], "test")
        db.chip_gruppen.chip_zuordnen(g.id, c[0], "test")
        db.chip_gruppen.chip_zuordnen(g.id, c[1], "test")
        assert [x.name for x in db.chip_gruppen.gruppen_fuer_chip(c[0])] == ["Übungsleiter"]
        gelesen = db.chip_gruppen.get(g.id)
        assert gelesen.anzahl_schloesser == 2 and gelesen.anzahl_chips == 2


class TestBerechtigungsHerkunft:
    def test_gruppe_id_wird_gespeichert_und_gelesen(self, db, bestand):
        from app.models.schliessanlage import ChipGruppe, TuerBerechtigung
        s, c = bestand["schloesser"], bestand["chips"]
        g = db.chip_gruppen.create(ChipGruppe(name="Übungsleiter"), "test")
        ber = db.tuer_berechtigungen.create(
            TuerBerechtigung(chip_id=c[0], schloss_id=s[0], gruppe_id=g.id), "test")
        assert ber.gruppe_id == g.id
        assert ber.gruppe_name == "Übungsleiter"

    def test_von_hand_erteilt_bleibt_ohne_herkunft(self, db, bestand):
        from app.models.schliessanlage import TuerBerechtigung
        s, c = bestand["schloesser"], bestand["chips"]
        ber = db.tuer_berechtigungen.create(
            TuerBerechtigung(chip_id=c[0], schloss_id=s[0]), "test")
        assert ber.gruppe_id is None and ber.gruppe_name is None

    def test_herkunft_landet_in_der_history(self, db, bestand):
        """Die Audit-Funktion muss die neue Spalte mitführen – sonst bliebe in der
        History still leer, woher eine Berechtigung stammte."""
        from app.models.schliessanlage import ChipGruppe, TuerBerechtigung
        s, c = bestand["schloesser"], bestand["chips"]
        g = db.chip_gruppen.create(ChipGruppe(name="Übungsleiter"), "test")
        ber = db.tuer_berechtigungen.create(
            TuerBerechtigung(chip_id=c[0], schloss_id=s[0], gruppe_id=g.id), "test")
        with db.cursor() as cur:
            cur.execute("SELECT gruppe_id FROM tuer_berechtigung_history WHERE id=%s",
                        (ber.id,))
            assert cur.fetchone()['gruppe_id'] == g.id


class TestMigration:
    def test_v92_nach_v93_legt_tabellen_und_spalte_an(self, db):
        """Fresh == Migriert: Die Migration muss dasselbe erzeugen wie der
        Frischaufbau – auf einem Schema, das die Tabellen noch nicht kennt."""
        with db.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS chip_gruppe_zuordnung_history, "
                        "chip_gruppe_zuordnung, chip_gruppe_schloss_history, "
                        "chip_gruppe_schloss, chip_gruppe_history CASCADE")
            cur.execute("ALTER TABLE tuer_berechtigung DROP COLUMN IF EXISTS gruppe_id")
            cur.execute("ALTER TABLE tuer_berechtigung_history DROP COLUMN IF EXISTS gruppe_id")
            cur.execute("DROP TABLE IF EXISTS chip_gruppe CASCADE")

        db._database._migrate_v92_to_v93()

        with db.cursor() as cur:
            cur.execute("SELECT tablename FROM pg_tables WHERE tablename LIKE 'chip_gruppe%'")
            tabellen = {r['tablename'] for r in cur.fetchall()}
            cur.execute("SELECT column_name FROM information_schema.columns "
                        "WHERE table_name='tuer_berechtigung' AND column_name='gruppe_id'")
            spalte = cur.fetchone()
            cur.execute("SELECT COUNT(*) AS n FROM information_schema.triggers "
                        "WHERE trigger_name LIKE 'trig_chip_gruppe%'")
            trigger = cur.fetchone()['n']
        assert tabellen == {
            'chip_gruppe', 'chip_gruppe_history',
            'chip_gruppe_schloss', 'chip_gruppe_schloss_history',
            'chip_gruppe_zuordnung', 'chip_gruppe_zuordnung_history'}
        assert spalte is not None
        assert trigger == 6                      # 3 Tabellen × INSERT/UPDATE

    def test_migration_ist_wiederholbar(self, db):
        db._database._migrate_v92_to_v93()
        db._database._migrate_v92_to_v93()
        with db.cursor() as cur:
            cur.execute("SELECT version FROM schema_version WHERE id=1")
            assert cur.fetchone()['version'] == 93


class TestPruneRegistry:
    def test_neue_tabellen_sind_registriert(self):
        """Ohne Registry-Eintrag wüchsen soft-gelöschte Zeilen unbegrenzt."""
        from app.services.prune_service import PRUNE_REGISTRY
        namen = {e.name for e in PRUNE_REGISTRY}
        assert {"chip_gruppe", "chip_gruppe_schloss", "chip_gruppe_zuordnung"} <= namen

    def test_kinder_stehen_vor_ihren_eltern(self):
        """Reihenfolge Kinder-vor-Eltern – sonst blockiert der FK das echte Löschen."""
        from app.services.prune_service import PRUNE_REGISTRY
        reihenfolge = [e.name for e in PRUNE_REGISTRY]
        for kind in ("chip_gruppe_schloss", "chip_gruppe_zuordnung", "tuer_berechtigung"):
            assert reihenfolge.index(kind) < reihenfolge.index("chip_gruppe")

    def test_gruppe_kennt_ihre_kinder(self):
        from app.services.prune_service import PRUNE_REGISTRY
        gruppe = next(e for e in PRUNE_REGISTRY if e.name == "chip_gruppe")
        kinder = {(c.table, c.fk) for c in gruppe.children}
        assert kinder == {("chip_gruppe_schloss", "gruppe_id"),
                          ("chip_gruppe_zuordnung", "gruppe_id"),
                          ("tuer_berechtigung", "gruppe_id")}

    def test_chip_und_schloss_wurden_um_die_gruppen_erweitert(self):
        """Ein Chip in einer Gruppe darf nicht am FK hängen bleiben."""
        from app.services.prune_service import PRUNE_REGISTRY
        chip = next(e for e in PRUNE_REGISTRY if e.name == "schluessel_chip")
        schloss = next(e for e in PRUNE_REGISTRY if e.name == "tuer_schloss")
        assert ("chip_gruppe_zuordnung", "chip_id") in {(c.table, c.fk) for c in chip.children}
        assert ("chip_gruppe_schloss", "schloss_id") in {(c.table, c.fk) for c in schloss.children}
