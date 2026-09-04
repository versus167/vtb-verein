"""
Tests für den KonsistenzService (read-only Scan „aktives Kind -> soft-gelöschter Parent").

Geprüft wird die reine SQL-Übersetzung sowie die Orchestrierung von ``pruefung()`` gegen
einen Fake-``db.cursor()`` – ohne echtes Postgres. Der Live-Scan gegen die echte DB fährt
der Betreiber über den Admin-Endpunkt.
"""
from contextlib import contextmanager

from app.services.konsistenz_service import (
    GEWOLLTE_VERWEISE,
    KAT_GEWOLLT,
    _registry_verweise,
    KAT_NACHZUG,
    KAT_OFFEN,
    ForeignKey,
    KonsistenzService,
    kategorie,
    build_fk_catalog_sql,
    build_reparatur_verwaiste_rechte_sql,
    build_softdelete_tables_sql,
    build_verletzung_count_sql,
    build_verletzung_sample_sql,
)


def _fk(child_table="mitglied_abteilung", child_column="abteilung_id",
        parent_table="abteilung", parent_column="id", constraint="fk_ma_abt"):
    return ForeignKey(constraint, child_table, child_column, parent_table, parent_column)


class TestBuilders:
    def test_katalog_liest_nur_fks_im_public_schema(self):
        sql, params = build_fk_catalog_sql()
        assert "FOREIGN KEY" in sql
        assert "table_schema = 'public'" in sql
        assert params == []

    def test_softdelete_tabellen_ueber_deleted_at_spalte(self):
        sql, params = build_softdelete_tables_sql()
        assert "column_name = 'deleted_at'" in sql
        assert params == []

    def test_count_zaehlt_aktives_kind_auf_geloeschten_parent(self):
        sql, params = build_verletzung_count_sql(_fk())
        assert "COUNT(*)" in sql
        assert "FROM mitglied_abteilung c" in sql
        assert "JOIN abteilung p ON c.abteilung_id = p.id" in sql
        # aktives Kind ...
        assert "c.deleted_at IS NULL" in sql
        # ... auf soft-gelöschten Parent
        assert "p.deleted_at IS NOT NULL" in sql
        assert params == []

    def test_sample_liefert_distinct_parent_ids_mit_limit(self):
        sql, _ = build_verletzung_sample_sql(_fk(), limit=5)
        assert "DISTINCT c.abteilung_id" in sql
        assert "LIMIT 5" in sql
        assert "ORDER BY c.abteilung_id" in sql

    def test_leerstring_deleted_at_gilt_als_nicht_geloescht(self):
        """deleted_at ist teils TEXT ('' = aktiv) – der ::text-Vergleich muss dabei sein."""
        sql, _ = build_verletzung_count_sql(_fk())
        assert "c.deleted_at::text = ''" in sql      # Kind aktiv
        assert "p.deleted_at::text <> ''" in sql     # Parent gelöscht


# --- Fake-DB für pruefung() -------------------------------------------------------
class _FakeCursor:
    def __init__(self, db):
        self._db = db
        self._rows: list[dict] = []

    def execute(self, sql, params=()):
        self._db.executed.append(sql)
        self._rows = self._db._resolve(sql)

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass


class _FakeDB:
    """Beantwortet die vier Query-Arten des Service anhand des SQL-Texts."""

    def __init__(self, soft_tables, fk_rows, violations):
        self._soft = soft_tables
        self._fks = fk_rows
        # violations: {(child_table, child_column, parent_table, parent_column): [parent_ids]}
        self._viol = violations
        self.executed: list[str] = []

    @contextmanager
    def cursor(self):
        yield _FakeCursor(self)

    def _match(self, sql):
        for key, ids in self._viol.items():
            ct, cc, pt, pc = key
            if f"FROM {ct} c JOIN {pt} p ON c.{cc} = p.{pc}" in sql:
                return ids
        return []

    def _resolve(self, sql):
        if "information_schema.columns" in sql:
            return [{"table_name": t} for t in self._soft]
        if "information_schema.table_constraints" in sql:
            return list(self._fks)
        if "COUNT(*)" in sql:
            return [{"n": len(self._match(sql))}]
        if "DISTINCT" in sql:
            return [{"parent_id": i} for i in dict.fromkeys(self._match(sql))]  # DISTINCT
        raise AssertionError(f"Unerwartetes SQL: {sql}")


def _fk_row(constraint, child_table, child_column, parent_table, parent_column="id"):
    return {
        "constraint": constraint,
        "child_table": child_table,
        "child_column": child_column,
        "parent_table": parent_table,
        "parent_column": parent_column,
    }


