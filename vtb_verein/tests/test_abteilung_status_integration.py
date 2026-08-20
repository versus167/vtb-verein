"""Vom Abteilungs-Status zur Funktion `passiv` – der Upgrade-Pfad v103 → v105.

Produktiv steht v103; beim Deploy laufen **beide** Migrationen hintereinander,
deshalb prüft diese Datei die Kette und nicht die Einzelschritte:

* **v104** dampft den Status auf `aktiv`/`passiv` ein. Die Rollen (`trainer`,
  `vorstand`, `ehrenmitglied`) werden zu `aktiv`, nicht zu `passiv` – sie waren
  beitragspflichtig und bleiben es. Alles andere wäre ein stiller Beitragserlass.
* **v105** macht aus `passiv` eine Funktion und entfernt die Spalte. Damit hat die
  Aussage einen Zeitraum, den das Kennzeichen nie hatte.

Der heikle Teil sind die Beitragsregeln, und dort **kehrt sich die Bedeutung um**:
`bedingung_abteilung_status = 'passiv'` ist der reduzierte Passiv-Beitrag, der
Passive gerade *treffen* soll – daraus wird ein Einschluss, aus dem Normalfall eine
Ausnahme. Wer das verwechselt, verliert Beiträge, ohne dass ein Fehler erscheint.

Läuft nur mit ``VTB_TEST_DATABASE_URL`` (leere Wegwerf-DB).
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

MARKE = "abtstatustest"
ROLLEN = ('trainer', 'vorstand', 'ehrenmitglied')

# Die Triggerfassung aus v103 – sie schrieb `status` mit. Der Frischaufbau kennt
# sie nicht mehr, also stellen wir sie für den Test her: Nur so zeigt sich, dass
# der alte Wert vor dem Entfernen der Spalte in der History landet.
_TRIGGER_V103 = """
    CREATE OR REPLACE FUNCTION fn_mitglied_abteilung_audit_update() RETURNS TRIGGER
    LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.version != OLD.version THEN
            INSERT INTO mitglied_abteilung_history (
                id, version, mitglied_id, abteilung_id, status, von, bis,
                created_at, created_by, updated_at, updated_by, deleted_at, deleted_by
            ) VALUES (
                NEW.id, NEW.version, NEW.mitglied_id, NEW.abteilung_id, NEW.status, NEW.von, NEW.bis,
                NEW.created_at, NEW.created_by, NEW.updated_at, NEW.updated_by,
                NEW.deleted_at, NEW.deleted_by
            );
        END IF;
        RETURN NEW;
    END; $$;
