"""
Integrationstests der Prune-Gates gegen echtes PostgreSQL.

Sensibler Bereich (endgültiges Löschen) – hier wird die SQL-Semantik der 5 Tore gegen
das reale Schema und die echten Spaltentypen (TEXT/TIMESTAMP) verifiziert, nicht nur die
String-Konstruktion (das macht test_prune_service.py).

Läuft nur, wenn ``VTB_TEST_DATABASE_URL`` auf eine LEERE Wegwerf-DB zeigt
(z.B. ein ephemerer Postgres-Container). VereinsDB legt das Schema beim Connect an.
Beispiel:
    docker run -d --name vtb-pg-prunetest -e POSTGRES_USER=test -e POSTGRES_PASSWORD=test \\
        -e POSTGRES_DB=prunetest -p 55432:5432 postgres:18
    VTB_TEST_DATABASE_URL=postgresql://test:test@localhost:55432/prunetest \\
        ./venv/bin/python -m pytest vtb_verein/tests/test_prune_integration.py
"""
import os
import pytest

from app.services.prune_service import (
    PruneEntity, ChildRef,
    build_original_candidate_count_sql, build_history_prune_count_sql,
    build_papierkorb_count_sql,
)

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-prune-uploads")
    yield d
    d.close()


def _leeren(db):
    """Alle Tabellen dieses Moduls leeren – OHNE die Sequenzen zurückzusetzen.

    Das fehlende ``RESTART IDENTITY`` ist der Kern: ``CASCADE`` greift viel weiter als
    die hier aufgezählten Tabellen (über ``abteilung`` bis ``beitragsregel``, ``gebuehr``,
    ``kassen``), und deren FK-freie ``*_history`` bleibt dabei stehen. Wurden die
    Sequenzen zurückgesetzt, vergab der nächste INSERT eine schon benutzte id und der
    Audit-Trigger lief auf ein vorhandenes ``(id, version)`` – quer durch fremde Module,
    die von diesem Modul gar nichts wissen. Laufende Sequenzen kosten nichts (die DB ist
    ein Wegwerf-Container) und machen das Problem strukturell unmöglich.
    """
    with db.cursor() as cur:
        cur.execute(
            "TRUNCATE mitglied, mannschaft, mitglied_kontakt, mitglied_abteilung, "
            "mitglied_funktion, mitglied_mannschaft, beitrag_sollstellung, "
            "gebuehr_forderung, users, tickets, ticket_anhaenge, abteilung CASCADE"
        )
        # History-Tabellen werden NICHT per CASCADE erfasst (FK-frei) – explizit leeren,
        # damit die Zählungen im Report nur die Zeilen dieses Tests sehen.
        cur.execute(
            "TRUNCATE mitglied_history, mitglied_kontakt_history, mitglied_abteilung_history, "
            "users_history, tickets_history, abteilung_history, schluessel_chip_history, "
            "beitrag_sollstellung_history, gebuehr_forderung_history"
        )
        cur.execute("TRUNCATE prune_einstellungen, prune_einstellungen_history")


@pytest.fixture(autouse=True)
def clean(db):
    # Vor UND nach dem Test aufräumen: Nur davor zu putzen lässt die Zeilen des letzten
    # Tests im geteilten Wegwerf-Postgres stehen, wo vereinsweite Auswertungen anderer
    # Module sie mitzählen (test_gastspieler_integration fiel genau darüber, sobald die
    # Suite ein zweites Mal gegen dieselbe DB lief).
    _leeren(db)
    yield
    _leeren(db)


# --- DB-Helfer -------------------------------------------------------------------
def _ins_mitglied(db):
    with db.cursor() as cur:
        cur.execute("INSERT INTO mitglied (vorname,nachname,zahlungsart) "
                    "VALUES ('A','B','lastschrift') RETURNING id")
        return cur.fetchone()["id"]


def _ins_kontakt(db, mid):
    with db.cursor() as cur:
        cur.execute("INSERT INTO mitglied_kontakt (mitglied_id,typ,wert) "
                    "VALUES (%s,'email','x@y.z') RETURNING id", (mid,))
        return cur.fetchone()["id"]


def _soft_delete(db, table, id_, days_ago):
    """Soft-Delete wie in der App: deleted_at setzen UND version bumpen.

    Der version-Bump ist entscheidend – der History-Trigger schreibt bei UPDATE nur
    dann eine Zeile, wenn NEW.version != OLD.version (PK (id, version))."""
    with db.cursor() as cur:
        cur.execute(
            f"UPDATE {table} SET deleted_at=(now()-make_interval(days=>%s)), "
            f"deleted_by='t', version=version+1 WHERE id=%s", (days_ago, id_)
        )


def _soft_delete_plain(db, table, id_, days_ago):
    """Soft-Delete für Tabellen OHNE version/History (z.B. Anhänge): nur deleted_at."""
    with db.cursor() as cur:
        cur.execute(
            f"UPDATE {table} SET deleted_at=(now()-make_interval(days=>%s)), "
            f"deleted_by='t' WHERE id=%s", (days_ago, id_)
        )


def _age_history(db, htable, id_, days_ago):
    """Simuliert vollständig abgeflossene History: alle Zeitstempel zurückdatieren."""
    with db.cursor() as cur:
        cur.execute(
            f"UPDATE {htable} SET created_at=(now()-make_interval(days=>%s)), "
            f"updated_at=(now()-make_interval(days=>%s)) WHERE id=%s",
            (days_ago, days_ago, id_)
        )
        cur.execute(
            f"UPDATE {htable} SET deleted_at=(now()-make_interval(days=>%s)) "
            f"WHERE id=%s AND deleted_at IS NOT NULL", (days_ago, id_)
        )


def _count(db, sql, params):
    with db.cursor() as cur:
        cur.execute(sql, tuple(params))
        return cur.fetchone()["n"]


def _candidates(db, entity, hist_ret):
    sql, params = build_original_candidate_count_sql(
        entity, entity.retention_days, entity.keep_min, hist_ret
    )
    return _count(db, sql, params)


