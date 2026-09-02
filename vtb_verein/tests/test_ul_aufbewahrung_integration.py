"""
Was mit Übungsleiter-Daten über die Zeit passiert – gegen echtes PostgreSQL (#188).

``ul_abrechnung``, ``ul_stunde`` und ``ul_satz`` standen zwar im PRUNE_REGISTRY, hatten
aber keine Uhr: Ohne ArchiveRule kommt eine aktive Zeile nie in den Papierkorb, und was
nie im Papierkorb liegt, wird auch nie geprunt. Tor 4 des Mitglieds (``NOT EXISTS`` OHNE
``deleted_at``-Filter, also physische Existenz) hing damit dauerhaft fest: Wer je eine
Abrechnung eingereicht hatte, blieb nach dem Austritt mit Namen, Geburtsdatum und
Adresse für immer im Papierkorb liegen.

Zwei verschiedene Regeln, weil es zwei verschiedene Datenarten sind – die Abrechnung
altert über ihren Zeitraum, der Vergütungssatz über das Ausscheiden seines Übungsleiters.
Beides wird hier gegen die echte Registry und das echte Schema geprüft, samt der Frage,
die den Ausschlag gab: Läuft die Kette am Ende wirklich bis zum Mitglied durch?

Läuft nur, wenn ``VTB_TEST_DATABASE_URL`` auf eine LEERE Wegwerf-DB zeigt
(VereinsDB legt das Schema beim Connect an). Beispiel:
    docker run -d --rm --name vtb-pg-ul -e POSTGRES_PASSWORD=test \\
        -e POSTGRES_DB=ultest -e TZ=Europe/Berlin -p 55438:5432 postgres:18
    VTB_TEST_DATABASE_URL=postgresql://postgres:test@localhost:55438/ultest \\
        ./venv/bin/python -m pytest vtb_verein/tests/test_ul_aufbewahrung_integration.py
"""
import os
import tempfile

import pytest

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

# Alt genug, dass die Zehn-Jahres-Frist in jedem Fall abgelaufen ist – unabhängig davon,
# wann der Test läuft. JUNG liegt bewusst innerhalb der Frist.
ALT = "2010"
JUNG = "2024"

UL_TABELLEN = ("ul_stunde", "ul_abrechnung", "ul_satz")


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    with tempfile.TemporaryDirectory(prefix="vtb-ul-uploads-") as pfad:
        d = VereinsDB(_URL, upload_path=pfad)
        yield d
        d.close()


@pytest.fixture
def svc(db):
    from app.services.prune_service import PruneService
    return PruneService(db)


def _leeren(db):
    with db.cursor() as cur:
        cur.execute("TRUNCATE mitglied, abteilung, ul_abrechnung, ul_stunde, ul_satz, "
                    "fibu_exporte CASCADE")
        for tabelle in ("mitglied", "ul_abrechnung", "ul_stunde", "ul_satz",
                        "fibu_exporte"):
            cur.execute(f"DELETE FROM {tabelle}_history")


@pytest.fixture(autouse=True)
def sauber(db):
    """Vor UND nach jedem Test alle ÜL- und Mitgliedsdaten weg.

    Vorher, weil die Tests echte Prune-Läufe loslassen und Reste sich sonst gegenseitig
    in die Zählungen rechnen. Nachher, weil ein Mitglied, das dieses Modul liegen lässt,
    beim nächsten Lauf im selben Wegwerf-Container die Mitglieder-Statistik anderer
    Module verfälscht (die zählen über den ganzen Bestand).
    """
    _leeren(db)
    yield
    _leeren(db)


@pytest.fixture
def ohne_mindestanzahl(db):
    """Tor 3 (``keep_min``) hält die zuletzt Gelöschten pauschal zurück und würde in
    Tests mit einer Handvoll Zeilen jedes andere Tor überdecken. Die übrigen Fristen
    bleiben auf ihren echten Werten."""
    for name in ("ul_stunde", "ul_abrechnung", "ul_satz", "mitglied"):
        db.prune_einstellungen.upsert(name, 90, 0, 365, updated_by="TEST")
    yield


# --- Anlegen -----------------------------------------------------------------------
def _abteilung(db, name="ÜL-Abteilung"):
    with db.cursor() as cur:
        cur.execute("INSERT INTO abteilung (name, created_by, updated_by) "
                    "VALUES (%s, 'TEST', 'TEST') RETURNING id", (name,))
        return cur.fetchone()["id"]


