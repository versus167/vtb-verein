"""
Tests für die reinen SQL-Bausteine des PruneService (Phase 0, ohne DB).

Geprüft wird die korrekte Übersetzung der Registry in Gates/Parameter – nicht die
Ausführung. Echte DB-Integrationstests folgen mit dem tatsächlichen Löschen (Phase 1+).
"""
from app.services.prune_service import (
    ChildRef,
    PruneEntity,
    PRUNE_REGISTRY,
    build_history_prune_count_sql,
    build_history_prune_delete_sql,
    build_history_total_count_sql,
    build_original_candidate_count_sql,
    build_original_candidate_ids_sql,
    build_papierkorb_count_sql,
    DEFAULT_HISTORY_RETENTION_DAYS,
)


def _entity(name: str) -> PruneEntity:
    return next(e for e in PRUNE_REGISTRY if e.name == name)


class TestRegistry:
    def test_blaetter_vor_wurzel(self):
        """mitglied (Wurzel) steht nach seinen Kind-Tabellen."""
        order = [e.name for e in PRUNE_REGISTRY]
        for leaf in ("mitglied_kontakt", "mitglied_abteilung", "mitglied_funktion",
                     "mitglied_mannschaft", "mannschaft"):
            assert order.index(leaf) < order.index("mitglied")

    def test_mitglied_kinder_decken_links_ab(self):
        kinder = {c.table for c in _entity("mitglied").children}
        assert {"mitglied_kontakt", "mitglied_abteilung", "mitglied_funktion",
                "mitglied_mannschaft", "beitrag_sollstellung", "gebuehr_forderung"} <= kinder

    def test_anhang_entitaeten_sind_dateibehaftete_blaetter(self):
        for name in ("ticket_anhang", "kassenbuchung_anhang"):
            e = _entity(name)
            assert e.stored_name_col == "stored_name"
            assert e.history_table is None        # keine History
            assert e.children == ()               # reines Blatt

    def test_stammdaten_und_ticket_entitaeten_registriert(self):
        names = {e.name for e in PRUNE_REGISTRY}
        assert {"abteilung", "funktion", "funktion_permission",
                "ticket", "ticket_kommentar", "ticket_bereich", "ticket_kategorie",
                "ticket_teilnehmer", "ticket_bereich_berechtigung"} <= names

    def test_kinder_stehen_vor_dem_elternteil(self):
        """Invariante: ist eine Kind-Tabelle selbst eine Prune-Entität, kommt sie früher
        (Blatt → Wurzel) – sonst stimmt die Löschreihenfolge im Report nicht."""
        pos_by_table = {e.table: i for i, e in enumerate(PRUNE_REGISTRY)}
        for i, e in enumerate(PRUNE_REGISTRY):
            for child in e.children:
                if child.table in pos_by_table:
                    assert pos_by_table[child.table] < i, \
                        f"{child.table} muss vor {e.name} stehen"


class TestOriginalCandidateSql:
    def test_leaf_hat_keine_kind_klausel_aber_history_gate(self):
        sql, params = build_original_candidate_count_sql(_entity("mitglied_kontakt"), 90, 10, 365)
        # Tor 2 + 3 + 5, kein Tor 4 (keine Kinder)
        assert "make_interval(days => %s)" in sql
        assert "r.rn > %s" in sql
        assert "mitglied_kontakt_history" in sql
        assert "SELECT 1 FROM c" not in sql  # keine Kind-Subqueries
        # Params: retention_days, keep_min, history_retention_days
        assert params == [90, 10, 365]

    def test_mitglied_hat_eine_klausel_pro_kind(self):
        ent = _entity("mitglied")
        sql, params = build_original_candidate_count_sql(
            ent, ent.retention_days, ent.keep_min, DEFAULT_HISTORY_RETENTION_DAYS
        )
        for child in ent.children:
            assert f"FROM {child.table} c WHERE c.{child.fk} = r.id" in sql
        # genau ein History-Param am Ende zusätzlich zu retention/keep_min
        assert params[:2] == [ent.retention_days, ent.keep_min]
        assert params[-1] == DEFAULT_HISTORY_RETENTION_DAYS

    def test_keep_min_nutzt_row_number(self):
        sql, _ = build_original_candidate_count_sql(_entity("mannschaft"), 90, 10, 365)
        assert "ROW_NUMBER() OVER" in sql
        assert "deleted_at IS NOT NULL" in sql

    def test_ohne_history_kein_history_gate_und_param(self):
        ent = PruneEntity("x", "X", "x_tbl", history_table=None,
                          children=(ChildRef("y_tbl", "x_id"),))
        sql, params = build_original_candidate_count_sql(ent, 90, 10, 365)
        assert "_history" not in sql
        assert params == [90, 10]  # kein history_retention_days


class TestHistoryAndPapierkorbSql:
    def test_history_prune_ist_datums_only(self):
        sql, params = build_history_prune_count_sql(_entity("mitglied"))
        assert "mitglied_history" in sql
        assert "make_interval(days => %s)" in sql
        assert "ROW_NUMBER" not in sql  # keine Mindestanzahl -> History fließt vollständig ab
        assert params == []  # Service ergänzt history_retention_days

    def test_papierkorb_zaehlt_soft_deletes(self):
        sql, params = build_papierkorb_count_sql(_entity("mannschaft"))
        assert "FROM mannschaft " in sql
        assert "deleted_at IS NOT NULL" in sql
        assert params == []

    def test_history_total_zaehlt_alle_history_zeilen(self):
        sql, params = build_history_total_count_sql(_entity("mitglied"))
        assert "FROM mitglied_history" in sql
        assert "WHERE" not in sql           # Gesamtzahl, keine Filterung
        assert params == []

    def test_history_delete_gleiche_logik_wie_zaehler(self):
        d_sql, d_params = build_history_prune_delete_sql(_entity("mitglied"))
        c_sql, _ = build_history_prune_count_sql(_entity("mitglied"))
        assert d_sql.startswith("DELETE FROM mitglied_history")
        # gleiche WHERE-Klausel wie der Zähler (nur SELECT vs DELETE davor)
        assert d_sql.split("WHERE", 1)[1] == c_sql.split("WHERE", 1)[1]
        assert d_params == []


class TestCandidateIds:
    def test_count_baut_auf_id_select_auf(self):
        ent = _entity("mitglied")
        ids_sql, ids_params = build_original_candidate_ids_sql(ent, 90, 10, 365)
        cnt_sql, cnt_params = build_original_candidate_count_sql(ent, 90, 10, 365)
        assert "SELECT r.id FROM ranked r WHERE" in ids_sql
        assert ids_sql in cnt_sql          # COUNT umschließt exakt das ID-SELECT
        assert cnt_sql.startswith("SELECT COUNT(*) AS n FROM (")
        assert ids_params == cnt_params    # identische Tor-Parameter

    def test_key_basierter_child_ref_nutzt_korrelierte_subquery(self):
        sql, _ = build_original_candidate_ids_sql(_entity("funktion"), 90, 10, 365)
        assert "FROM funktion_permission c WHERE c.funktion_id = r.id" in sql   # id-basiert
        assert ("FROM mitglied_funktion c WHERE c.funktion = "
                "(SELECT p.key FROM funktion p WHERE p.id = r.id)") in sql      # key-basiert