_KONTAKT = PruneEntity("mitglied_kontakt", "K", "mitglied_kontakt",
                       history_table="mitglied_kontakt_history",
                       retention_days=30, keep_min=0)


def test_history_trigger_schreibt_bei_version_bump(db):
    """Vorbedingung: Soft-Delete (mit version-Bump) erzeugt eine History-Snapshot-Zeile."""
    m = _ins_mitglied(db)
    k = _ins_kontakt(db, m)
    assert _count(db, "SELECT COUNT(*) n FROM mitglied_kontakt_history WHERE id=%s", [k]) == 1
    _soft_delete(db, "mitglied_kontakt", k, 60)
    assert _count(db, "SELECT COUNT(*) n FROM mitglied_kontakt_history WHERE id=%s", [k]) == 2


def test_tor_datum_und_history(db):
    """Nur ein alter, history-freier Datensatz ist Kandidat; junge/history-behaftete nicht."""
    m = _ins_mitglied(db)
    k_recent = _ins_kontakt(db, m); _soft_delete(db, "mitglied_kontakt", k_recent, 5)   # zu jung
    k_fresh = _ins_kontakt(db, m); _soft_delete(db, "mitglied_kontakt", k_fresh, 60)    # frische History
    k_drained = _ins_kontakt(db, m); _soft_delete(db, "mitglied_kontakt", k_drained, 60)
    _age_history(db, "mitglied_kontakt_history", k_drained, 60)                          # History abgeflossen
    _ins_kontakt(db, m)                                                                  # aktiv
    assert _candidates(db, _KONTAKT, 10) == 1


def test_tor_children(db):
    """Eltern nur löschbar, wenn KEINE Kind-Zeile mehr existiert (aktiv ODER soft-deleted)."""
    mitglied = PruneEntity(
        "mitglied", "M", "mitglied", history_table="mitglied_history",
        children=(ChildRef("mitglied_kontakt", "mitglied_id"),),
        retention_days=30, keep_min=0,
    )
    m1 = _ins_mitglied(db); _soft_delete(db, "mitglied", m1, 60)
    _age_history(db, "mitglied_history", m1, 60)                                  # kinderlos -> Kandidat
    m2 = _ins_mitglied(db); _ins_kontakt(db, m2); _soft_delete(db, "mitglied", m2, 60)
    _age_history(db, "mitglied_history", m2, 60)                                  # aktives Kind -> blockiert
    m3 = _ins_mitglied(db); k3 = _ins_kontakt(db, m3)
    _soft_delete(db, "mitglied_kontakt", k3, 99); _soft_delete(db, "mitglied", m3, 60)
    _age_history(db, "mitglied_history", m3, 60)                                  # soft-del Kind existiert noch
    assert _candidates(db, mitglied, 10) == 1


def test_tor_mindestanzahl_keep_min(db):
    """Die keep_min zuletzt gelöschten bleiben immer erhalten."""
    keep2 = PruneEntity("mitglied_kontakt", "K", "mitglied_kontakt",
                        history_table="mitglied_kontakt_history",
                        retention_days=30, keep_min=2)
    m = _ins_mitglied(db)
    for d in (60, 61, 62, 63, 64):
        k = _ins_kontakt(db, m); _soft_delete(db, "mitglied_kontakt", k, d)
        _age_history(db, "mitglied_kontakt_history", k, d)
    assert _candidates(db, keep2, 10) == 3   # 5 - keep_min(2)


def test_history_prune_zaehler_datums_only(db):
    """History-Prune entfernt alle abgeflossenen Zeilen; frisches Fenster schützt alles."""
    m = _ins_mitglied(db); k = _ins_kontakt(db, m)
    _soft_delete(db, "mitglied_kontakt", k, 60)
    _age_history(db, "mitglied_kontakt_history", k, 60)
    total = _count(db, "SELECT COUNT(*) n FROM mitglied_kontakt_history WHERE id=%s", [k])
    h_sql, h_params = build_history_prune_count_sql(_KONTAKT)
    assert _count(db, h_sql, h_params + [10]) == total       # alle abgeflossen
    assert _count(db, h_sql, h_params + [10000]) == 0        # frisches Fenster -> nichts


def test_einstellungen_override_roundtrip(db):
    """Override überschreibt Default, report() spiegelt ihn, delete fällt auf Default zurück."""
    from app.services.prune_service import PruneService
    svc = PruneService(db)

    default = {e["name"]: e for e in svc.einstellungen()}["mitglied"]
    assert default["is_override"] is False

    db.prune_einstellungen.upsert("mitglied", 30, 3, 100, updated_by="tester")
    over = {e["name"]: e for e in svc.einstellungen()}["mitglied"]
    assert (over["retention_days"], over["keep_min"], over["history_retention_days"]) == (30, 3, 100)
    assert over["is_override"] is True

    rep = {e["name"]: e for e in svc.report()["entities"]}["mitglied"]
    assert rep["retention_days"] == 30 and rep["history_retention_days"] == 100 and rep["is_override"] is True

    assert db.prune_einstellungen.delete("mitglied", deleted_by="tester") is True
    reset = {e["name"]: e for e in svc.einstellungen()}["mitglied"]
    assert reset["is_override"] is False
    assert reset["retention_days"] == default["retention_days"]


def test_history_gesamt_im_report(db):
    """report() zählt alle aktuell vorhandenen History-Zeilen je Bereich."""
    from app.services.prune_service import PruneService
    m = _ins_mitglied(db)
    for _ in range(3):
        _ins_kontakt(db, m)   # je INSERT eine History-Zeile
    rep = {e["name"]: e for e in PruneService(db).report()["entities"]}
    assert rep["mitglied_kontakt"]["history_gesamt"] == 3


def _row_exists(db, table, id_):
    with db.cursor() as cur:
        cur.execute(f"SELECT 1 FROM {table} WHERE id=%s", (id_,))
        return cur.fetchone() is not None