class TestPruefung:
    def test_nur_fks_mit_soft_delete_auf_beiden_seiten_werden_geprueft(self):
        soft = {"mitglied_abteilung", "abteilung", "mitglied"}
        fks = [
            _fk_row("fk_ma_abt", "mitglied_abteilung", "abteilung_id", "abteilung"),
            # Parent 'users' NICHT soft-delete-fähig -> wird ignoriert
            _fk_row("fk_m_user", "mitglied", "user_id", "users"),
        ]
        db = _FakeDB(soft, fks, violations={})
        report = KonsistenzService(db).pruefung()

        assert report["geprueft"] == 1            # nur die abteilung-FK
        assert report["alles_konsistent"] is True
        assert report["befunde"] == []
        # der ignorierte FK darf keine COUNT-Query ausgelöst haben
        assert not any("mitglied c JOIN users p" in s for s in db.executed)

    def test_findet_haengende_verweise_und_summiert(self):
        soft = {"mitglied_abteilung", "abteilung", "mitglied_funktion", "funktion"}
        fks = [
            _fk_row("fk_ma_abt", "mitglied_abteilung", "abteilung_id", "abteilung"),
            _fk_row("fk_mf_fkt", "mitglied_funktion", "funktion_id", "funktion"),
        ]
        violations = {
            ("mitglied_abteilung", "abteilung_id", "abteilung", "id"): [7, 7, 12],
            ("mitglied_funktion", "funktion_id", "funktion", "id"): [3],
        }
        db = _FakeDB(soft, fks, violations)
        report = KonsistenzService(db).pruefung()

        assert report["geprueft"] == 2
        assert report["alles_konsistent"] is False
        assert report["summe_verletzungen"] == 4          # 3 + 1
        # Offene zuerst, danach nach Anzahl: `mitglied_abteilung.abteilung_id` steht als
        # ChildRef ohne Nachzug im PRUNE_REGISTRY (die Zuordnung überlebt ihre Abteilung
        # bewusst) und ist damit eingeordnet – trotz der größeren Zahl steht sie hinten.
        # `mitglied_funktion.funktion_id` kennt das Registry nicht: der eine Fall, der
        # jemanden erfordert.
        assert report["summe_offen"] == 1
        assert report["befunde"][0]["child_table"] == "mitglied_funktion"
        assert report["befunde"][0]["verletzungen"] == 1
        assert report["befunde"][1]["child_table"] == "mitglied_abteilung"
        assert report["befunde"][1]["verletzungen"] == 3
        assert report["befunde"][1]["beispiel_parent_ids"] == [7, 12]  # DISTINCT-Sample

    def test_befunde_ohne_verletzung_werden_weggelassen(self):
        soft = {"mitglied_abteilung", "abteilung"}
        fks = [_fk_row("fk_ma_abt", "mitglied_abteilung", "abteilung_id", "abteilung")]
        db = _FakeDB(soft, fks, violations={})   # keine Verletzungen
        report = KonsistenzService(db).pruefung()

        assert report["geprueft"] == 1
        assert report["befunde"] == []
        assert report["alles_konsistent"] is True


class TestReparaturVerwaisteRechte:
    def test_builder_trifft_nur_aktive_rechte_geloeschter_user(self):
        sql, params = build_reparatur_verwaiste_rechte_sql()
        assert sql.startswith("UPDATE user_permissions")
        assert "version = version + 1" in sql          # löst den Audit-Trigger aus
        assert "FROM users u" in sql
        assert "up.deleted_at IS NULL" in sql          # nur aktive Rechte
        assert "u.deleted_at IS NOT NULL" in sql       # nur gelöschte User
        assert params == []

    def test_service_gibt_bereinigte_anzahl_und_akteur_doppelt(self):
        class _Cur:
            rowcount = 7
            def execute(self, sql, params=()):
                self.last_params = params
            def close(self):
                pass

        class _DB:
            def __init__(self):
                self._cur = _Cur()
            @contextmanager
            def cursor(self):
                yield self._cur

        db = _DB()
        result = KonsistenzService(db).repariere_verwaiste_rechte(actor="admin")
        assert result == {"bereinigt": 7}
        # Akteur füllt deleted_by UND updated_by
        assert db._cur.last_params == ("admin", "admin")


