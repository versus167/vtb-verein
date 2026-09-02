"""
Belegungsplan der eigenen Plätze gegen echtes PostgreSQL (#152).

Die Abfrage ist absichtlich anders zugeschnitten als jede andere Termin-Abfrage, und
jede Abweichung ist eine Entscheidung, die still falsch sein könnte:

* **Kein Kader-Filter.** Wer den Platz mäht, muss jede Belegung sehen. Genau das lässt
  sich mit Fakes nicht prüfen — es geht um einen JOIN, der die ACL-CTE NICHT enthält.
* **Nur eigene Plätze.** Ein Auswärtsspiel belegt nichts, was dieser Verein pflegt.
* **Abgesagte bleiben drin**, soft-gelöschte nicht.
* **Plätze ohne Belegung** stehen trotzdem im Plan.

Läuft nur, wenn ``VTB_TEST_DATABASE_URL`` auf eine LEERE Wegwerf-DB zeigt
(VereinsDB legt das Schema beim Connect an). Beispiel:
    docker run -d --rm --name vtb-pg-pb -e POSTGRES_PASSWORD=test \\
        -e POSTGRES_DB=pbtest -e TZ=Europe/Berlin -p 55435:5432 postgres:18
    VTB_TEST_DATABASE_URL=postgresql://postgres:test@localhost:55435/pbtest \\
        ./venv/bin/python -m pytest vtb_verein/tests/test_platzbelegung_integration.py
"""
import os

import pytest

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

MARKE = "PLATZBELEGUNG-TEST"
VON, BIS = "2026-09-07", "2026-09-13"


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-platzbelegung-uploads")
    yield d
    d.close()


def _leeren(db):
    """Nur die eigenen Spuren – die Wegwerf-DB teilt sich dieses Modul mit anderen.

    `termine` und `spielstaette` per Marke, nicht per TRUNCATE: Die beiden
    Platzhalter-Spielstätten sind Schema-Bestandteil und dürfen nicht fallen.
    """
    with db.cursor() as cur:
        for tabelle in ("termine_history", "termine"):
            cur.execute(f"DELETE FROM {tabelle} WHERE created_by = %s", (MARKE,))
        for tabelle in ("spielstaette_history", "spielstaette"):
            cur.execute(f"DELETE FROM {tabelle} WHERE created_by = %s", (MARKE,))
        for tabelle in ("mannschaft_history", "mannschaft"):
            cur.execute(f"DELETE FROM {tabelle} WHERE created_by = %s", (MARKE,))
        for tabelle in ("abteilung_history", "abteilung"):
            cur.execute(f"DELETE FROM {tabelle} WHERE created_by = %s", (MARKE,))


@pytest.fixture(autouse=True)
def sauber(db):
    _leeren(db)
    yield
    _leeren(db)


def _platz(db, name, ist_eigen=True, parallel=1):
    with db.cursor() as cur:
        cur.execute("INSERT INTO spielstaette (name, ist_eigen, parallel_moeglich, "
                    "created_by, updated_by) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                    (f"{MARKE} {name}", ist_eigen, parallel, MARKE, MARKE))
        return cur.fetchone()["id"]


def _mannschaft(db, name="Erste", abteilung="Fußball"):
    with db.cursor() as cur:
        cur.execute("INSERT INTO abteilung (name, created_by, updated_by) "
                    "VALUES (%s, %s, %s) RETURNING id",
                    (f"{MARKE}-{abteilung}", MARKE, MARKE))
        aid = cur.fetchone()["id"]
        cur.execute("INSERT INTO mannschaft (abteilung_id, name, saison, created_by, "
                    "updated_by) VALUES (%s, %s, '2026/27', %s, %s) RETURNING id",
                    (aid, f"{MARKE}-{name}", MARKE, MARKE))
        return cur.fetchone()["id"]


def _termin(db, mannschaft_id, platz_id, beginn, ende=None, typ="training",
            status="geplant", geloescht=False):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO termine (mannschaft_id, typ, beginn, ende, spielstaette_id, "
            "status, created_by, updated_by, deleted_at, deleted_by) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (mannschaft_id, typ, beginn, ende, platz_id, status, MARKE, MARKE,
             "2026-01-01" if geloescht else None, MARKE if geloescht else None),
        )
        return cur.fetchone()["id"]