def _mitglied(db, austritt=None, nachname="Übungsleiter"):
    with db.cursor() as cur:
        cur.execute("INSERT INTO mitglied (vorname, nachname, zahlungsart, "
                    "austrittsdatum, created_by) "
                    "VALUES ('Uta', %s, 'lastschrift', %s, 'TEST') RETURNING id",
                    (nachname, austritt or ""))
        return cur.fetchone()["id"]


def _abrechnung(db, mitglied_id, abteilung_id, jahr):
    with db.cursor() as cur:
        cur.execute("INSERT INTO ul_abrechnung (mitglied_id, abteilung_id, "
                    "zeitraum_von, zeitraum_bis, status, created_by, updated_by) "
                    "VALUES (%s, %s, %s, %s, 'bestaetigt', 'TEST', 'TEST') RETURNING id",
                    (mitglied_id, abteilung_id, f"{jahr}-01-01", f"{jahr}-06-30"))
        aid = cur.fetchone()["id"]
        cur.execute("INSERT INTO ul_stunde (abrechnung_id, datum, stunden, "
                    "created_by, updated_by) "
                    "VALUES (%s, %s, 2.0, 'TEST', 'TEST') RETURNING id",
                    (aid, f"{jahr}-03-04"))
        return aid, cur.fetchone()["id"]


def _satz(db, mitglied_id, abteilung_id, satz=15.0):
    with db.cursor() as cur:
        cur.execute("INSERT INTO ul_satz (mitglied_id, abteilung_id, satz, "
                    "created_by, updated_by) "
                    "VALUES (%s, %s, %s, 'TEST', 'TEST') RETURNING id",
                    (mitglied_id, abteilung_id, satz))
        return cur.fetchone()["id"]


# --- Abfragen ----------------------------------------------------------------------
def _papierkorb(db, tabelle, zeilen_id):
    with db.cursor() as cur:
        cur.execute(f"SELECT deleted_at FROM {tabelle} WHERE id = %s", (zeilen_id,))
        zeile = cur.fetchone()
    assert zeile is not None, f"{tabelle}#{zeilen_id} existiert nicht (mehr)"
    return zeile["deleted_at"] is not None


def _existiert(db, tabelle, zeilen_id):
    with db.cursor() as cur:
        cur.execute(f"SELECT 1 FROM {tabelle} WHERE id = %s", (zeilen_id,))
        return cur.fetchone() is not None


def _altern(db, tage):
    """Lässt Zeit vergehen: Papierkorb- und History-Uhren zurückdatieren. Die History
    muss mit, sonst hielte Tor 5 die Zeilen fest."""
    with db.cursor() as cur:
        for tabelle in UL_TABELLEN + ("mitglied",):
            cur.execute(f"UPDATE {tabelle} SET deleted_at = deleted_at - "
                        f"make_interval(days => %s) WHERE deleted_at IS NOT NULL",
                        (tage,))
            cur.execute(f"UPDATE {tabelle}_history SET "
                        "created_at = created_at - make_interval(days => %s), "
                        "updated_at = updated_at - make_interval(days => %s), "
                        "deleted_at = deleted_at - make_interval(days => %s)",
                        (tage, tage, tage))


class TestAbrechnungAltert:

    def test_alte_abrechnung_wandert_mit_ihren_stunden(self, db, svc):
        """Der Kern der ersten Regel: Zehn Jahre nach dem abgerechneten Zeitraum geht
        die Abrechnung in den Papierkorb – und die Stunden gehen mit, sonst hielte Tor 4
        sie dort für immer fest."""
        abt = _abteilung(db)
        mit = _mitglied(db)
        alt, alte_stunde = _abrechnung(db, mit, abt, ALT)
        jung, junge_stunde = _abrechnung(db, mit, abt, JUNG)

        svc.prune(dry_run=False)

        assert _papierkorb(db, "ul_abrechnung", alt) is True
        assert _papierkorb(db, "ul_stunde", alte_stunde) is True
        assert _papierkorb(db, "ul_abrechnung", jung) is False
        assert _papierkorb(db, "ul_stunde", junge_stunde) is False

    def test_report_zeigt_die_faellige_abrechnung_vorher_an(self, db, svc):
        """Archivieren ist reversibel, zählt also zu ``summe_archivierbar`` und NICHT
        zu ``summe_loeschbar`` – der Admin sieht vor dem Auslösen, was passiert."""
        abt = _abteilung(db)
        mit = _mitglied(db)
        _abrechnung(db, mit, abt, ALT)

        zeile = {e["name"]: e
                 for e in svc.report()["entities"]}["ul_abrechnung_alter"]
        assert zeile["archivierbar"] == 1
        assert zeile["loeschbar"] == 0
        assert zeile["soft_delete"] is False

    def test_abrechnung_ohne_zeitraum_bleibt_liegen(self, db, svc):
        """`_ab_jahresende` liefert für ein leeres Datum NULL. Ohne das NULLIF darin
        ergäbe der Ausdruck den Text '-12-31', der vor jedem Stichtag liegt – eine
        undatierte Abrechnung würde sofort archiviert."""
        abt = _abteilung(db)
        mit = _mitglied(db)
        with db.cursor() as cur:
            cur.execute("INSERT INTO ul_abrechnung (mitglied_id, abteilung_id, "
                        "zeitraum_von, zeitraum_bis, created_by, updated_by) "
                        "VALUES (%s, %s, '', '', 'TEST', 'TEST') RETURNING id",
                        (mit, abt))
            ohne = cur.fetchone()["id"]

        svc.prune(dry_run=False)

        assert _papierkorb(db, "ul_abrechnung", ohne) is False