def _live_count(db, table):
    with db.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) n FROM {table}")
        return cur.fetchone()["n"]


def test_prune_loescht_genau_die_kandidaten(db):
    """prune() entfernt exakt die Kandidaten des Reports – nicht mehr, nicht weniger."""
    from app.services.prune_service import PruneService
    db.prune_einstellungen.upsert("mitglied_kontakt", 30, 0, 10, updated_by="t")
    svc = PruneService(db)
    m = _ins_mitglied(db)
    k_recent = _ins_kontakt(db, m); _soft_delete(db, "mitglied_kontakt", k_recent, 5)
    k_fresh = _ins_kontakt(db, m); _soft_delete(db, "mitglied_kontakt", k_fresh, 60)
    k_drained = _ins_kontakt(db, m); _soft_delete(db, "mitglied_kontakt", k_drained, 60)
    _age_history(db, "mitglied_kontakt_history", k_drained, 60)
    k_active = _ins_kontakt(db, m)

    rep = {e["name"]: e for e in svc.report()["entities"]}["mitglied_kontakt"]
    assert rep["loeschbar"] == 1

    res = {e["name"]: e for e in svc.prune(dry_run=False)["entities"]}["mitglied_kontakt"]
    assert res["geloescht"] == 1

    assert not _row_exists(db, "mitglied_kontakt", k_drained)
    for k in (k_recent, k_fresh, k_active):
        assert _row_exists(db, "mitglied_kontakt", k)


def test_prune_dry_run_loescht_nichts(db):
    from app.services.prune_service import PruneService
    db.prune_einstellungen.upsert("mitglied_kontakt", 30, 0, 10, updated_by="t")
    svc = PruneService(db)
    m = _ins_mitglied(db)
    k = _ins_kontakt(db, m); _soft_delete(db, "mitglied_kontakt", k, 60)
    _age_history(db, "mitglied_kontakt_history", k, 60)

    out = svc.prune(dry_run=True)
    assert out["dry_run"] is True
    assert _row_exists(db, "mitglied_kontakt", k)   # nichts gelöscht


def test_prune_idempotent(db):
    from app.services.prune_service import PruneService
    db.prune_einstellungen.upsert("mitglied_kontakt", 30, 0, 10, updated_by="t")
    svc = PruneService(db)
    m = _ins_mitglied(db)
    k = _ins_kontakt(db, m); _soft_delete(db, "mitglied_kontakt", k, 60)
    _age_history(db, "mitglied_kontakt_history", k, 60)

    assert svc.prune(dry_run=False)["summe_geloescht"] == 1
    assert svc.prune(dry_run=False)["summe_geloescht"] == 0   # zweiter Lauf: nichts mehr


def test_prune_kein_cascade_in_einem_lauf(db):
    """Vorschau = Aktion: ein erst durch Blatt-Löschung kinderloses Elternteil bleibt
    diesen Lauf stehen und wird erst im nächsten entfernt."""
    from app.services.prune_service import PruneService
    db.prune_einstellungen.upsert("mitglied_kontakt", 30, 0, 10, updated_by="t")
    db.prune_einstellungen.upsert("mitglied", 30, 0, 10, updated_by="t")
    svc = PruneService(db)
    m = _ins_mitglied(db)
    k = _ins_kontakt(db, m)
    _soft_delete(db, "mitglied_kontakt", k, 60); _age_history(db, "mitglied_kontakt_history", k, 60)
    _soft_delete(db, "mitglied", m, 60); _age_history(db, "mitglied_history", m, 60)

    # Snapshot vor Lauf: mitglied ist durch das (noch existierende) Kind blockiert
    rep = {e["name"]: e for e in svc.report()["entities"]}
    assert rep["mitglied_kontakt"]["loeschbar"] == 1
    assert rep["mitglied"]["loeschbar"] == 0

    svc.prune(dry_run=False)
    assert not _row_exists(db, "mitglied_kontakt", k)   # Blatt weg
    assert _row_exists(db, "mitglied", m)               # Elternteil bleibt

    svc.prune(dry_run=False)                              # zweiter Lauf
    assert not _row_exists(db, "mitglied", m)            # jetzt kinderlos -> entfernt


def test_prune_loescht_anhang_datensatz_und_datei(db):
    """Phase 4: ein geprunter Anhang verschwindet aus DB UND von der Platte."""
    from app.services.prune_service import PruneService
    db.prune_einstellungen.upsert("ticket_anhang", 30, 0, 365, updated_by="t")
    svc = PruneService(db)

    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO users (username,email,password_hash,role,created_by,updated_by) "
            "VALUES ('u1','u1@x.de','h','admin','t','t') RETURNING id"
        )
        uid = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO tickets (titel,beschreibung,gemeldet_von,created_by,updated_by) "
            "VALUES ('T','B',%s,'t','t') RETURNING id", (uid,)
        )
        tid = cur.fetchone()["id"]

    stored = "att_prunetest_1.bin"
    db.anhang_service.schreibe(stored, b"inhalt")
    assert db.anhang_service.existiert(stored)

    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO ticket_anhaenge "
            "(ticket_id,original_name,stored_name,mime_type,dateigroesse,hochgeladen_von) "
            "VALUES (%s,'x.bin',%s,'application/octet-stream',6,%s) RETURNING id",
            (tid, stored, uid),
        )
        aid = cur.fetchone()["id"]
    _soft_delete_plain(db, "ticket_anhaenge", aid, 60)

    assert {e["name"]: e for e in svc.report()["entities"]}["ticket_anhang"]["loeschbar"] == 1

    res = {e["name"]: e for e in svc.prune(dry_run=False)["entities"]}["ticket_anhang"]
    assert res["geloescht"] == 1
    assert res["dateien_geloescht"] == 1

    assert not _row_exists(db, "ticket_anhaenge", aid)   # DB-Zeile weg
    assert not db.anhang_service.existiert(stored)        # Datei von Platte weg