def _ids(db):
    return [t.id for t in db.termine.belegung(VON, BIS)]


class TestZuschnitt:

    def test_fremde_spielstaette_bleibt_draussen(self, db):
        """Ein Auswärtsspiel belegt nichts, was dieser Verein zu pflegen hätte."""
        man = _mannschaft(db)
        eigen = _termin(db, man, _platz(db, "Platz 1"), "2026-09-09T18:00")
        _termin(db, man, _platz(db, "Gegner-Arena", ist_eigen=False), "2026-09-09T15:00")

        assert _ids(db) == [eigen]

    def test_platzhalter_zeilen_bleiben_draussen(self, db):
        """„Kein Vereinsgelände" ist eine gültige Antwort im Termin, aber kein Platz."""
        man = _mannschaft(db)
        with db.cursor() as cur:
            cur.execute("SELECT id FROM spielstaette WHERE platzhalter = 'auswaerts'")
            platzhalter = cur.fetchone()["id"]
        _termin(db, man, platzhalter, "2026-09-09T18:00")

        assert _ids(db) == []
        assert not [p for p in db.spielstaetten.list_eigene()
                    if p.platzhalter is not None]

    def test_termine_aller_abteilungen_kommen_mit(self, db):
        """Der Kern von #152: Der Platzwart sieht JEDE Belegung. Käme hier die
        Kader-ACL ins Spiel, zeigte der Plan einen Platz als frei, den eine andere
        Abteilung längst belegt hat — schlimmer als gar keine Ansicht."""
        platz = _platz(db, "Platz 1")
        fussball = _termin(db, _mannschaft(db, "Erste", "Fußball"), platz,
                           "2026-09-09T18:00")
        handball = _termin(db, _mannschaft(db, "Damen", "Handball"), platz,
                           "2026-09-10T18:00")

        assert sorted(_ids(db)) == sorted([fussball, handball])

    def test_abgesagte_bleiben_drin(self, db):
        """Für den Platzwart die interessantere Nachricht: Der Platz ist doch frei."""
        man = _mannschaft(db)
        abgesagt = _termin(db, man, _platz(db, "Platz 1"), "2026-09-09T18:00",
                           status="abgesagt")

        gefunden = db.termine.belegung(VON, BIS)
        assert [t.id for t in gefunden] == [abgesagt]
        assert gefunden[0].status == "abgesagt"

    def test_geloeschte_termine_und_plaetze_fallen_weg(self, db):
        man = _mannschaft(db)
        platz = _platz(db, "Platz 1")
        _termin(db, man, platz, "2026-09-09T18:00", geloescht=True)
        weiterer = _platz(db, "Platz 2")
        _termin(db, man, weiterer, "2026-09-10T18:00")
        db.spielstaetten.mark_deleted(weiterer, MARKE)

        assert _ids(db) == []
        assert weiterer not in [p.id for p in db.spielstaetten.list_eigene()]

    def test_fenster_grenzt_ab(self, db):
        man = _mannschaft(db)
        platz = _platz(db, "Platz 1")
        drin_anfang = _termin(db, man, platz, "2026-09-07T09:00")
        drin_ende = _termin(db, man, platz, "2026-09-13T20:00")
        _termin(db, man, platz, "2026-09-06T18:00")
        _termin(db, man, platz, "2026-09-14T18:00")

        assert sorted(_ids(db)) == sorted([drin_anfang, drin_ende])

    def test_termin_traegt_mannschaft_und_platz_namen(self, db):
        """Die Anzeige braucht beides; ein zweiter Aufruf je Zeile wäre Unfug."""
        man = _mannschaft(db, "Erste")
        _termin(db, man, _platz(db, "Platz 1"), "2026-09-09T18:00", ende="2026-09-09T19:30")

        t = db.termine.belegung(VON, BIS)[0]
        assert t.mannschaft_name == f"{MARKE}-Erste"
        assert t.spielstaette_name == f"{MARKE} Platz 1"
        assert t.ende == "2026-09-09T19:30"


