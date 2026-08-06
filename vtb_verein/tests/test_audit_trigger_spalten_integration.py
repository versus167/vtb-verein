"""
Integrationstest: Audit-Trigger schreiben jede History-Spalte mit.

Hintergrund (Schema-Diff 2026-08-06): v78→v79 hat die SEPA-Spalten an
``fibu_einstellungen`` und deren History gehängt, die Audit-Funktionen aber nicht
neu erzeugt. Auf gewachsenen DBs schrieb der Trigger die fünf neuen Spalten
deshalb nie mit — die History war still unvollständig, ohne Fehler, ohne Warnung.
Der Frischaufbau war korrekt, weil er dieselbe Konstante nutzt; auffallen konnte
das nur im Vergleich beider Pfade.

Dieser Test prüft die Eigenschaft direkt am Schema: Für jede ``*_history``-Tabelle
muss die zugehörige Audit-Funktion jede Spalte der History erwähnen. Damit fällt
eine vergessene Spalte künftig sofort auf — egal in welcher Migration sie entsteht.

Läuft nur mit ``VTB_TEST_DATABASE_URL`` auf einer LEEREN Wegwerf-DB:
    docker run -d --name vtb-pg-audittest -e POSTGRES_USER=test \\
        -e POSTGRES_PASSWORD=test -e POSTGRES_DB=audittest -p 55433:5432 postgres:18
    VTB_TEST_DATABASE_URL=postgresql://test:test@localhost:55433/audittest \\
        ./venv/bin/python -m pytest vtb_verein/tests/test_audit_trigger_spalten_integration.py
"""
import os
import re

import pytest

_URL = os.getenv("VTB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _URL, reason="VTB_TEST_DATABASE_URL nicht gesetzt (Wegwerf-Postgres nötig)"
)

# Spalten, die eine History führt, ohne dass der Trigger sie aus NEW übernimmt:
# Sie entstehen erst beim Schreiben der History-Zeile selbst.
_NICHT_AUS_NEW = {"history_id", "geaendert_am", "geaendert_von", "archiviert_am"}


@pytest.fixture(scope="module")
def db():
    from app.db.datastore import VereinsDB
    d = VereinsDB(_URL, upload_path="/tmp/vtb-audit-uploads")
    yield d
    d.close()


def _history_tabellen(cur) -> list[str]:
    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name LIKE '%\\_history'
        ORDER BY table_name
    """)
    return [r['table_name'] for r in cur.fetchall()]


def _funktionen_zur_tabelle(cur, basis: str) -> dict[str, str]:
    """Quelltext der Audit-Funktionen, die auf ``basis`` getriggert sind."""
    cur.execute("""
        SELECT p.proname, p.prosrc
        FROM pg_trigger t
        JOIN pg_class c ON c.oid = t.tgrelid
        JOIN pg_proc p ON p.oid = t.tgfoid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relname = %s AND NOT t.tgisinternal
    """, (basis,))
    return {r['proname']: r['prosrc'] for r in cur.fetchall()}


def test_audit_funktionen_schreiben_alle_history_spalten(db):
    """Jede History-Spalte muss in der zugehörigen Audit-Funktion vorkommen.

    Geprüft wird der Funktionsquelltext, nicht das Verhalten: Eine Spalte, die im
    INSERT der Funktion fehlt, bleibt in der History dauerhaft NULL.
    """
    fehlend: dict[str, list[str]] = {}
    with db.cursor() as cur:
        for history in _history_tabellen(cur):
            basis = history[:-len("_history")]
            funktionen = _funktionen_zur_tabelle(cur, basis)
            if not funktionen:
                continue                      # Tabelle ohne Audit-Trigger (z. B. reine Archive)

            # Nur Spalten, die es auch in der Live-Tabelle gibt: Eine History-Spalte
            # ohne Gegenstück ist ein Altbestand (z. B. mitglied_history.email/telefon
            # aus der Zeit vor den Kontakt-Zeilen, v74) — der Trigger kann sie nicht
            # füllen, sie hält nur die Historie alter Zeilen lesbar.
            cur.execute("""
                SELECT h.column_name FROM information_schema.columns h
                JOIN information_schema.columns l
                  ON l.table_schema = 'public' AND l.table_name = %s
                 AND l.column_name = h.column_name
                WHERE h.table_schema = 'public' AND h.table_name = %s
            """, (basis, history))
            spalten = {r['column_name'] for r in cur.fetchall()} - _NICHT_AUS_NEW

            for name, quelltext in funktionen.items():
                if 'INSERT INTO %s' % history not in quelltext.replace('\n', ' '):
                    continue                  # Trigger ohne History-Insert (z. B. updated_at)
                genannt = set(re.findall(r'\bNEW\.(\w+)', quelltext))
                if luecke := sorted(spalten - genannt):
                    fehlend[f"{name} → {history}"] = luecke

    assert not fehlend, (
        "Audit-Funktionen übergehen History-Spalten (bleiben dauerhaft NULL):\n"
        + "\n".join(f"  {k}: {', '.join(v)}" for k, v in sorted(fehlend.items()))
    )


def test_fibu_einstellungen_history_faengt_sepa_werte(db):
    """Regression zum konkreten Fund: SEPA-Angaben landen wirklich in der History."""
    with db.cursor() as cur:
        cur.execute("""
            UPDATE fibu_einstellungen
            SET sepa_glaeubiger_id = 'DE98ZZZ09999999999',
                sepa_glaeubiger_name = 'Testverein',
                version = version + 1, updated_by = 'test'
            WHERE id = 1
        """)
        cur.execute("""
            SELECT sepa_glaeubiger_id, sepa_glaeubiger_name
            FROM fibu_einstellungen_history
            WHERE id = 1 ORDER BY version DESC LIMIT 1
        """)
        zeile = cur.fetchone()

    assert zeile is not None, "Kein History-Eintrag trotz version-Bump"
    assert zeile['sepa_glaeubiger_id'] == 'DE98ZZZ09999999999'
    assert zeile['sepa_glaeubiger_name'] == 'Testverein'