def _ins_abteilung(db, name="Abt"):
    with db.cursor() as cur:
        cur.execute("INSERT INTO abteilung (name) VALUES (%s) RETURNING id", (name,))
        return cur.fetchone()["id"]


def test_prune_abteilung_timestamp_und_child_gate(db):
    """Stammdaten: abteilung hat TIMESTAMP-deleted_at + komplexe Child-Map.

    Prüft den ganzen Pfad: durch ein Kind (mitglied_abteilung) blockiert, nach dessen
    Entfernung löschbar – und dass das TIMESTAMP-deleted_at korrekt verarbeitet wird."""
    from app.services.prune_service import PruneService
    db.prune_einstellungen.upsert("abteilung", 30, 0, 10, updated_by="t")
    svc = PruneService(db)

    a = _ins_abteilung(db)
    m = _ins_mitglied(db)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO mitglied_abteilung (mitglied_id, abteilung_id) VALUES (%s,%s) RETURNING id",
            (m, a),
        )
        ma_id = cur.fetchone()["id"]
    _soft_delete(db, "abteilung", a, 60)                 # version-Bump -> abteilung_history
    _age_history(db, "abteilung_history", a, 60)

    # Durch das (noch existierende) mitglied_abteilung-Kind blockiert
    assert {e["name"]: e for e in svc.report()["entities"]}["abteilung"]["loeschbar"] == 0
    svc.prune(dry_run=False)
    assert _row_exists(db, "abteilung", a)

    # Kind entfernen -> abteilung wird löschbar
    with db.cursor() as cur:
        cur.execute("DELETE FROM mitglied_abteilung WHERE id=%s", (ma_id,))
    assert {e["name"]: e for e in svc.report()["entities"]}["abteilung"]["loeschbar"] == 1
    res = {e["name"]: e for e in svc.prune(dry_run=False)["entities"]}["abteilung"]
    assert res["geloescht"] == 1
    assert not _row_exists(db, "abteilung", a)


def test_protokoll_seitenaufrufe_retention(db):
    """Sonder-Bereich: nur alte category='page' werden gelöscht; auth/page-frisch bleiben."""
    from app.services.prune_service import PruneService, ACCESS_LOG_PAGE
    db.prune_einstellungen.upsert(ACCESS_LOG_PAGE, 30, 0, 1, updated_by="t")  # retention 30 Tage
    svc = PruneService(db)
    with db.cursor() as cur:
        cur.execute("INSERT INTO access_log (event_type,category,created_at) "
                    "VALUES ('page_view','page', now()-make_interval(days=>60))")  # alt -> weg
        cur.execute("INSERT INTO access_log (event_type,category,created_at) "
                    "VALUES ('page_view','page', now()-make_interval(days=>5))")   # frisch -> bleibt
        cur.execute("INSERT INTO access_log (event_type,category,created_at) "
                    "VALUES ('login_success','auth', now()-make_interval(days=>60))")  # auth -> bleibt

    rep = {e["name"]: e for e in svc.report()["entities"]}[ACCESS_LOG_PAGE]
    assert rep["loeschbar"] == 1 and rep["soft_delete"] is False

    res = {e["name"]: e for e in svc.prune(dry_run=False)["entities"]}[ACCESS_LOG_PAGE]
    assert res["geloescht"] == 1
    with db.cursor() as cur:
        cur.execute("SELECT count(*) n FROM access_log")
        assert cur.fetchone()["n"] == 2     # frischer Seitenaufruf + Auth-Event bleiben


def test_alters_archivierung_vergangene_termine(db):
    """ArchiveRule: aktive Termine älter als das Fenster werden (samt aktiver Zusagen) in
    den Papierkorb verschoben; künftige Termine bleiben aktiv. Reversibel (soft-delete),
    daher NICHT in summe_loeschbar, sondern in summe_archivierbar. Idempotent."""
    from app.services.prune_service import PruneService, TERMIN_ALTER
    with db.cursor() as cur:
        cur.execute(
            "TRUNCATE termine, termine_history, termin_zusage, termin_zusage_history, "
            "mannschaft, mannschaft_history CASCADE"
        )
    db.prune_einstellungen.upsert(TERMIN_ALTER, 30, 0, 1, updated_by="t")  # Alter: 30 Tage
    with db.cursor() as cur:
        cur.execute("INSERT INTO abteilung (name,created_by,updated_by) "
                    "VALUES ('Arch-Abt','t','t') RETURNING id")
        aid = cur.fetchone()["id"]
        cur.execute("INSERT INTO mannschaft (abteilung_id,name,saison,created_by,updated_by) "
                    "VALUES (%s,'M','2020/21','t','t') RETURNING id", (aid,))
        mid = cur.fetchone()["id"]
        # alter Termin (vor 90 Tagen) + Zusage, künftiger Termin (in 7 Tagen)
        cur.execute("SELECT id FROM spielstaette WHERE platzhalter='auswaerts'")
        platz = cur.fetchone()["id"]      # Spielstätte ist seit v80 Pflicht
        cur.execute("INSERT INTO termine (mannschaft_id,typ,beginn,spielstaette_id,"
                    "created_by,updated_by) "
                    "VALUES (%s,'training',"
                    "(now()-make_interval(days=>90))::date::text||'T19:00',%s,'t','t') RETURNING id",
                    (mid, platz))
        alt = cur.fetchone()["id"]
        cur.execute("INSERT INTO termine (mannschaft_id,typ,beginn,spielstaette_id,"
                    "created_by,updated_by) "
                    "VALUES (%s,'training',"
                    "(now()+make_interval(days=>7))::date::text||'T19:00',%s,'t','t') RETURNING id",
                    (mid, platz))
        neu = cur.fetchone()["id"]
        cur.execute("INSERT INTO mitglied (vorname,nachname,zahlungsart) "
                    "VALUES ('A','B','lastschrift') RETURNING id")
        pid = cur.fetchone()["id"]
        cur.execute("INSERT INTO termin_zusage (termin_id,mitglied_id,antwort,created_by,updated_by) "
                    "VALUES (%s,%s,'zu','t','t')", (alt, pid))

    svc = PruneService(db)
    report = svc.report()
    rep = {e["name"]: e for e in report["entities"]}[TERMIN_ALTER]
    assert rep["archivierbar"] == 1 and rep["loeschbar"] == 0 and rep["soft_delete"] is False
    assert report["summe_archivierbar"] == 1

    res = svc.prune(dry_run=False)
    assert res["summe_archiviert"] == 1
    assert {e["name"]: e for e in res["entities"]}[TERMIN_ALTER]["archiviert"] == 1
    with db.cursor() as cur:
        cur.execute("SELECT deleted_at IS NOT NULL AS d FROM termine WHERE id=%s", (alt,))
        assert cur.fetchone()["d"] is True                       # alter Termin archiviert
        cur.execute("SELECT deleted_at IS NOT NULL AS d FROM termine WHERE id=%s", (neu,))
        assert cur.fetchone()["d"] is False                      # künftiger bleibt aktiv
        cur.execute("SELECT deleted_at IS NOT NULL AS d FROM termin_zusage WHERE termin_id=%s", (alt,))
        assert cur.fetchone()["d"] is True                       # Zusage mit-archiviert
        cur.execute("SELECT count(*) n FROM termine_history WHERE id=%s", (alt,))
        assert cur.fetchone()["n"] >= 1                          # version-Bump -> Audit-History

    # zweiter Lauf: nichts mehr fällig (idempotent)
    assert svc.prune(dry_run=False)["summe_archiviert"] == 0