"""


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-abtstatus-uploads")
    yield d
    d.close()


def _aufraeumen(db):
    with db.cursor() as cur:
        # Die Passiv-Funktionen legt die Migration selbst an – mit created_by
        # 'SYSTEM'. Sie hängen an unseren Mitgliedern, also über die ausräumen.
        for tabelle in ('mitglied_funktion_history', 'mitglied_funktion'):
            cur.execute(f"DELETE FROM {tabelle} WHERE mitglied_id IN "
                        "(SELECT id FROM mitglied WHERE created_by = %s)", (MARKE,))
        for tabelle in ('beitragsregel_history', 'beitragsregel',
                        'mitglied_abteilung_history', 'mitglied_abteilung',
                        'mitglied_history', 'mitglied',
                        'abteilung_history', 'abteilung'):
            cur.execute(f"DELETE FROM {tabelle} WHERE created_by = %s", (MARKE,))


@pytest.fixture(autouse=True)
def clean(db):
    _aufraeumen(db)
    yield
    _aufraeumen(db)
    _v105_wiederherstellen(db)


def _v103_stand(db):
    """Den Schema-Stand von v103 nachbauen: beide Spalten zurück, alte Trigger-
    fassung, Version auf 103."""
    from app.db.database import (_FN_BEITRAGSREGEL_AUDIT_INSERT,
                                 _FN_BEITRAGSREGEL_AUDIT_UPDATE)
    with db.cursor() as cur:
        cur.execute("ALTER TABLE mitglied_abteilung ADD COLUMN IF NOT EXISTS status "
                    "TEXT NOT NULL DEFAULT 'aktiv'")
        cur.execute("ALTER TABLE beitragsregel ADD COLUMN IF NOT EXISTS "
                    "bedingung_abteilung_status TEXT")
        cur.execute(_TRIGGER_V103)
        # Die Beitragsregel-Trigger der aktuellen Fassung kennen die Spalte nicht
        # mehr – für den Test genügt das, sie schreiben nur weniger in die History.
        cur.execute(_FN_BEITRAGSREGEL_AUDIT_INSERT)
        cur.execute(_FN_BEITRAGSREGEL_AUDIT_UPDATE)
        cur.execute("UPDATE schema_version SET version = 103 WHERE id = 1")


def _v105_wiederherstellen(db):
    """Nach dem Test wieder den Stand herstellen, den der Frischaufbau liefert –
    die Wegwerf-DB teilen sich alle Integrationstests."""
    from app.db.database import (_FN_MITGLIED_ABTEILUNG_AUDIT_UPDATE)
    with db.cursor() as cur:
        cur.execute("ALTER TABLE mitglied_abteilung DROP COLUMN IF EXISTS status")
        cur.execute("ALTER TABLE beitragsregel DROP COLUMN IF EXISTS bedingung_abteilung_status")
        cur.execute(_FN_MITGLIED_ABTEILUNG_AUDIT_UPDATE)
        cur.execute("UPDATE schema_version SET version = 105 WHERE id = 1")


def _migrieren(db):
    db._database._migrate_v103_to_v104()
    db._database._migrate_v104_to_v105()


def _abteilung(db, name="AS-Sparte"):
    with db.cursor() as cur:
        cur.execute("INSERT INTO abteilung (name, created_by, updated_by) "
                    "VALUES (%s, %s, %s) RETURNING id", (name, MARKE, MARKE))
        return cur.fetchone()["id"]


def _mitglied(db, nachname="Status"):
    from app.models.mitglied import Mitglied
    return db.create_mitglied(
        Mitglied(vorname="As", nachname=nachname, eintrittsdatum="2020-01-01",
                 zahlungsart="lastschrift"), created_by=MARKE).id


def _zuordnen(db, mitglied_id, abteilung_id, status, von="2020-01-01", bis=None):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO mitglied_abteilung (mitglied_id, abteilung_id, status, von, bis, "
            "created_by, updated_by) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (mitglied_id, abteilung_id, status, von, bis, MARKE, MARKE))
        return cur.fetchone()["id"]


def _regel(db, abteilung_id, bedingung):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO beitragsregel (name, abteilung_id, betrag_pro_monat, einzug_turnus, "
            "gueltig_ab, bedingung_abteilung_status, created_by, updated_by) "
            "VALUES ('AS-Regel', %s, 5.0, 'quartal', '2020-01-01', %s, %s, %s) RETURNING id",
            (abteilung_id, bedingung, MARKE, MARKE))
        return cur.fetchone()["id"]


def _funktionen(db, mitglied_id):
    return [(f.funktion, f.abteilung_id, f.von, f.bis)
            for f in db.list_mitglied_funktionen(mitglied_id)]


# --------------------------------------------------------------- Zuordnungen

def test_rollen_werden_aktiv_und_nicht_passiv(db):
    """Sie waren beitragspflichtig (beitragsfrei war nur 'passiv') und bleiben es –
    auch 'ehrenmitglied', wo 'passiv' verführerisch wäre."""
    _v103_stand(db)
    abt = _abteilung(db)
    zeilen = {rolle: _zuordnen(db, _mitglied(db, rolle), abt, rolle) for rolle in ROLLEN}

    _migrieren(db)

    for rolle, zid in zeilen.items():
        zuordnung = db.get_mitglied_abteilung(zid)
        assert zuordnung is not None, rolle
        assert _funktionen(db, zuordnung.mitglied_id) == [], rolle


def test_passiv_wird_zur_funktion_mit_abteilung_und_zeitraum(db):
    _v103_stand(db)
    abt = _abteilung(db)
    mid = _mitglied(db, "Passiv")
    _zuordnen(db, mid, abt, 'passiv', von="2024-03-01", bis="2026-12-31")

    _migrieren(db)

    assert _funktionen(db, mid) == [('passiv', abt, "2024-03-01", "2026-12-31")]


def test_aktive_bekommen_keine_funktion(db):
    _v103_stand(db)
    abt = _abteilung(db)
    mid = _mitglied(db, "Aktiv")
    _zuordnen(db, mid, abt, 'aktiv')

    _migrieren(db)

    assert _funktionen(db, mid) == []


def test_der_alte_status_bleibt_in_der_history(db):
    """Die Spalte fällt weg – der Wert nicht: Ein version-Bump hebt ihn vorher in
    die History, den Beleg dafür, was einmal galt."""
    _v103_stand(db)
    abt = _abteilung(db)
    mid = _mitglied(db, "Passiv")
    zid = _zuordnen(db, mid, abt, 'passiv')

    _migrieren(db)

    with db.cursor() as cur:
        cur.execute("SELECT status FROM mitglied_abteilung_history WHERE id = %s "
                    "ORDER BY version", (zid,))
        assert 'passiv' in [r["status"] for r in cur.fetchall()]


def test_die_spalten_sind_danach_weg(db):
    _v103_stand(db)
    _migrieren(db)
    with db.cursor() as cur:
        assert not db._database._hat_spalte(cur, 'mitglied_abteilung', 'status')
        assert not db._database._hat_spalte(cur, 'beitragsregel', 'bedingung_abteilung_status')
        cur.execute("SELECT version FROM schema_version WHERE id = 1")
        assert cur.fetchone()["version"] == 105


def test_die_funktion_passiv_ist_angelegt(db):
    _v103_stand(db)
    _migrieren(db)
    assert 'passiv' in db.funktionen.list_keys()


# ------------------------------------------------------------ Beitragsregeln

def _regel_stand(db, regel_id):
    r = db.beitragsregeln.get(regel_id)
    return (list(r.bedingung_funktionen or []), list(r.ausnahme_funktionen or []),
            list(r.ausnahme_abteilung_ids or []))


@pytest.mark.parametrize("bedingung", [None, '', 'aktiv', 'trainer'])
def test_normalfall_wird_zur_ausnahme(db, bedingung):
    """Ohne Angabe (oder mit 'aktiv') galt „alle außer passiv" – genau das sagt
    jetzt eine Ausnahme. 'trainer' läuft über v104 vorher nach 'aktiv'."""
    _v103_stand(db)
    abt = _abteilung(db)
    rid = _regel(db, abt, bedingung)

    _migrieren(db)

    bedingungen, ausnahmen, ausnahme_abt = _regel_stand(db, rid)
    assert ausnahmen == ['passiv'] and ausnahme_abt == [abt]
    assert bedingungen == []


def test_passiv_beitrag_wird_zum_einschluss(db):
    """Hier kehrt sich die Bedeutung um: Die Regel soll Passive *treffen*."""
    _v103_stand(db)
    abt = _abteilung(db)
    rid = _regel(db, abt, 'passiv')

    _migrieren(db)

    bedingungen, ausnahmen, _ = _regel_stand(db, rid)
    assert bedingungen == ['passiv']
    assert ausnahmen == []


def test_alle_bleibt_alle(db):
    """'aktiv,passiv' hieß „ohne Unterschied" – dann ist weder ein- noch
    auszuschließen."""
    _v103_stand(db)
    abt = _abteilung(db)
    rid = _regel(db, abt, 'aktiv,passiv')

    _migrieren(db)

    bedingungen, ausnahmen, _ = _regel_stand(db, rid)
    assert bedingungen == [] and ausnahmen == []


def test_vereinsbeitrag_bleibt_unberuehrt(db):
    """Eine Regel ohne Abteilung kannte den Status nie – und Passive zahlen den
    Vereinsbeitrag weiter."""
    _v103_stand(db)
    rid = _regel(db, None, None)

    _migrieren(db)

    bedingungen, ausnahmen, _ = _regel_stand(db, rid)
    assert bedingungen == [] and ausnahmen == []