class TestPlaetze:

    def test_platz_ohne_belegung_steht_trotzdem_im_plan(self, db):
        """Die freie Zeile IST die Aussage. Käme der Platz nur über seine Termine mit,
        verschwände er genau dann, wenn er interessant wird."""
        leer = _platz(db, "Platz 3")

        assert leer in [p.id for p in db.spielstaetten.list_eigene()]

    def test_fremde_spielstaetten_sind_keine_planzeilen(self, db):
        fremd = _platz(db, "Gegner-Arena", ist_eigen=False)

        assert fremd not in [p.id for p in db.spielstaetten.list_eigene()]

    def test_kapazitaet_kommt_mit(self, db):
        platz = _platz(db, "Kleinfeld", parallel=2)

        treffer = [p for p in db.spielstaetten.list_eigene() if p.id == platz]
        assert treffer and treffer[0].parallel_moeglich == 2


def test_neues_recht_ist_ueber_die_matrix_vergebbar():
    """Ohne Eintrag in PERMISSION_GROUPS wäre der Key nur per SQL vergebbar — die
    Ansicht gäbe es, aber niemand käme dran."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from backend.api.users import PERMISSION_GROUPS
    from app.models.permission import Permission
    keys = {key for g in PERMISSION_GROUPS for key, _ in g['permissions']}
    assert Permission.SPIELSTAETTEN_BELEGUNG in keys


def test_migration_v117_v118_gibt_admins_das_neue_recht(db):
    """Fresh == Upgrade: Auf einer frisch aufgebauten DB steht der Key im Admin-Seed,
    auf einer gewachsenen muss die Migration ihn nachziehen. Sonst stünde bei
    Bestands-Admins in der Rechte-Matrix ein leerer Haken für etwas, das sie längst
    dürfen (role='admin' umgeht die Prüfung ohnehin)."""
    from app.models.permission import Permission
    neu = Permission.SPIELSTAETTEN_BELEGUNG

    def _halter(cur):
        cur.execute("SELECT user_id FROM user_permissions WHERE permission = %s "
                    "AND effect = 'grant' AND deleted_at IS NULL", (neu,))
        return {r["user_id"] for r in cur.fetchall()}

    with db.cursor() as cur:
        vorher = _halter(cur)
        cur.execute(
            "INSERT INTO users (username, email, password_hash, role, active, "
            "created_by, updated_by) VALUES (%s, %s, 'x', 'admin', 1, %s, %s) "
            "RETURNING id",
            (f"{MARKE}-admin", f"{MARKE}-admin@example.invalid", MARKE, MARKE))
        bestands_admin = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO users (username, email, password_hash, role, active, "
            "created_by, updated_by) VALUES (%s, %s, 'x', 'mitglied', 1, %s, %s) "
            "RETURNING id",
            (f"{MARKE}-user", f"{MARKE}-user@example.invalid", MARKE, MARKE))
        normal = cur.fetchone()["id"]
        cur.execute("DELETE FROM user_permissions WHERE user_id = %s AND permission = %s",
                    (bestands_admin, neu))

    try:
        db._database._migrate_v117_to_v118()
        with db.cursor() as cur:
            halter = _halter(cur)
            assert bestands_admin in halter, "Bestands-Admin ohne den neuen Key"
            assert normal not in halter, "Recht an jemanden ohne Anlass vergeben"
            cur.execute("SELECT version FROM schema_version WHERE id = 1")
            assert cur.fetchone()["version"] == 118

        db._database._migrate_v117_to_v118()      # idempotent
        with db.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM user_permissions "
                        "WHERE user_id = %s AND permission = %s", (bestands_admin, neu))
            assert cur.fetchone()["n"] == 1
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM user_permissions WHERE permission = %s "
                        "AND NOT (user_id = ANY(%s))", (neu, list(vorher)))
            cur.execute("DELETE FROM user_permissions_history WHERE permission = %s "
                        "AND NOT (user_id = ANY(%s))", (neu, list(vorher)))
            for tabelle in ("user_permissions_history", "user_permissions",
                            "users_history", "users"):
                cur.execute(f"DELETE FROM {tabelle} WHERE created_by = %s", (MARKE,))
