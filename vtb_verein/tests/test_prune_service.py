"""
Tests für die reinen SQL-Bausteine des PruneService (Phase 0, ohne DB).

Geprüft wird die korrekte Übersetzung der Registry in Gates/Parameter – nicht die
Ausführung. Echte DB-Integrationstests folgen mit dem tatsächlichen Löschen (Phase 1+).
"""
from app.services.prune_service import (
    ChildRef,
    LogRule,
    LOG_REGISTRY,
    PruneEntity,
    PRUNE_REGISTRY,
    ARCHIVE_REGISTRY,
    build_active_count_sql,
    build_history_prune_count_sql,
    build_history_prune_delete_sql,
    build_history_total_count_sql,
    build_log_delete_sql,
    build_log_due_count_sql,
    build_log_total_sql,
    build_original_candidate_count_sql,
    build_original_candidate_ids_sql,
    build_papierkorb_count_sql,
    DEFAULT_HISTORY_RETENTION_DAYS,
    _ab_jahresende,
)


def _entity(name: str) -> PruneEntity:
    return next(e for e in PRUNE_REGISTRY if e.name == name)


def _log(name: str) -> LogRule:
    return next(r for r in LOG_REGISTRY if r.name == name)


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

    def test_schliessanlage_und_ul_entitaeten_registriert(self):
        names = {e.name for e in PRUNE_REGISTRY}
        assert {"tuer_app_berechtigung", "tuer_berechtigung", "tuer_schloss",
                "schluessel_chip", "ul_stunde", "ul_abrechnung", "ul_satz"} <= names

    def test_teamkassen_sammlungen_registriert(self):
        """#181: Jede neue Soft-Delete-Tabelle muss ins Register — sonst wachsen
        soft-gelöschte Zeilen unbegrenzt und werden nie bereinigt."""
        order = [e.name for e in PRUNE_REGISTRY]
        assert {"clubdeckel_event", "clubdeckel_event_opt_out"} <= set(order)
        # Die Buchung zeigt per event_id auf die Sammlung, muss also vor ihr weg;
        # die Sammlung selbst vor der Teamkasse.
        assert order.index("clubdeckel_buchung") < order.index("clubdeckel_event")
        assert order.index("clubdeckel_event") < order.index("clubdeckel")
        assert ("clubdeckel_buchung", "event_id") in {
            (c.table, c.fk) for c in _entity("clubdeckel_event").children}
        deckel_kinder = {(c.table, c.fk) for c in _entity("clubdeckel").children}
        assert {("clubdeckel_event", "deckel_id"),
                ("clubdeckel_event_opt_out", "deckel_id")} <= deckel_kinder
        mitglied_kinder = {(c.table, c.fk) for c in _entity("mitglied").children}
        assert {("clubdeckel_event", "fuer_mitglied_id"),
                ("clubdeckel_event_opt_out", "mitglied_id")} <= mitglied_kinder

    def test_mitglied_guards_gegen_schliessanlage_und_ul(self):
        """Befund #75: mitglied darf nicht geprunt werden, solange Chip/Zutritts-Log/ÜL
        darauf zeigen (sonst FK-RESTRICT sprengt den ganzen Lauf)."""
        refs = {(c.table, c.fk) for c in _entity("mitglied").children}
        assert {("schluessel_chip", "mitglied_id"), ("tuer_zutritt_log", "mitglied_id"),
                ("ul_abrechnung", "mitglied_id"), ("ul_satz", "mitglied_id")} <= refs

    def test_abteilung_guards_gegen_schliessanlage_und_ul(self):
        refs = {(c.table, c.fk) for c in _entity("abteilung").children}
        assert {("tuer_schloss", "abteilung_id"), ("ul_abrechnung", "abteilung_id"),
                ("ul_satz", "abteilung_id")} <= refs

    def test_tuer_schloss_deckt_dauerprotokolle_ab(self):
        """tuer_schloss muss auch die nie-soft-gelöschten Logs als Guard führen."""
        refs = {(c.table, c.fk) for c in _entity("tuer_schloss").children}
        assert {("tuer_zutritt_log", "schloss_id"), ("tuer_credential", "schloss_id"),
                ("tuer_schloss_status_log", "schloss_id")} <= refs

    def test_kinder_stehen_vor_dem_elternteil(self):
        """Invariante: ist eine Kind-Tabelle selbst eine Prune-Entität, kommt sie früher
        (Blatt → Wurzel) – sonst stimmt die Löschreihenfolge im Report nicht.

        Selbstbezüge sind davon ausgenommen: ein Storno-Fibu-Export zeigt auf seinen
        Ur-Export in derselben Tabelle. Der Guard wirkt trotzdem (er hält den Ur-Export
        fest, solange sein Storno existiert), nur eine Reihenfolge kann es dafür nicht
        geben – die Tabelle müsste vor sich selbst stehen.
        """
        pos_by_table = {e.table: i for i, e in enumerate(PRUNE_REGISTRY)}
        for i, e in enumerate(PRUNE_REGISTRY):
            for child in e.children:
                if child.table == e.table:
                    continue
                if child.table in pos_by_table:
                    assert pos_by_table[child.table] < i, \
                        f"{child.table} muss vor {e.name} stehen"

    def test_selbstbezug_loest_sich_ueber_mehrere_laeufe(self):
        """Der Selbstbezug darf nicht dazu führen, dass gar nichts mehr geht: das Storno
        ist selbst kinderlos und damit im ersten Lauf löschbar, der Ur-Export folgt im
        nächsten. Genau das Verhalten hat „kein Cascade in einem Lauf" ohnehin."""
        kinder = {(c.table, c.fk) for c in _entity("fibu_export").children}
        assert ("fibu_exporte", "storno_von_export_id") in kinder


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

    def test_active_count_zaehlt_nur_nicht_geloeschte(self):
        sql, params = build_active_count_sql(_entity("mannschaft"))
        assert "FROM mannschaft " in sql
        assert "deleted_at IS NULL" in sql
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