class TestEinordnung:
    """Ohne Einordnung ist der Bericht dauerhaft rot und damit wertlos.

    Rund zwei Dutzend hängende Verweise sind erwartet – teils gewollt (Urheber-Angaben),
    teils vorübergehend (der Prune zieht sie nach). Stünden sie gleichrangig neben einer
    echten Lücke, fiele die nicht mehr auf.
    """

    def test_childref_ohne_nachziehen_ist_gewollt(self):
        """Die Einordnung kommt aus dem PRUNE_REGISTRY, nicht aus einer zweiten Liste.

        Ein ChildRef OHNE ``nachziehen`` ist bereits die Aussage „das Kind erwähnt den
        Eltern-Datensatz nur und muss ihn überleben" – dieselbe, die der Bericht
        braucht. Sie hier noch einmal zu pflegen hieße, dieselbe Entscheidung an zwei
        Orten zu treffen.
        """
        for paar in [("tickets", "gemeldet_von"),          # Melder
                     ("tickets", "zugewiesen_an"),          # Bearbeiter
                     ("ticket_anhaenge", "hochgeladen_von"),
                     ("kassenbuchung_anhaenge", "hochgeladen_von"),
                     ("clubdeckel_buchung", "artikel_id")]:
            kat, grund = kategorie(*paar)
            assert kat == KAT_GEWOLLT, paar
            assert grund, f"{paar} ohne Begründung"

    def test_childref_mit_nachziehen_ist_nachzug(self):
        assert kategorie("mitglied_kontakt", "mitglied_id")[0] == KAT_NACHZUG
        assert kategorie("ul_stunde", "abrechnung_id")[0] == KAT_NACHZUG

    def test_offen_heisst_dem_registry_unbekannt(self):
        """Die einzige Kategorie, die jemanden erfordert: Hier hat noch nie jemand
        entschieden, ob das Kind seinem Eltern-Datensatz gehört."""
        assert kategorie("irgendeine_tabelle", "irgendeine_spalte") == (KAT_OFFEN, "")

    def test_handliste_wiederholt_nichts_aus_dem_registry(self):
        """Ein Override für ein Paar, das das Registry ohnehin kennt, ist tote Konfiguration
        – und die schlimmere Sorte: Sie sieht nach einer Entscheidung aus und wird nie
        wieder mit dem Registry abgeglichen."""
        doppelt = sorted(set(GEWOLLTE_VERWEISE) & set(_registry_verweise()))
        assert not doppelt, f"Schon im PRUNE_REGISTRY eingeordnet: {doppelt}"

    def test_jede_ausnahme_hat_eine_begruendung(self):
        leer = [k for k, v in GEWOLLTE_VERWEISE.items() if not (v or "").strip()]
        assert not leer, f"Ausnahmen ohne Begründung: {leer}"

    def test_gruene_ampel_haengt_an_den_offenen(self):
        """Ein Bericht voller erwarteter Zeilen ist konsistent – solange nichts offen ist."""
        soft = {"tickets", "users", "mitglied_kontakt", "mitglied"}
        fks = [_fk_row("fk_t", "tickets", "gemeldet_von", "users"),
               _fk_row("fk_mk", "mitglied_kontakt", "mitglied_id", "mitglied")]
        violations = {
            ("tickets", "gemeldet_von", "users", "id"): [1, 2, 3, 4, 5, 6, 7],
            ("mitglied_kontakt", "mitglied_id", "mitglied", "id"): [8, 9, 10],
        }
        bericht = KonsistenzService(_FakeDB(soft, fks, violations)).pruefung()

        assert bericht["summe_verletzungen"] == 10
        assert bericht["summe_offen"] == 0
        assert bericht["alles_konsistent"] is True
        assert {b["kategorie"] for b in bericht["befunde"]} == {KAT_GEWOLLT, KAT_NACHZUG}

    def test_ein_offener_befund_faerbt_den_bericht_rot(self):
        soft = {"tickets", "users", "neue_tabelle", "mitglied"}
        fks = [_fk_row("fk_t", "tickets", "gemeldet_von", "users"),
               _fk_row("fk_neu", "neue_tabelle", "parent_id", "mitglied")]
        violations = {
            ("tickets", "gemeldet_von", "users", "id"): [1, 2, 3, 4, 5],
            ("neue_tabelle", "parent_id", "mitglied", "id"): [42, 43, 44],
        }
        bericht = KonsistenzService(_FakeDB(soft, fks, violations)).pruefung()

        assert bericht["summe_offen"] == 3
        assert bericht["alles_konsistent"] is False
        # Offene zuerst, auch wenn sie die kleinere Zahl tragen – sonst geht der eine
        # echte Fund zwischen den erwarteten unter.
        assert bericht["befunde"][0]["child_table"] == "neue_tabelle"