class TestSatzHaengtAmUebungsleiter:

    def test_satz_wandert_mit_dem_ausgeschiedenen_uebungsleiter(self, db, svc):
        """Die zweite Regel: Ein Vergütungssatz hat kein natürliches Enddatum, also
        keine Datumsregel – er stirbt mit dem Mitglied, dem er gehört."""
        abt = _abteilung(db)
        raus = _mitglied(db, austritt="2010-05-01", nachname="Ausgeschieden")
        bleibt = _mitglied(db, austritt="2024-05-01", nachname="Aktiv")
        alter_satz = _satz(db, raus, abt)
        junger_satz = _satz(db, bleibt, abt)

        svc.prune(dry_run=False)

        assert _papierkorb(db, "ul_satz", alter_satz) is True
        assert _papierkorb(db, "ul_satz", junger_satz) is False

    def test_allgemeiner_satz_der_abteilung_bleibt_unberuehrt(self, db, svc):
        """Sätze ohne ``mitglied_id`` gelten für die ganze Abteilung. Sie dürfen nicht
        mitgerissen werden, wenn irgendein Übungsleiter ausscheidet – sonst wäre die
        Abteilung nach dem Lauf ohne Vergütungsgrundlage."""
        abt = _abteilung(db)
        _mitglied(db, austritt="2010-05-01")
        with db.cursor() as cur:
            cur.execute("INSERT INTO ul_satz (abteilung_id, satz, created_by, "
                        "updated_by) VALUES (%s, 12.0, 'TEST', 'TEST') RETURNING id",
                        (abt,))
            allgemein = cur.fetchone()["id"]

        svc.prune(dry_run=False)

        assert _papierkorb(db, "ul_satz", allgemein) is False

    def test_satz_bekommt_keine_eigene_datumsregel(self, db, svc):
        """Gegenprobe zur Entscheidung: Ein Satz, dessen Übungsleiter noch da ist,
        altert NICHT – auch wenn er uralt ist. Eine Datumsregel würde ihn archivieren
        und damit jede künftige Abrechnung entwerten."""
        abt = _abteilung(db)
        mit = _mitglied(db)               # kein Austritt
        satz = _satz(db, mit, abt)
        with db.cursor() as cur:
            cur.execute("UPDATE ul_satz SET gueltig_ab = '2009-01-01', "
                        "created_at = now() - make_interval(days => 6000) "
                        "WHERE id = %s", (satz,))

        svc.prune(dry_run=False)

        assert _papierkorb(db, "ul_satz", satz) is False