class TestLogRuleSql:
    """Protokolle/Gerätebindungen: Hard-Delete nach Alter, kein Papierkorb."""

    def test_zaehlen_und_loeschen_teilen_dieselbe_bedingung(self):
        """„Vorschau = Aktion" auch hier: was gezählt wird, wird gelöscht."""
        rule = _log("tuer_zutritt_log")
        zaehl = build_log_due_count_sql(rule)
        loesch = build_log_delete_sql(rule)
        bedingung = zaehl.split("WHERE", 1)[1]
        assert loesch.split("WHERE", 1)[1] == bedingung

    def test_kategorie_filter_gilt_auch_beim_loeschen(self):
        """Sonst würde das Löschen der Seitenaufrufe die Anmelde-Ereignisse mitnehmen."""
        loesch = build_log_delete_sql(_log("access_log_page"))
        assert "category = 'page'" in loesch
        assert loesch.startswith("DELETE FROM access_log WHERE")

    def test_auffangbecken_deckt_die_uebrigen_kategorien_ab(self):
        """Neue access_log-Kategorien dürfen nicht still ohne Frist bleiben."""
        rule = _log("access_log_uebrige")
        assert "NOT IN" in rule.where
        # Die drei namentlich geführten Kategorien sind ausgenommen – und nur die.
        for eigene in ("'page'", "'auth'", "'schliessanlage'"):
            assert eigene in rule.where

    def test_gesamtzahl_ohne_alters_parameter(self):
        """Die Mengenangabe im Report darf nicht vom Fenster abhängen."""
        sql = build_log_total_sql(_log("tresor_zugriff_log"))
        assert "%s" not in sql

    def test_geraetebindung_datiert_ab_dem_tod_der_zeile(self):
        """Nicht ab Anlage: eine seit Jahren laufende Sitzung ist nicht fällig."""
        rule = _log("user_sessions")
        assert "revoked_at" in rule.ts_expr and "expires_at" in rule.ts_expr
        assert "created_at" not in rule.ts_expr

    def test_aktives_push_abo_ist_nie_faellig(self):
        """revoked_at NULL -> ts NULL -> Vergleich NULL -> Zeile bleibt. Ohne das würde
        der Prune die aktiven Push-Abos aller Nutzer abräumen."""
        rule = _log("push_subscriptions")
        assert rule.ts_expr == "NULLIF(revoked_at, '')"

    def test_leerer_string_zaehlt_als_nicht_gesetzt(self):
        """revoked_at ist TEXT – '' ist im Schema genauso verbreitet wie NULL."""
        assert "NULLIF" in _log("auth_tokens").ts_expr


class TestJahresendeVerankerung:
    """Aufbewahrungsfristen laufen ab Schluss des Kalenderjahres."""

    def test_datum_wird_auf_silvester_gezogen(self):
        assert _ab_jahresende("buchungsdatum") == \
            "(NULLIF(LEFT(buchungsdatum::text, 4), '') || '-12-31')"

    def test_leeres_datum_wird_nie_faellig(self):
        """Der gefährliche Fall: ohne NULLIF ergäbe '' den Text '-12-31', der vor jedem
        Stichtag liegt – ein undatierter Beleg würde sofort archiviert."""
        ausdruck = _ab_jahresende("buchungsdatum")
        assert "NULLIF(LEFT(buchungsdatum::text, 4), '')" in ausdruck

    def test_finanzregeln_nutzen_die_verankerung(self):
        finanz = [r for r in ARCHIVE_REGISTRY if r.name.endswith("_alter")
                  and r.default_days >= 10 * 365]
        assert finanz, "keine Finanz-Archivregel gefunden"
        for regel in finanz:
            assert "-12-31" in regel.date_expr, f"{regel.name} datiert nicht ab Jahresende"