def test_papierkorb_zaehler(db):
    """Papierkorb zählt nur soft-deleted, nicht aktive Datensätze."""
    m = _ins_mitglied(db)
    for d in (1, 60):
        k = _ins_kontakt(db, m); _soft_delete(db, "mitglied_kontakt", k, d)
    _ins_kontakt(db, m)   # aktiv
    pk_sql, pk_params = build_papierkorb_count_sql(_KONTAKT)
    assert _count(db, pk_sql, pk_params) == 2


def test_registry_deckt_alle_eingehenden_fks_ab(db):
    """Schema-Drift-Wächter (Ticket #75): JEDE Live-FK, die auf eine geprunte Tabelle zeigt,
    MUSS als ChildRef in der Registry stehen.

    Fehlt eine, zählt der Report das Elternteil als löschbar, aber das echte DELETE läuft in
    den FK-RESTRICT und rollt den ganzen Lauf zurück. Genau so entstand die Lücke, als
    Schließanlage/Übungsleiter neue FKs auf mitglied/abteilung mitbrachten. Neue Domäne mit
    FK auf eine geprunte Tabelle ohne Registry-Pflege ⇒ dieser Test wird rot.
    """
    from app.services.prune_service import PRUNE_REGISTRY
    pruned_tables = {e.table for e in PRUNE_REGISTRY}
    refs_by_parent = {e.table: {(c.table, c.fk) for c in e.children} for e in PRUNE_REGISTRY}

    with db.cursor() as cur:
        cur.execute(
            "SELECT tc.table_name AS child_table, kcu.column_name AS child_col, "
            "       ccu.table_name AS parent_table "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema "
            "JOIN information_schema.constraint_column_usage ccu "
            "  ON tc.constraint_name = ccu.constraint_name AND tc.table_schema = ccu.table_schema "
            "WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public'"
        )
        fks = cur.fetchall()

    fehlend = [
        (r["parent_table"], r["child_table"], r["child_col"])
        for r in fks
        if r["parent_table"] in pruned_tables
        and (r["child_table"], r["child_col"]) not in refs_by_parent[r["parent_table"]]
    ]
    assert not fehlend, (
        "FK auf geprunte Tabelle ohne ChildRef – Prune-DELETE würde am RESTRICT scheitern: "
        + ", ".join(f"{c}.{col} -> {p}" for p, c, col in fehlend)
    )


def test_jede_tabelle_hat_einen_loeschpfad(db):
    """Inventur-Wächter: JEDE Tabelle muss in einer der Registries auftauchen.

    Der Befund vom 11.08.2026 war nicht, dass einzelne Fristen falsch gesetzt waren –
    sondern dass ganze Tabellen (Zutrittsprotokolle, Rechte-Zuweisungen, Sessions) nie
    zur Entscheidung vorgelegt worden waren und einfach immer weiter wuchsen. Dieser Test
    macht das Vergessen unmöglich: eine neue Tabelle ohne Löschpfad färbt ihn rot, und wer
    sie bewusst dauerhaft halten will, muss das hier unten mit Begründung hinschreiben.
    """
    from app.services.prune_service import (
        ARCHIVE_REGISTRY, LOG_REGISTRY, PRUNE_REGISTRY,
    )

    # Bewusst ohne Löschpfad – jede Zeile braucht eine Begründung.
    OHNE_PFAD = {
        "schema_version":  "eine Zeile, IST der Schema-Stand",
        "beitrag_einstellungen": "Singleton-Konfiguration, eine Zeile",
        "fibu_einstellungen":    "Singleton-Konfiguration, eine Zeile",
        "prune_einstellungen":   "Konfiguration dieses Dienstes, wächst nur mit Overrides",
        "ttlock_konto":          "Zugangsdaten der Schließanlage, eine Zeile",
        "schliessanlage_einstellungen": "Singleton-Konfiguration, eine Zeile",
        "tuer_credential":       "Spiegel des TTLock-Cloud-Zustands, wird dort hart ersetzt",
        "dfbnet_import_stand":   "Stand des letzten Spielplan-Imports, eine überschriebene Zeile",
    }

    with db.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
        )
        alle = {r["table_name"] for r in cur.fetchall()}

    abgedeckt = {e.table for e in PRUNE_REGISTRY}
    abgedeckt |= {e.history_table for e in PRUNE_REGISTRY if e.history_table}
    abgedeckt |= {r.table for r in ARCHIVE_REGISTRY}
    abgedeckt |= {r.table for r in LOG_REGISTRY}

    ohne = sorted(alle - abgedeckt - set(OHNE_PFAD))
    assert not ohne, (
        "Tabellen ohne Löschpfad – bitte entscheiden: entweder in PRUNE_REGISTRY / "
        "ARCHIVE_REGISTRY / LOG_REGISTRY aufnehmen, oder mit Begründung in OHNE_PFAD "
        "eintragen: " + ", ".join(ohne)
    )

    # Andersherum: eine Ausnahme, die es gar nicht mehr gibt, ist ein Karteileichen-Alibi.
    verwaiste_ausnahmen = sorted(set(OHNE_PFAD) - alle)
    assert not verwaiste_ausnahmen, (
        "OHNE_PFAD nennt Tabellen, die es nicht (mehr) gibt: "
        + ", ".join(verwaiste_ausnahmen)
    )


