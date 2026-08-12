"""Stand des Spielplan-Imports (#171): Repository, Migration und Endpunkt.

Im Terminkalender war nicht zu erkennen, von wann der Spielplan stammt. Festgehalten
wird deshalb das ÄNDERUNGSDATUM der eingelesenen Datei – der Stand, den der Anwender
meint; wann jemand sie eingelesen hat, steht daneben.

Der DB-Teil läuft nur mit ``VTB_TEST_DATABASE_URL``; die Endpunkt-Tests brauchen
keine Datenbank (Stubs, Muster wie test_schliessanlage_gruppen_api).
"""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402

from app.models.permission import Permission  # noqa: E402
from backend.api import imports as api  # noqa: E402

_URL = os.getenv("VTB_TEST_DATABASE_URL")


# --------------------------------------------------------------- Endpunkt

def _user(*perms, role='mitglied'):
    keys = set(perms)
    return SimpleNamespace(
        id=1, username='verwalter', role=role, active=True,
        has_permission=lambda p: role == 'admin' or p in keys,
        has_permission_global=lambda p: role == 'admin' or p in keys,
        allowed_abteilungen=lambda p: None,
    )


class _StandRepo:
    def __init__(self, stand=None):
        self.stand = stand
        self.gesetzt = []

    def get(self):
        return self.stand

    def set(self, **kw):
        self.gesetzt.append(kw)
        self.stand = kw
        return kw


class TestStandEndpunkt:
    def test_ohne_import_leere_antwort(self):
        db = SimpleNamespace(dfbnet_import_stand=_StandRepo(None))
        assert api.dfbnet_stand(_user(), db) == {}

    def test_liefert_den_gespeicherten_stand(self):
        stand = {'dateiname': 'spielplan.csv', 'datei_datum': '2026-08-12T09:00:00+00:00',
                 'importiert_am': '2026-08-12T11:39:00+00:00', 'importiert_von': 'vsuess'}
        db = SimpleNamespace(dfbnet_import_stand=_StandRepo(stand))
        assert api.dfbnet_stand(_user(), db) == stand

    def test_kein_eigenes_recht_noetig(self):
        """Wer die Termine sieht, darf wissen, wie alt sie sind – die Auskunft ist
        ein Dateiname und zwei Zeitpunkte."""
        db = SimpleNamespace(dfbnet_import_stand=_StandRepo({'importiert_am': 'x'}))
        assert api.dfbnet_stand(_user(), db) == {'importiert_am': 'x'}


# --------------------------------------------------------------- Datenbank

pg = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)")


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-dfbnet-stand-uploads")
    yield d
    d.close()


@pytest.fixture()
def leer(db):
    with db.cursor() as cur:
        # History mit leeren: Sie ist der Verlauf, den die Tests hier prüfen –
        # bliebe sie stehen, zählte jeder Lauf die Zeilen des vorigen mit.
        cur.execute("DELETE FROM dfbnet_import_stand_history")
        cur.execute("DELETE FROM dfbnet_import_stand")
    return db


@pg
class TestStandRepository:
    def test_ohne_import_kein_stand(self, leer):
        assert leer.dfbnet_import_stand.get() is None

    def test_erster_import_legt_die_zeile_an(self, leer):
        stand = leer.dfbnet_import_stand.set(
            dateiname="spielplan.csv", datei_datum="2026-08-12T09:00:00+00:00",
            anzahl_spiele=157, by="vsuess")
        assert stand['dateiname'] == "spielplan.csv"
        assert stand['anzahl_spiele'] == 157
        assert stand['importiert_von'] == "vsuess"
        assert stand['datei_datum'].isoformat().startswith("2026-08-12T")

    def test_zweiter_import_ueberschreibt_statt_anzuhaengen(self, leer):
        """Es gibt genau einen Stand – sonst wüchse die Tabelle unbegrenzt und
        bräuchte eine Bereinigung, die sie nicht hat."""
        leer.dfbnet_import_stand.set(dateiname="alt.csv", datei_datum=None,
                                     anzahl_spiele=1, by="a")
        leer.dfbnet_import_stand.set(dateiname="neu.csv", datei_datum=None,
                                     anzahl_spiele=2, by="b")
        with leer.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n, MAX(version) AS v FROM dfbnet_import_stand")
            row = cur.fetchone()
        assert row['n'] == 1 and row['v'] == 2
        assert leer.dfbnet_import_stand.get()['dateiname'] == "neu.csv"

    def test_ohne_dateidatum_bleibt_der_zeitpunkt_des_einlesens(self, leer):
        """Ein Browser ohne lastModified darf den Stand nicht verhindern."""
        stand = leer.dfbnet_import_stand.set(dateiname="x.csv", datei_datum=None,
                                             anzahl_spiele=None, by="a")
        assert stand['datei_datum'] is None
        assert stand['importiert_am'] is not None