class TestKetteLaeuftBisZumMitgliedDurch:
    """Der eigentliche Zweck von #188 – geprüft wird nicht die Regel, sondern ihr
    Ergebnis: dass ein ausgeschiedener Übungsleiter das System am Ende verlässt."""

    def test_uebungsleiter_wird_endgueltig_geloescht(self, db, svc, ohne_mindestanzahl):
        abt = _abteilung(db)
        mit = _mitglied(db, austritt="2010-05-01")
        abrechnung, stunde = _abrechnung(db, mit, abt, ALT)
        satz = _satz(db, mit, abt)

        svc.prune(dry_run=False)          # 1) Archivieren: alles in den Papierkorb
        assert all(_papierkorb(db, t, i) for t, i in (
            ("mitglied", mit), ("ul_abrechnung", abrechnung),
            ("ul_stunde", stunde), ("ul_satz", satz)))

        _altern(db, 400)                  # Tor 2 und Tor 5 laufen ab

        # „Vorschau = Aktion": Kandidaten werden VOR dem Löschen eingesammelt, ein in
        # diesem Lauf kinderlos gewordener Elternteil fällt erst im nächsten. Deshalb
        # braucht die dreistufige Kette Stunde → Abrechnung → Mitglied drei Läufe.
        svc.prune(dry_run=False)
        assert not _existiert(db, "ul_stunde", stunde)
        assert not _existiert(db, "ul_satz", satz)
        assert _existiert(db, "ul_abrechnung", abrechnung), "Tor 4: Stunde lag noch da"

        svc.prune(dry_run=False)
        assert not _existiert(db, "ul_abrechnung", abrechnung)
        assert _existiert(db, "mitglied", mit), "Tor 4: Abrechnung lag noch da"

        svc.prune(dry_run=False)
        assert not _existiert(db, "mitglied", mit)

    def test_ohne_abrechnung_haengt_das_mitglied_nicht_fest(self, db, svc,
                                                            ohne_mindestanzahl):
        """Gegenprobe: Ein ausgeschiedenes Mitglied ohne ÜL-Vergangenheit war auch
        vorher schon löschbar – der Test oben misst also wirklich die ÜL-Kette."""
        _abteilung(db)
        mit = _mitglied(db, austritt="2010-05-01")

        svc.prune(dry_run=False)
        _altern(db, 400)
        svc.prune(dry_run=False)

        assert not _existiert(db, "mitglied", mit)


class TestExportBleibtBisZurAbrechnung:
    """Die beiden Export-Spalten der Abrechnung sind – anders als bei den Forderungen –
    ohne FK angelegt. Die DB stoppt hier also nichts; ohne Guard verschwindet der Export
    vor der Abrechnung und lässt in ihr eine Export-Nummer zurück, die auf nichts mehr
    zeigt (und die Frage „wurde das je exportiert?" unbeantwortbar macht)."""

    def _export(self, db):
        with db.cursor() as cur:
            cur.execute("INSERT INTO fibu_exporte (exportiert_am, exportiert_von, "
                        "dateiname, created_by, deleted_at, deleted_by) "
                        "VALUES ('2010-07-15', 'TEST', 'fbasc.hia', 'TEST', "
                        "now() - make_interval(days => 400), 'TEST') RETURNING id")
            eid = cur.fetchone()["id"]
            cur.execute("UPDATE fibu_exporte_history SET "
                        "created_at = created_at - make_interval(days => 400) "
                        "WHERE id = %s", (eid,))
        return eid

    def _loeschbar(self, db, export_id):
        from dataclasses import replace
        from app.services.prune_service import (
            PRUNE_REGISTRY, PruneService, build_original_candidate_ids_sql,
        )
        entity = replace(next(e for e in PRUNE_REGISTRY if e.name == "fibu_export"),
                         keep_min=0)
        # Die Zeitspalten der History kommen aus dem Schema, nicht aus der Registry –
        # `fibu_exporte_history` führt kein `updated_at`.
        ts_cols = PruneService(db)._history_ts_cols(entity)
        sql, params = build_original_candidate_ids_sql(entity, 90, 0, 365, ts_cols)
        with db.cursor() as cur:
            cur.execute(sql, tuple(params))
            return export_id in {r["id"] for r in cur.fetchall()}

    def test_export_wartet_auf_die_abrechnung(self, db):
        abt = _abteilung(db)
        mit = _mitglied(db)
        abrechnung, _ = _abrechnung(db, mit, abt, ALT)
        eid = self._export(db)
        with db.cursor() as cur:
            cur.execute("UPDATE ul_abrechnung SET exportiert_in_export_id = %s "
                        "WHERE id = %s", (eid, abrechnung))

        assert self._loeschbar(db, eid) is False, "Tor 4: Abrechnung zeigt noch darauf"

        with db.cursor() as cur:      # einen Lauf später ist die Abrechnung weg
            cur.execute("DELETE FROM ul_stunde WHERE abrechnung_id = %s", (abrechnung,))
            cur.execute("DELETE FROM ul_abrechnung WHERE id = %s", (abrechnung,))
        assert self._loeschbar(db, eid) is True

    def test_auch_der_storno_verweis_haelt_fest(self, db):
        """Ein stornierter Export wird über die zweite Spalte vermerkt – auch sie ist
        eine Referenz, die nicht ins Leere zeigen darf."""
        abt = _abteilung(db)
        mit = _mitglied(db)
        abrechnung, _ = _abrechnung(db, mit, abt, ALT)
        eid = self._export(db)
        with db.cursor() as cur:
            cur.execute("UPDATE ul_abrechnung SET storno_exportiert_in_export_id = %s "
                        "WHERE id = %s", (eid, abrechnung))

        assert self._loeschbar(db, eid) is False