def test_mitglied_durch_schluessel_chip_blockiert(db):
    """Regression Befund #75: ein soft-gelöschtes Mitglied mit Chip ist NICHT prunebar.

    Ohne den schluessel_chip-Guard hätte der Report es als löschbar gezählt und das echte
    DELETE wäre am FK-RESTRICT gescheitert (und hätte den ganzen Lauf zurückgerollt)."""
    from app.services.prune_service import PruneService
    db.prune_einstellungen.upsert("mitglied", 30, 0, 10, updated_by="t")
    svc = PruneService(db)
    m = _ins_mitglied(db)
    with db.cursor() as cur:
        cur.execute("INSERT INTO schluessel_chip (kartennummer, mitglied_id) "
                    "VALUES ('C-75', %s)", (m,))
    _soft_delete(db, "mitglied", m, 60)
    _age_history(db, "mitglied_history", m, 60)

    assert {e["name"]: e for e in svc.report()["entities"]}["mitglied"]["loeschbar"] == 0
    svc.prune(dry_run=False)                 # kein FK-Crash
    assert _row_exists(db, "mitglied", m)    # Mitglied bleibt (durch Chip blockiert)


# --- Neue Löschpfade (Inventur 11.08.2026) ----------------------------------------

def test_log_prune_trifft_nur_die_eigene_kategorie(db):
    """Die access_log-Bereiche teilen sich eine Tabelle – ein Lauf darf nur seine
    Kategorie treffen. Sonst nähme das Aufräumen der Seitenaufrufe (90 Tage) die
    Anmelde-Ereignisse (365 Tage) mit."""
    from app.services.prune_service import (
        PruneService, build_log_delete_sql, LOG_BY_NAME,
    )
    with db.cursor() as cur:
        cur.execute("TRUNCATE access_log")
        for kategorie in ("page", "auth", "schliessanlage", "kalender"):
            cur.execute(
                "INSERT INTO access_log (category, event_type, created_at) "
                "VALUES (%s, 'x', now() - interval '400 days')", (kategorie,)
            )

    with db.cursor() as cur:
        cur.execute(build_log_delete_sql(LOG_BY_NAME["access_log_page"]), (90,))
        assert cur.rowcount == 1

    with db.cursor() as cur:
        cur.execute("SELECT category FROM access_log ORDER BY category")
        assert [r["category"] for r in cur.fetchall()] == ["auth", "kalender", "schliessanlage"]

    # Das Auffangbecken nimmt genau die Kategorie, für die es keinen eigenen Bereich gibt.
    with db.cursor() as cur:
        cur.execute(build_log_delete_sql(LOG_BY_NAME["access_log_uebrige"]), (365,))
        assert cur.rowcount == 1
    with db.cursor() as cur:
        cur.execute("SELECT category FROM access_log ORDER BY category")
        assert [r["category"] for r in cur.fetchall()] == ["auth", "schliessanlage"]


def test_aktives_push_abo_ueberlebt_den_prune(db):
    """Regression-Wächter: ts_expr ist NULL, solange nicht widerrufen wurde. Ein Fehler
    hier würde allen Nutzern still die Push-Benachrichtigungen abschalten."""
    from app.services.prune_service import build_log_delete_sql, LOG_BY_NAME
    from datetime import datetime, timedelta
    with db.cursor() as cur:
        cur.execute("TRUNCATE push_subscriptions, push_subscriptions_history CASCADE")
        cur.execute(
            "INSERT INTO users (username,email,password_hash,role,created_by,updated_by) "
            "VALUES ('pushuser','push@x.de','h','mitglied','t','t') RETURNING id"
        )
        uid = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, created_at) "
            "VALUES (%s, 'https://example/aktiv', 'k', 'a', now() - interval '5 years')",
            (uid,),
        )
        cur.execute(
            "INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, created_at, "
            "revoked_at) VALUES (%s, 'https://example/tot', 'k', 'a', "
            "now() - interval '5 years', %s)",
            (uid, (datetime.now() - timedelta(days=400)).isoformat()),
        )

    with db.cursor() as cur:
        cur.execute(build_log_delete_sql(LOG_BY_NAME["push_subscriptions"]), (90,))
        assert cur.rowcount == 1, "nur das widerrufene Abo darf fallen"
    with db.cursor() as cur:
        cur.execute("SELECT endpoint FROM push_subscriptions")
        assert [r["endpoint"] for r in cur.fetchall()] == ["https://example/aktiv"]


