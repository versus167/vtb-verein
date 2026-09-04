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
from functools import lru_cache


# Wie viele Beispiel-Parent-IDs je Befund zurückgegeben werden (Einstieg für die Recherche).
DEFAULT_SAMPLE_LIMIT = 10

# --- Einordnung der Befunde --------------------------------------------------------
# Ohne sie ist der Bericht dauerhaft rot und damit wertlos: Ein Teil der hängenden
# Verweise ist gewollt und verschwindet nie, ein weiterer löst sich von selbst auf.
# Zwischen zwei Dutzend erwarteten Zeilen fällt die eine neue nicht mehr auf.
KAT_OFFEN = 'offen'              # echter Befund – hier fehlt eine Kaskade
KAT_GEWOLLT = 'gewollt'          # bewusst so, löst sich nie auf
KAT_NACHZUG = 'nachzug'          # vorübergehend, der Prune räumt es weg

# Handpflege NUR für Beziehungen, die das PRUNE_REGISTRY gar nicht kennt (siehe
# `kategorie`). Normalerweise leer: Steht ein Paar im Registry, ist es dort schon
# eingeordnet, und eine zweite Liste hier liefe unweigerlich davon weg. Wer hier etwas
# einträgt, nimmt es dauerhaft aus der Aufmerksamkeit – deshalb mit Begründung.
GEWOLLTE_VERWEISE: dict[tuple[str, str], str] = {}


@lru_cache(maxsize=1)
def _registry_verweise() -> dict:
    """(Kind-Tabelle, Kind-Spalte) -> (Eltern-Tabelle, wird nachgezogen?).

    Das PRUNE_REGISTRY hat die Einordnung längst getroffen, mitsamt Begründung im
    Kommentar: Ein ChildRef MIT ``nachziehen`` sagt „das Kind gehört dem
    Eltern-Datensatz", einer OHNE sagt „es erwähnt ihn nur und muss ihn überleben".
    Genau diese beiden Aussagen braucht der Bericht — sie hier noch einmal zu pflegen,
    hieße dieselbe Entscheidung an zwei Orten zu treffen.

    Der Registry-Inhalt steht zur Importzeit fest, deshalb einmal berechnet.
    """
    from app.services.prune_service import PRUNE_REGISTRY
    verweise: dict = {}
    for e in PRUNE_REGISTRY:
        for c in e.children:
            eltern, bisher = verweise.get((c.table, c.fk), (e.table, False))
            # Ein einziges `nachziehen` genügt: Dann räumt der Prune die Zeile weg.
            verweise[(c.table, c.fk)] = (eltern, bisher or c.nachziehen)
    return verweise


def kategorie(child_table: str, child_column: str) -> tuple[str, str]:
    """(Kategorie, Begründung) für eine Beziehung.

    „offen" heißt damit wörtlich: Diese Beziehung kennt das PRUNE_REGISTRY nicht. Jemand
    hat eine Tabelle oder Spalte angelegt und nicht entschieden, ob das Kind seinem
    Eltern-Datensatz gehört. Das ist die einzige Kategorie, die jemanden erfordert.
    """
    grund = GEWOLLTE_VERWEISE.get((child_table, child_column))
    if grund:
        return KAT_GEWOLLT, grund
    eintrag = _registry_verweise().get((child_table, child_column))
    if eintrag is None:
        return KAT_OFFEN, ""
    eltern, nachziehen = eintrag
    if nachziehen:
        return KAT_NACHZUG, ('Wird vom Prune nachgezogen, sobald der gelöschte '
                             f'{eltern}-Datensatz nur noch daran hängt.')
    return KAT_GEWOLLT, (f'Das PRUNE_REGISTRY führt die Beziehung unter „{eltern}" '
                         'ohne Nachzug: Das Kind erwähnt den Eltern-Datensatz nur und '
                         'überlebt ihn bewusst.')


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


def build_reparatur_verwaiste_rechte_sql() -> tuple[str, list]:
    """Einmalige Altlast-Bereinigung: soft-löscht aktive ``user_permissions``, deren User
    bereits soft-gelöscht ist.

    Entspricht exakt dem heutigen Verhalten beim Benutzer-Löschen
    (``revoke_all_permissions_for_user``), nur nachgezogen für User, die vor dieser Logik
    gelöscht wurden. Idempotent: ein zweiter Lauf findet nichts mehr. Zwei Platzhalter für
    den Akteur (``deleted_by`` + ``updated_by``).
    """
    sql = (
        "UPDATE user_permissions up "
        "SET deleted_at = now(), deleted_by = %s, "
        "    updated_at = now(), updated_by = %s, version = version + 1 "
        f"WHERE {_child_aktiv('up')} "
        "  AND EXISTS (SELECT 1 FROM users u "
        f"             WHERE u.id = up.user_id AND {_parent_geloescht('u')})"
    )
    return sql, []


class KonsistenzService:
    """Orchestriert den generischen Konsistenz-Scan (read-only) plus gezielte,
    einmalige Altlast-Reparaturen."""

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
        summe_offen = 0

        for fk in fks:
            cnt_sql, cnt_params = build_verletzung_count_sql(fk)
            row = self._fetchone(cnt_sql, cnt_params)
            anzahl = int(row["n"]) if row else 0
            if anzahl == 0:
                continue

            s_sql, s_params = build_verletzung_sample_sql(fk, sample_limit)
            beispiele = [r["parent_id"] for r in self._fetchall(s_sql, s_params)]

            kat, grund = kategorie(fk.child_table, fk.child_column)
            summe += anzahl
            if kat == KAT_OFFEN:
                summe_offen += anzahl
            befunde.append({
                "constraint": fk.constraint,
                "child_table": fk.child_table,
                "child_column": fk.child_column,
                "parent_table": fk.parent_table,
                "parent_column": fk.parent_column,
                "verletzungen": anzahl,
                "beispiel_parent_ids": beispiele,
                "kategorie": kat,
                "begruendung": grund,
            })

        # Auffälligste Befunde zuerst – aber die offenen immer vor den eingeordneten,
        # sonst versteckt sich der eine echte Fund hinter hundert erwarteten Zeilen.
        befunde.sort(key=lambda b: (b["kategorie"] != KAT_OFFEN, -b["verletzungen"]))

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "geprueft": len(fks),
            "befunde": befunde,
            "summe_verletzungen": summe,
            # Die Zahl, auf die es ankommt: alles, was NICHT eingeordnet ist.
            "summe_offen": summe_offen,
            "alles_konsistent": summe_offen == 0,
        }

    # --- Gezielte, einmalige Altlast-Reparaturen ----------------------------------
    def repariere_verwaiste_rechte(self, actor: str) -> dict:
        """Bereinigt die Rechte bereits gelöschter Benutzer (Altlast). Idempotent.

        Bewusst KEIN generisches „alle hängenden Kinder löschen": die meisten Befunde
        (Kontakte, Tickets, Audit-Verweise) sollen ausdrücklich bestehen bleiben.
        """
        sql, params = build_reparatur_verwaiste_rechte_sql()
        with self._db.cursor() as cur:
            cur.execute(sql, tuple([actor, actor] + params))
            return {"bereinigt": cur.rowcount}
