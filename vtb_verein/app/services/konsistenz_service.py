"""
KonsistenzService – read-only Prüfung der Daten-Beziehungen, die FKs nicht abdecken.

Hintergrund (siehe Soft-Delete-Only-Prinzip): Es wird nie hart gelöscht, sondern nur
``deleted_at`` gesetzt. FK-Constraints (ohne ON DELETE CASCADE) garantieren zwar die
*physische* Integrität – kein Datensatz zeigt je auf eine nicht existierende Zeile –,
aber sie kennen den Papierkorb nicht: Ein **aktives Kind** (``deleted_at IS NULL``) darf
per FK problemlos auf einen **soft-gelöschten Parent** (``deleted_at IS NOT NULL``) zeigen.
Genau diese „hängenden" Beziehungen findet dieser Service.

Der Scan ist vollständig **generisch aus dem FK-Katalog** (``information_schema``):
  1. Alle Foreign Keys des ``public``-Schemas einlesen.
  2. Nur die behalten, bei denen Kind- UND Parent-Tabelle eine ``deleted_at``-Spalte haben
     (nur dort ist ein soft-gelöschter Parent überhaupt möglich).
  3. Je FK zählen, wie viele aktive Kinder auf einen soft-gelöschten Parent zeigen, plus
     ein paar Beispiel-Parent-IDs als Einstieg für die Recherche.

Read-only: es wird ausschließlich gelesen, nie geschrieben. Die SQL-Bausteine sind reine
Funktionen und damit ohne echtes Postgres testbar.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


# Wie viele Beispiel-Parent-IDs je Befund zurückgegeben werden (Einstieg für die Recherche).
DEFAULT_SAMPLE_LIMIT = 10


@dataclass(frozen=True)
class ForeignKey:
    """Eine Foreign-Key-Beziehung aus dem Katalog: Kind-Spalte -> Parent-Spalte."""
    constraint: str
    child_table: str
    child_column: str
    parent_table: str
    parent_column: str


# --- Reine SQL-Bausteine (ohne DB testbar) ----------------------------------------
# "aktiv" / "gelöscht" spiegeln die Prune-Semantik: deleted_at ist teils TEXT (ISO-String,
# leerer String = nicht gelöscht), teils TIMESTAMPTZ. Der ::text-Vergleich mit '' ist für
# beide Typen gültig und bei TIMESTAMPTZ schlicht nie wahr.
def _child_aktiv(alias: str) -> str:
    return f"({alias}.deleted_at IS NULL OR {alias}.deleted_at::text = '')"


def _parent_geloescht(alias: str) -> str:
    return f"({alias}.deleted_at IS NOT NULL AND {alias}.deleted_at::text <> '')"


def build_fk_catalog_sql() -> tuple[str, list]:
    """Alle Foreign Keys des public-Schemas (Kind-Tabelle/-Spalte -> Parent-Tabelle/-Spalte).

    Alle FKs dieses Schemas sind einspaltig, daher genügt der einfache Dreier-Join über
    den Constraint-Namen ohne Ordinal-Abgleich.
    """
    sql = (
        "SELECT tc.constraint_name AS constraint, "
        "       tc.table_name      AS child_table, "
        "       kcu.column_name    AS child_column, "
        "       ccu.table_name     AS parent_table, "
        "       ccu.column_name    AS parent_column "
        "FROM information_schema.table_constraints tc "
        "JOIN information_schema.key_column_usage kcu "
        "  ON kcu.constraint_name = tc.constraint_name "
        " AND kcu.table_schema = tc.table_schema "
        "JOIN information_schema.constraint_column_usage ccu "
        "  ON ccu.constraint_name = tc.constraint_name "
        " AND ccu.table_schema = tc.table_schema "
        "WHERE tc.constraint_type = 'FOREIGN KEY' "
        "  AND tc.table_schema = 'public' "
        "ORDER BY child_table, child_column"
    )
    return sql, []


def build_softdelete_tables_sql() -> tuple[str, list]:
    """Alle Tabellen des public-Schemas, die eine ``deleted_at``-Spalte besitzen."""
    sql = (
        "SELECT table_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND column_name = 'deleted_at'"
    )
    return sql, []


def build_verletzung_count_sql(fk: ForeignKey) -> tuple[str, list]:
    """Zahl der aktiven Kinder, die auf einen soft-gelöschten Parent zeigen."""
    sql = (
        f"SELECT COUNT(*) AS n "
        f"FROM {fk.child_table} c "
        f"JOIN {fk.parent_table} p ON c.{fk.child_column} = p.{fk.parent_column} "
        f"WHERE {_child_aktiv('c')} AND {_parent_geloescht('p')}"
    )
    return sql, []


def build_verletzung_sample_sql(fk: ForeignKey, limit: int = DEFAULT_SAMPLE_LIMIT) -> tuple[str, list]:
    """Ein paar betroffene (soft-gelöschte) Parent-IDs als Einstieg für die Recherche."""
    sql = (
        f"SELECT DISTINCT c.{fk.child_column} AS parent_id "
        f"FROM {fk.child_table} c "
        f"JOIN {fk.parent_table} p ON c.{fk.child_column} = p.{fk.parent_column} "
        f"WHERE {_child_aktiv('c')} AND {_parent_geloescht('p')} "
        f"ORDER BY c.{fk.child_column} "
        f"LIMIT {int(limit)}"
    )
    return sql, []


class KonsistenzService:
    """Orchestriert den generischen Konsistenz-Scan. Ausschließlich read-only."""

    def __init__(self, db):
        self._db = db

    def _fetchall(self, sql: str, params: list) -> list[dict]:
        with self._db.cursor() as cur:
            cur.execute(sql, tuple(params))
            return list(cur.fetchall())

    def _fetchone(self, sql: str, params: list) -> dict | None:
        with self._db.cursor() as cur:
            cur.execute(sql, tuple(params))
            return cur.fetchone()

    def _soft_delete_foreign_keys(self) -> list[ForeignKey]:
        """FKs, bei denen Kind UND Parent soft-delete-fähig sind (nur die sind prüfbar)."""
        sql, params = build_softdelete_tables_sql()
        soft = {r["table_name"] for r in self._fetchall(sql, params)}

        sql, params = build_fk_catalog_sql()
        fks: list[ForeignKey] = []
        for r in self._fetchall(sql, params):
            if r["child_table"] in soft and r["parent_table"] in soft:
                fks.append(ForeignKey(
                    constraint=r["constraint"],
                    child_table=r["child_table"],
                    child_column=r["child_column"],
                    parent_table=r["parent_table"],
                    parent_column=r["parent_column"],
                ))
        return fks

    def pruefung(self, sample_limit: int = DEFAULT_SAMPLE_LIMIT) -> dict:
        """Scan: aktive Kinder, die auf soft-gelöschte Parents zeigen. Löscht/ändert NICHTS."""
        fks = self._soft_delete_foreign_keys()
        befunde: list[dict] = []
        summe = 0

        for fk in fks:
            cnt_sql, cnt_params = build_verletzung_count_sql(fk)
            row = self._fetchone(cnt_sql, cnt_params)
            anzahl = int(row["n"]) if row else 0
            if anzahl == 0:
                continue

            s_sql, s_params = build_verletzung_sample_sql(fk, sample_limit)
            beispiele = [r["parent_id"] for r in self._fetchall(s_sql, s_params)]

            summe += anzahl
            befunde.append({
                "constraint": fk.constraint,
                "child_table": fk.child_table,
                "child_column": fk.child_column,
                "parent_table": fk.parent_table,
                "parent_column": fk.parent_column,
                "verletzungen": anzahl,
                "beispiel_parent_ids": beispiele,
            })

        # Auffälligste Befunde zuerst.
        befunde.sort(key=lambda b: b["verletzungen"], reverse=True)

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "geprueft": len(fks),
            "befunde": befunde,
            "summe_verletzungen": summe,
            "alles_konsistent": summe == 0,
        }
