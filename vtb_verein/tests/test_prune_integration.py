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


@pytest.fixture(autouse=True)
def clean(db):
    """Vor jedem Test: alle relevanten Tabellen + History leeren (Wegwerf-DB)."""
    with db.cursor() as cur:
        cur.execute(
            "TRUNCATE mitglied, mannschaft, mitglied_kontakt, mitglied_abteilung, "
            "mitglied_funktion, mitglied_mannschaft, beitrag_sollstellung, "
            "gebuehr_forderung, users, tickets, ticket_anhaenge, abteilung "
            "RESTART IDENTITY CASCADE"
        )
        cur.execute(
            "TRUNCATE mitglied_history, mitglied_kontakt_history, users_history, "
            "tickets_history, abteilung_history RESTART IDENTITY"
        )
        cur.execute("TRUNCATE prune_einstellungen")
    yield


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
            f"UPDATE {table} SET deleted_at=(now()-make_interval(days=>%s))::text, "
            f"deleted_by='t', version=version+1 WHERE id=%s", (days_ago, id_)
        )


def _soft_delete_plain(db, table, id_, days_ago):
    """Soft-Delete für Tabellen OHNE version/History (z.B. Anhänge): nur deleted_at."""
    with db.cursor() as cur:
        cur.execute(
            f"UPDATE {table} SET deleted_at=(now()-make_interval(days=>%s))::text, "
            f"deleted_by='t' WHERE id=%s", (days_ago, id_)
        )


def _age_history(db, htable, id_, days_ago):
    """Simuliert vollständig abgeflossene History: alle Zeitstempel zurückdatieren."""
    with db.cursor() as cur:
        cur.execute(
            f"UPDATE {htable} SET created_at=(now()-make_interval(days=>%s))::text, "
            f"updated_at=(now()-make_interval(days=>%s))::text WHERE id=%s",
            (days_ago, days_ago, id_)
        )
        cur.execute(
            f"UPDATE {htable} SET deleted_at=(now()-make_interval(days=>%s))::text "
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


def test_papierkorb_zaehler(db):
    """Papierkorb zählt nur soft-deleted, nicht aktive Datensätze."""
    m = _ins_mitglied(db)
    for d in (1, 60):
        k = _ins_kontakt(db, m); _soft_delete(db, "mitglied_kontakt", k, d)
    _ins_kontakt(db, m)   # aktiv
    pk_sql, pk_params = build_papierkorb_count_sql(_KONTAKT)
    assert _count(db, pk_sql, pk_params) == 2