@pg
class TestVerlauf:
    """Die History macht aus der einen Zeile ein Import-Protokoll: wer wie oft."""

    def test_jeder_import_hinterlaesst_eine_zeile(self, leer):
        for nr, wer in ((1, "vsuess"), (2, "marko"), (3, "vsuess")):
            leer.dfbnet_import_stand.set(dateiname=f"lauf{nr}.csv", datei_datum=None,
                                         anzahl_spiele=nr, by=wer)
        verlauf = leer.dfbnet_import_stand.verlauf()
        assert len(verlauf) == 3
        assert [v['importiert_von'] for v in verlauf].count("vsuess") == 2

    def test_juengster_zuerst(self, leer):
        leer.dfbnet_import_stand.set(dateiname="alt.csv", datei_datum=None,
                                     anzahl_spiele=1, by="a")
        leer.dfbnet_import_stand.set(dateiname="neu.csv", datei_datum=None,
                                     anzahl_spiele=2, by="b")
        assert leer.dfbnet_import_stand.verlauf()[0]['dateiname'] == "neu.csv"

    def test_limit_wird_beachtet(self, leer):
        for nr in range(5):
            leer.dfbnet_import_stand.set(dateiname=f"{nr}.csv", datei_datum=None,
                                         anzahl_spiele=nr, by="a")
        assert len(leer.dfbnet_import_stand.verlauf(limit=2)) == 2

    def test_ohne_import_leerer_verlauf(self, leer):
        assert leer.dfbnet_import_stand.verlauf() == []

    def test_history_ist_ein_protokoll_mit_frist(self):
        """Sie wächst mit jedem Import – ohne Löschpfad liefe sie unbegrenzt voll.
        Die Frist läuft ab `importiert_am`: `created_at` trägt in jeder Version den
        Zeitpunkt der ERSTEN Zeile und wäre als Alter untauglich."""
        from app.services.prune_service import LOG_REGISTRY
        regel = next(r for r in LOG_REGISTRY if r.table == "dfbnet_import_stand_history")
        assert regel.ts_expr == "importiert_am"


@pg
class TestMigration:
    def test_v93_nach_v94_legt_tabelle_history_und_trigger_an(self, db):
        """Fresh == Migriert: auf einem Schema, das die Tabellen noch nicht kennt.

        Der Trigger gehört ausdrücklich dazu – ohne ihn bliebe die History leer und
        das Import-Protokoll wäre eine leere Versprechung."""
        with db.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS dfbnet_import_stand_history")
            cur.execute("DROP TABLE IF EXISTS dfbnet_import_stand CASCADE")
        db._database._migrate_v93_to_v94()
        with db.cursor() as cur:
            cur.execute("SELECT column_name FROM information_schema.columns "
                        "WHERE table_name='dfbnet_import_stand'")
            spalten = {r['column_name'] for r in cur.fetchall()}
            cur.execute("SELECT COUNT(*) AS n FROM information_schema.tables "
                        "WHERE table_name='dfbnet_import_stand_history'")
            history = cur.fetchone()['n']
            cur.execute("SELECT COUNT(*) AS n FROM information_schema.triggers "
                        "WHERE trigger_name LIKE 'trig_dfbnet_import_stand%'")
            trigger = cur.fetchone()['n']
        assert {'dateiname', 'datei_datum', 'importiert_am', 'importiert_von',
                'anzahl_spiele'} <= spalten
        assert history == 1
        assert trigger == 2                      # INSERT + UPDATE

    def test_migration_ist_wiederholbar(self, db):
        db._database._migrate_v93_to_v94()
        db._database._migrate_v93_to_v94()
        with db.cursor() as cur:
            cur.execute("SELECT version FROM schema_version WHERE id=1")
            assert cur.fetchone()['version'] == 94

    def test_kein_prune_eintrag_noetig(self):
        """Eine Tabelle mit genau einer überschriebenen Zeile wächst nicht – sie
        gehört bewusst NICHT in die Registry (anders als jede Soft-Delete-Tabelle).

        Die Ausnahme ist mit Begründung im Inventur-Wächter hinterlegt, siehe
        `OHNE_PFAD` in test_prune_integration.test_jede_tabelle_hat_einen_loeschpfad."""
        from app.services.prune_service import PRUNE_REGISTRY
        assert not any(e.table == "dfbnet_import_stand" for e in PRUNE_REGISTRY)
