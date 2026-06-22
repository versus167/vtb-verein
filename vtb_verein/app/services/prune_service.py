"""
PruneService – endgültiges Entfernen alter, nicht mehr abhängiger Soft-Deletes.

Hintergrund (siehe Soft-Delete-Only-Prinzip): Es wird nie hart gelöscht, weder im
Request-Pfad noch durch Cascades. Stattdessen landen Datensätze im "Papierkorb"
(``deleted_at IS NOT NULL``) und sind über ``restore_*`` wiederherstellbar. Dieser
Service räumt den Papierkorb kontrolliert auf, OHNE die Wiederherstellung auszuhebeln.

Prune-Modell – ein Original-Datensatz ist nur dann endgültig löschbar, wenn ALLE Tore
gelten:
  1. Soft-deleted (``deleted_at`` gesetzt) – aktive Datensätze werden nie angefasst.
  2. Alt genug (Datum): ``deleted_at`` älter als ``retention_days``. Dieses Fenster IST
     die Restore-Garantie.
  3. Mindestanzahl (Anzahl): die ``keep_min`` zuletzt gelöschten Datensätze bleiben pro
     Entität immer erhalten, egal wie alt.
  4. Nicht mehr abhängig: keine Kind-Referenz mehr (aktiv ODER soft-deleted). Die FK-
     Constraints (ohne ON DELETE CASCADE) erzwingen das ohnehin auf DB-Ebene – wir
     prüfen es vorab, damit der Report stimmt und Eltern nicht fälschlich als löschbar
     erscheinen.
  5. History-frei: keine ``*_history``-Zeile mehr vorhanden. History ist die tiefste
     Recovery-/Audit-Schicht und wird ZUERST geprunt (nach eigenem, längerem Fenster);
     erst wenn für einen Datensatz keine History mehr übrig bliebe, darf das Original weg.

Phase 0 (dieser Stand): NUR Dry-Run-Report (``report()``) – es wird NICHTS gelöscht.
Die SQL-Bausteine sind als reine Funktionen ausgelagert und damit ohne DB testbar.
Das echte Löschen (``prune()``) folgt in den nächsten Phasen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# --- Default-Aufbewahrung (später konfigurierbar) ---------------------------------
DEFAULT_RETENTION_DAYS = 90      # Original: Mindest-Verweildauer im Papierkorb
DEFAULT_KEEP_MIN = 10            # Original: so viele zuletzt Gelöschte bleiben immer
DEFAULT_HISTORY_RETENTION_DAYS = 365   # History: eigenes, längeres Fenster


@dataclass(frozen=True)
class ChildRef:
    """Eine Live-Tabelle, die per FK auf die Eltern-Tabelle zeigt."""
    table: str
    fk: str


@dataclass(frozen=True)
class PruneEntity:
    """Deklarative Beschreibung einer prunebaren Entität.

    Struktur (table/history/children) ist fix; retention_days/keep_min/history_retention_days
    sind nur die CODE-DEFAULTS – zur Laufzeit überschreibbar via `prune_einstellungen`.
    """
    name: str                       # technischer Schlüssel
    label: str                      # Anzeigename (DE)
    table: str                      # Live-Tabelle
    history_table: Optional[str] = None
    history_id_col: str = "id"      # Spalte in der History, die auf table.id zeigt
    children: tuple[ChildRef, ...] = field(default_factory=tuple)
    retention_days: int = DEFAULT_RETENTION_DAYS
    keep_min: int = DEFAULT_KEEP_MIN
    history_retention_days: int = DEFAULT_HISTORY_RETENTION_DAYS


# Reihenfolge: Blatt → Wurzel. So sind beim echten Lauf die Kinder schon weg, bevor
# das Eltern-Element drankommt. History wird je Entität separat (und vorgelagert) geprunt.
#
# Phase 0 deckt die Mitglied-Domäne ab. TODO (spätere Phasen): abteilung (entkoppelt von
# beitragsregel/kassen/funktion), users (verflochten mit Auth/Audit + Last-Admin-Schutz).
PRUNE_REGISTRY: tuple[PruneEntity, ...] = (
    PruneEntity("mitglied_kontakt", "Kontaktdaten", "mitglied_kontakt",
                history_table="mitglied_kontakt_history"),
    PruneEntity("mitglied_abteilung", "Abteilungs-Zuordnungen", "mitglied_abteilung",
                history_table="mitglied_abteilung_history"),
    PruneEntity("mitglied_funktion", "Funktions-Zuordnungen", "mitglied_funktion",
                history_table="mitglied_funktion_history"),
    PruneEntity("mitglied_mannschaft", "Mannschafts-Zuordnungen", "mitglied_mannschaft",
                history_table="mitglied_mannschaft_history"),
    PruneEntity("mannschaft", "Mannschaften", "mannschaft",
                history_table="mannschaft_history",
                children=(ChildRef("mitglied_mannschaft", "mannschaft_id"),)),
    PruneEntity("mitglied", "Mitglieder", "mitglied",
                history_table="mitglied_history",
                children=(
                    ChildRef("beitrag_sollstellung", "mitglied_id"),
                    ChildRef("gebuehr_forderung", "mitglied_id"),
                    ChildRef("mitglied_abteilung", "mitglied_id"),
                    ChildRef("mitglied_funktion", "mitglied_id"),
                    ChildRef("mitglied_kontakt", "mitglied_id"),
                    ChildRef("mitglied_mannschaft", "mitglied_id"),
                )),
)


# --- Reine SQL-Bausteine (ohne DB testbar) ----------------------------------------
# Hilfsausdruck: TEXT- wie TIMESTAMP-Spalten robust nach timestamptz casten. Viele
# deleted_at/created_at-Spalten sind TEXT (ISO-Strings); leere Strings -> NULL.
def _ts(col: str) -> str:
    return f"NULLIF({col}, '')::timestamptz"


def _history_effective_ts(prefix: str = "") -> str:
    """Effektiver Zeitstempel einer History-Zeile: Lösch- vor Änderungs- vor Anlagezeit."""
    p = f"{prefix}." if prefix else ""
    return (
        f"COALESCE({_ts(p + 'deleted_at')}, {_ts(p + 'updated_at')}, {_ts(p + 'created_at')})"
    )


def build_papierkorb_count_sql(entity: PruneEntity) -> tuple[str, list]:
    """Gesamtzahl im Papierkorb (soft-deleted) – Kontext für den Report."""
    sql = (
        f"SELECT COUNT(*) AS n FROM {entity.table} "
        f"WHERE deleted_at IS NOT NULL AND deleted_at <> ''"
    )
    return sql, []


def build_original_candidate_count_sql(
    entity: PruneEntity,
    retention_days: int,
    keep_min: int,
    history_retention_days: int,
) -> tuple[str, list]:
    """Zahl der endgültig löschbaren Original-Datensätze (alle 5 Tore).

    Tunables (retention_days/keep_min/history_retention_days) werden explizit übergeben –
    der Aufrufer löst Override-vs-Default vorher auf.
    """
    params: list = []
    where = [
        f"r.del < now() - make_interval(days => %s)",   # Tor 2: Datum
        "r.rn > %s",                                      # Tor 3: Mindestanzahl
    ]
    params.append(retention_days)
    params.append(keep_min)

    for child in entity.children:                         # Tor 4: keine Kind-Referenz
        where.append(
            f"NOT EXISTS (SELECT 1 FROM {child.table} c WHERE c.{child.fk} = r.id)"
        )

    if entity.history_table:                              # Tor 5: history-frei
        where.append(
            f"NOT EXISTS (SELECT 1 FROM {entity.history_table} h "
            f"WHERE h.{entity.history_id_col} = r.id "
            f"AND {_history_effective_ts('h')} >= now() - make_interval(days => %s))"
        )
        params.append(history_retention_days)

    sql = (
        "WITH ranked AS ("
        f"  SELECT id, {_ts('deleted_at')} AS del, "
        f"         ROW_NUMBER() OVER (ORDER BY {_ts('deleted_at')} DESC NULLS LAST, id DESC) AS rn "
        f"  FROM {entity.table} "
        "   WHERE deleted_at IS NOT NULL AND deleted_at <> '' "
        ") "
        "SELECT COUNT(*) AS n FROM ranked r WHERE " + " AND ".join(where)
    )
    return sql, params


def build_history_prune_count_sql(entity: PruneEntity) -> tuple[str, list]:
    """Zahl der History-Zeilen, die das (vorgelagerte) History-Prune entfernen würde.

    Datums-only und ohne Mindestanzahl: die History muss vollständig abfließen können,
    sonst würde das zugehörige Original nie history-frei (Tor 5).
    """
    assert entity.history_table is not None
    sql = (
        f"SELECT COUNT(*) AS n FROM {entity.history_table} "
        f"WHERE {_history_effective_ts()} < now() - make_interval(days => %s)"
    )
    return sql, []  # history_retention_days wird vom Service als Param ergänzt


def build_history_total_count_sql(entity: PruneEntity) -> tuple[str, list]:
    """Gesamtzahl der aktuell vorhandenen History-Zeilen (Kontext für den Report)."""
    assert entity.history_table is not None
    return f"SELECT COUNT(*) AS n FROM {entity.history_table}", []


class PruneService:
    """Orchestriert die Prune-Registry. Phase 0: ausschließlich Dry-Run-Report.

    Tunables (Tage/Anzahl/History-Tage) sind pro Entität einstellbar: gespeicherte
    Overrides (``prune_einstellungen``) überschreiben die Code-Defaults der Registry.
    """

    def __init__(self, db):
        self._db = db

    def _count(self, sql: str, params: list) -> int:
        with self._db.cursor() as cur:
            cur.execute(sql, tuple(params))
            row = cur.fetchone()
            return int(row["n"]) if row else 0

    def effective_config(self) -> dict[str, dict]:
        """Wirksame Tunables je Entität: Override (falls gesetzt) sonst Code-Default."""
        overrides = self._db.prune_einstellungen.get_all()
        result: dict[str, dict] = {}
        for entity in PRUNE_REGISTRY:
            o = overrides.get(entity.name, {})
            result[entity.name] = {
                "retention_days": o.get("retention_days", entity.retention_days),
                "keep_min": o.get("keep_min", entity.keep_min),
                "history_retention_days": o.get(
                    "history_retention_days", entity.history_retention_days
                ),
                "is_override": entity.name in overrides,
            }
        return result

    def einstellungen(self) -> list[dict]:
        """Konfigurations-Sicht für die Admin-UI: Struktur + wirksame Tunables je Entität."""
        cfg = self.effective_config()
        return [
            {
                "name": e.name,
                "label": e.label,
                "table": e.table,
                "history_table": e.history_table,
                **cfg[e.name],
            }
            for e in PRUNE_REGISTRY
        ]

    def report(self) -> dict:
        """Dry-Run: was *würde* ein vollständiger Prune-Lauf entfernen? Löscht NICHTS."""
        cfg = self.effective_config()
        entities: list[dict] = []
        summe_loeschbar = 0
        summe_history = 0
        summe_history_gesamt = 0

        for entity in PRUNE_REGISTRY:
            c = cfg[entity.name]
            pk_sql, pk_params = build_papierkorb_count_sql(entity)
            im_papierkorb = self._count(pk_sql, pk_params)

            cand_sql, cand_params = build_original_candidate_count_sql(
                entity, c["retention_days"], c["keep_min"], c["history_retention_days"]
            )
            loeschbar = self._count(cand_sql, cand_params)

            history_loeschbar: Optional[int] = None
            history_gesamt: Optional[int] = None
            if entity.history_table:
                ht_sql, ht_params = build_history_total_count_sql(entity)
                history_gesamt = self._count(ht_sql, ht_params)
                h_sql, h_params = build_history_prune_count_sql(entity)
                history_loeschbar = self._count(h_sql, h_params + [c["history_retention_days"]])
                summe_history += history_loeschbar
                summe_history_gesamt += history_gesamt

            summe_loeschbar += loeschbar
            entities.append({
                "name": entity.name,
                "label": entity.label,
                "table": entity.table,
                "retention_days": c["retention_days"],
                "keep_min": c["keep_min"],
                "history_retention_days": c["history_retention_days"],
                "is_override": c["is_override"],
                "im_papierkorb": im_papierkorb,
                "loeschbar": loeschbar,
                "history_table": entity.history_table,
                "history_gesamt": history_gesamt,
                "history_loeschbar": history_loeschbar,
            })

        return {
            "dry_run": True,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "entities": entities,
            "summe_loeschbar": summe_loeschbar,
            "summe_history_loeschbar": summe_history,
            "summe_history_gesamt": summe_history_gesamt,
        }