def test_finanz_archivierung_rechnet_ab_jahresende(db):
    """Ein Beleg vom März 2015 wird wie einer vom 31.12.2015 behandelt – und ein Beleg
    ohne Datum bleibt unangetastet (sonst risse ihn das leere Jahr sofort mit)."""
    from app.services.prune_service import (
        build_archive_parent_delete_sql, ARCHIVE_REGISTRY,
    )
    regel = next(r for r in ARCHIVE_REGISTRY if r.name == "beitrag_sollstellung_alter")
    # Marker statt TRUNCATE: `beitragsregel` teilt sich den Wegwerf-Container mit dem
    # SEPA-Modul, das auf fortlaufenden IDs aufbaut. Ein RESTART IDENTITY hier lässt
    # dort den Audit-Trigger auf ein schon vergebenes (id, version) laufen.
    marke = "PRUNE-ARCHIV-TEST"
    with db.cursor() as cur:
        cur.execute("INSERT INTO mitglied (vorname,nachname,zahlungsart,created_by) "
                    "VALUES ('A','B','lastschrift',%s) RETURNING id", (marke,))
        mid = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO beitragsregel (name, betrag_pro_monat, einzug_turnus, "
            "gueltig_ab, zahler_typ, created_by) VALUES ('R', 10, 'monatlich', "
            "'2010-01-01', 'mitglied', %s) RETURNING id", (marke,)
        )
        rid = cur.fetchone()["id"]
        ids = []
        for datum, betrag in (("2015-03-04", 100), ("2024-03-04", 200), ("", 300)):
            cur.execute(
                "INSERT INTO beitrag_sollstellung "
                "(mitglied_id, beitragsregel_id, betrag_soll, faelligkeitsdatum, zeitraum, "
                " status, created_by) "
                "VALUES (%s, %s, %s, %s, '2015', 'offen', %s) RETURNING id",
                (mid, rid, betrag, datum, marke)
            )
            ids.append(cur.fetchone()["id"])

    # Stichtag: 10 Jahre zurück. 2015 ist durch, 2024 nicht, undatiert nie.
    from datetime import date, timedelta
    cutoff = (date.today() - timedelta(days=10 * 365)).isoformat()
    with db.cursor() as cur:
        cur.execute(
            build_archive_parent_delete_sql(regel) + " AND created_by = %s",
            ("TEST", cutoff, marke),
        )
        assert cur.rowcount == 1

    with db.cursor() as cur:
        cur.execute("SELECT betrag_soll, deleted_at FROM beitrag_sollstellung "
                    "WHERE id = ANY(%s) ORDER BY betrag_soll", (ids,))
        zeilen = cur.fetchall()
    archiviert = {int(r["betrag_soll"]): r["deleted_at"] is not None for r in zeilen}
    assert archiviert[100] is True, "Beleg von 2015 muss archiviert sein"
    assert archiviert[200] is False, "Beleg von 2024 ist noch aufbewahrungspflichtig"
    assert archiviert[300] is False, "undatierter Beleg darf NIE automatisch verschwinden"

    # Eigene Spuren beseitigen – der Container wird von allen Modulen geteilt.
    with db.cursor() as cur:
        for tabelle in ("beitrag_sollstellung", "beitragsregel", "mitglied"):
            cur.execute(f"DELETE FROM {tabelle}_history WHERE created_by = %s", (marke,))
            cur.execute(f"DELETE FROM {tabelle} WHERE created_by = %s", (marke,))


def test_verwaiste_datei_wird_erkannt_aber_bekannte_nicht(db, tmp_path):
    """Der Orphan-Scan darf nur Dateien nehmen, die keine DB-Zeile kennt – und auch die
    erst nach der Schonfrist. Ein Anhang im Papierkorb ist wiederherstellbar, seine Datei
    gehört also NICHT dazu."""
    import os
    import time
    from app.services.prune_service import PruneService

    dienst = db.anhang_service
    verzeichnis = dienst.upload_path
    verzeichnis.mkdir(parents=True, exist_ok=True)
    for p in verzeichnis.iterdir():
        if p.is_file():
            p.unlink()

    alt = time.time() - 60 * 86400          # deutlich älter als die 30-Tage-Schonfrist
    (verzeichnis / "verwaist.pdf").write_bytes(b"x")
    os.utime(verzeichnis / "verwaist.pdf", (alt, alt))
    (verzeichnis / "frisch.pdf").write_bytes(b"x")          # innerhalb der Schonfrist
    (verzeichnis / "beansprucht.pdf").write_bytes(b"x")
    os.utime(verzeichnis / "beansprucht.pdf", (alt, alt))

    with db.cursor() as cur:
        cur.execute("TRUNCATE tickets, ticket_anhaenge CASCADE")
        cur.execute("TRUNCATE tickets_history")
        cur.execute(
            "INSERT INTO users (username,email,password_hash,role,created_by,updated_by) "
            "VALUES ('anhanguser','anhang@x.de','h','mitglied','t','t') RETURNING id"
        )
        uid = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO tickets (titel, beschreibung, status, gemeldet_von, created_by, "
            "updated_by) VALUES ('t', 'b', 'offen', %s, 't', 't') RETURNING id", (uid,)
        )
        ticket_id = cur.fetchone()["id"]
        # bewusst SOFT-GELÖSCHT: die Datei muss trotzdem als beansprucht gelten
        cur.execute(
            "INSERT INTO ticket_anhaenge (ticket_id, original_name, stored_name, mime_type, "
            "dateigroesse, hochgeladen_von, deleted_at) "
            "VALUES (%s, 'b.pdf', 'beansprucht.pdf', 'application/pdf', 1, %s, now())",
            (ticket_id, uid),
        )

    svc = PruneService(db)
    gefunden = {p.name for p in svc.verwaiste_dateien(30)}
    assert gefunden == {"verwaist.pdf"}, f"unerwartet: {gefunden}"


def test_verwaiste_datei_wird_beim_lauf_entfernt(db):
    """Vorschau = Aktion, auch auf der Platte."""
    import os
    import time
    from app.services.prune_service import PruneService, DATEI_VERWAIST

    verzeichnis = db.anhang_service.upload_path
    verzeichnis.mkdir(parents=True, exist_ok=True)
    for p in verzeichnis.iterdir():
        if p.is_file():
            p.unlink()
    alt = time.time() - 60 * 86400
    ziel = verzeichnis / "muell.pdf"
    ziel.write_bytes(b"x")
    os.utime(ziel, (alt, alt))

    svc = PruneService(db)
    vorschau = {e["name"]: e for e in svc.report()["entities"]}[DATEI_VERWAIST]
    assert vorschau["loeschbar"] == 1

    ergebnis = {e["name"]: e for e in svc.prune(dry_run=False)["entities"]}[DATEI_VERWAIST]
    assert ergebnis["dateien_geloescht"] == 1
    assert not ziel.exists()


def test_archiv_kinder_kennen_ihre_version_spalte(db):
    """`has_version` steuert, ob der Archiv-Soft-Delete ein `version = version + 1`
    schreibt. Steht es falsch, scheitert der Lauf zur Laufzeit auf einer fehlenden
    Spalte – und zwar erst nach zehn Jahren, wenn die erste Zeile fällig wird. Deshalb
    wird die Annahme hier gegen das echte Schema geprüft."""
    from app.services.prune_service import ARCHIVE_REGISTRY

    with db.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND column_name = 'version'"
        )
        mit_version = {r["table_name"] for r in cur.fetchall()}

    falsch = [
        (rule.name, child.table, child.has_version)
        for rule in ARCHIVE_REGISTRY
        for child in rule.children
        if child.has_version != (child.table in mit_version)
    ]
    assert not falsch, (
        "has_version stimmt nicht mit dem Schema überein: "
        + ", ".join(f"{r}/{t} steht auf {v}" for r, t, v in falsch)
    )


# --- Teamkassen-Buchung hält ihren Termin fest (#167) -----------------------------
def _termin_mit_buchung(db):
    """Soft-gelöschter, längst abgelaufener Termin mit einer AKTIVEN Buchung darauf.
    Gibt (termin_id, buchung_id) zurück."""
    with db.cursor() as cur:
        cur.execute("INSERT INTO abteilung (name,created_by,updated_by) "
                    "VALUES ('Deckel-Prune-Abt','t','t') RETURNING id")
        aid = cur.fetchone()["id"]
        cur.execute("INSERT INTO mannschaft (abteilung_id,name,saison,created_by,updated_by) "
                    "VALUES (%s,'M','2020/21','t','t') RETURNING id", (aid,))
        man = cur.fetchone()["id"]
        cur.execute("SELECT id FROM spielstaette WHERE platzhalter='auswaerts'")
        platz = cur.fetchone()["id"]
        cur.execute("INSERT INTO termine (mannschaft_id,typ,beginn,spielstaette_id,"
                    "created_by,updated_by) VALUES (%s,'training',"
                    "(now()-make_interval(days=>900))::date::text||'T19:00',%s,'t','t') "
                    "RETURNING id", (man, platz))
        termin = cur.fetchone()["id"]
    mid = _ins_mitglied(db)
    deckel = db.clubdeckel.create(man, 'Kasse', 't')
    with db.cursor() as cur:
        cur.execute("INSERT INTO clubdeckel_buchung (deckel_id,mitglied_id,typ,betrag,"
                    "termin_id,created_by,updated_by) "
                    "VALUES (%s,%s,'kauf',-1.50,%s,'t','t') RETURNING id",
                    (deckel.id, mid, termin))
        buchung = cur.fetchone()["id"]
    return termin, buchung


def _termin_entity():
    """Termin-Entität mit abgeschalteter Mindestanzahl – sonst hielte keep_min=10
    den einzelnen Testtermin ohnehin fest und der Test bewiese nichts."""
    from dataclasses import replace
    from app.services.prune_service import PRUNE_REGISTRY
    entity = {e.name: e for e in PRUNE_REGISTRY}["termin"]
    return replace(entity, retention_days=30, keep_min=0)


def test_termin_mit_teamkassen_buchung_wird_nicht_hart_geloescht(db):
    """Tor 4: Solange eine Buchung auf den Termin zeigt, bleibt er im Papierkorb.
    Ohne den ChildRef liefe das DELETE in den FK-RESTRICT und risse den Lauf um."""
    from app.services.prune_service import PruneService
    termin, _ = _termin_mit_buchung(db)
    _soft_delete(db, "termine", termin, 900)
    _age_history(db, "termine_history", termin, 900)
    db.prune_einstellungen.upsert("termin", 30, 0, 0, updated_by="t")

    assert _candidates(db, _termin_entity(), 0) == 0

    PruneService(db).prune(dry_run=False)
    assert _row_exists(db, "termine", termin)


def test_termin_wird_loeschbar_sobald_die_buchung_weg_ist(db):
    """Gegenprobe: Die Sperre ist an die Buchung geknüpft, nicht dauerhaft."""
    termin, buchung = _termin_mit_buchung(db)
    _soft_delete(db, "termine", termin, 900)
    _age_history(db, "termine_history", termin, 900)
    entity = _termin_entity()
    assert _candidates(db, entity, 0) == 0

    with db.cursor() as cur:
        cur.execute("DELETE FROM clubdeckel_buchung WHERE id=%s", (buchung,))
    assert _candidates(db, entity, 0) == 1


def test_alters_archivierung_laesst_die_buchung_aktiv(db):
    """Ein Getränk verschwindet nicht aus dem Ledger, weil der Termin alt wird –
    deshalb steht clubdeckel_buchung bewusst NICHT in der ArchiveRule."""
    from app.services.prune_service import PruneService, TERMIN_ALTER
    termin, buchung = _termin_mit_buchung(db)
    db.prune_einstellungen.upsert(TERMIN_ALTER, 30, 0, 1, updated_by="t")

    PruneService(db).prune(dry_run=False)

    with db.cursor() as cur:
        cur.execute("SELECT deleted_at IS NOT NULL AS d FROM termine WHERE id=%s", (termin,))
        assert cur.fetchone()["d"] is True            # Termin archiviert …
        cur.execute("SELECT deleted_at IS NOT NULL AS d FROM clubdeckel_buchung WHERE id=%s",
                    (buchung,))
        assert cur.fetchone()["d"] is False           # … die Buchung bleibt aktiv
