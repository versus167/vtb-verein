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

# Zugriffsprotokoll-Seitenaufrufe: KEIN Soft-Delete-Eintrag, sondern eigene Retention –
# Hard-Delete nach created_at-Alter, nur category 'page' (auth/prune bleiben dauerhaft).
# Als Sonder-Bereich in Report/Prune geführt, damit es auf der Bereinigungs-Seite sichtbar
# und einstellbar ist (Schlüssel auch in der Override-Tabelle prune_einstellungen nutzbar).
ACCESS_LOG_PAGE = "access_log_page"
DEFAULT_PAGE_VIEW_RETENTION_DAYS = 90


@dataclass(frozen=True)
class ChildRef:
    """Eine Live-Tabelle, die auf die Eltern-Tabelle zeigt.

    Standard: ``child.fk == parent.id`` (echte FK). Manche Bezüge laufen aber NICHT über
    die id, sondern über eine andere Eltern-Spalte (z.B. mitglied_funktion.funktion ==
    funktion.key, lose ohne FK) – dafür ``parent_col`` setzen.
    """
    table: str
    fk: str
    parent_col: str = "id"


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
    # Spalte mit dem Datei-Namen auf der Platte (Anhänge); gesetzt -> beim Prune wird
    # die Datei via AnhangService zusätzlich gelöscht. Domänen-unabhängiger Storage-Layer.
    stored_name_col: Optional[str] = None
    retention_days: int = DEFAULT_RETENTION_DAYS
    keep_min: int = DEFAULT_KEEP_MIN
    history_retention_days: int = DEFAULT_HISTORY_RETENTION_DAYS


# Reihenfolge: Blatt → Wurzel. So sind beim echten Lauf die Kinder schon weg, bevor
# das Eltern-Element drankommt. History wird je Entität separat (und vorgelagert) geprunt.
#
# Abgedeckte Domänen: Anhänge (mit Disk-Datei), Mitglied, Tickets, Stammdaten,
# Schließanlage/Zutritt und Übungsleiter-Abrechnung.
# BEWUSST NICHT drin: Finanzdaten (Kassen/Buchungen/Beiträge/Gebühren –
# Aufbewahrungspflicht) und users (Auth-/Audit-verflochten, Last-Admin-Schutz).
# Ebenfalls NICHT drin: geräte-gebundene Tabellen mit revoked_at statt deleted_at
# (user_sessions, push_subscriptions) – sie haben eigene zeitbasierte Cleanups
# (cleanup_expired / cleanup_revoked) analog access_log, kein deleted_at-Prune.
# Vollständigkeit der Child-Refs wird per Schema-Drift-Test (test_prune_integration.py)
# gegen die echten FKs abgesichert – neue FK auf eine geprunte Tabelle -> Test rot.
#
# Child-Refs listen ALLE eingehenden FKs (auch aus nicht-geprunten Tabellen) – fehlt
# einer, würde der DB-FK (RESTRICT) das echte Löschen blockieren. Anhänge sind reine
# Blätter ohne History/Version; stored_name_col aktiviert das Datei-Löschen.
PRUNE_REGISTRY: tuple[PruneEntity, ...] = (
    # --- Anhänge (Blätter mit Disk-Datei) ---
    PruneEntity("ticket_anhang", "Ticket-Anhänge", "ticket_anhaenge",
                stored_name_col="stored_name"),
    PruneEntity("kassenbuchung_anhang", "Kassen-Anhänge", "kassenbuchung_anhaenge",
                stored_name_col="stored_name"),
    # --- Schließanlage / Zutritt (Blatt → Wurzel) ---
    # Steht VOR mitglied/abteilung: schluessel_chip hängt an mitglied, tuer_schloss an
    # abteilung. tuer_zutritt_log, tuer_credential, tuer_schloss_status_log sind KEINE
    # Prune-Entitäten (Dauerprotokolle/kein Soft-Delete) – tauchen nur als Child-Guards auf.
    PruneEntity("tuer_app_berechtigung", "App-Türberechtigungen", "tuer_app_berechtigung",
                history_table="tuer_app_berechtigung_history"),
    PruneEntity("tuer_berechtigung", "Chip-Türberechtigungen", "tuer_berechtigung",
                history_table="tuer_berechtigung_history"),
    PruneEntity("tuer_schloss", "Schlösser", "tuer_schloss",
                history_table="tuer_schloss_history",
                children=(
                    ChildRef("tuer_app_berechtigung", "schloss_id"),
                    ChildRef("tuer_berechtigung", "schloss_id"),
                    ChildRef("tuer_credential", "schloss_id"),
                    ChildRef("tuer_schloss_status_log", "schloss_id"),
                    ChildRef("tuer_zutritt_log", "schloss_id"),
                )),
    PruneEntity("schluessel_chip", "Schlüssel-Chips", "schluessel_chip",
                history_table="schluessel_chip_history",
                children=(
                    ChildRef("tuer_berechtigung", "chip_id"),
                    ChildRef("tuer_zutritt_log", "chip_id"),
                )),
    # --- Übungsleiter-Abrechnung (Blatt → Wurzel) ---
    PruneEntity("ul_stunde", "ÜL-Stunden", "ul_stunde",
                history_table="ul_stunde_history"),
    PruneEntity("ul_abrechnung", "ÜL-Abrechnungen", "ul_abrechnung",
                history_table="ul_abrechnung_history",
                children=(ChildRef("ul_stunde", "abrechnung_id"),)),
    PruneEntity("ul_satz", "ÜL-Sätze", "ul_satz",
                history_table="ul_satz_history"),
    # --- Passwort-Tresor (Blatt → Wurzel) ---
    # tresor_zugriff_log ist append-only (kein Soft-Delete, keine FK auf tresor/-eintrag)
    # und daher KEINE Prune-Entität – es taucht auch nicht als Child-Guard auf.
    PruneEntity("tresor_eintrag", "Tresor-Einträge", "tresor_eintrag",
                history_table="tresor_eintrag_history"),
    PruneEntity("tresor_freigabe", "Tresor-Freigaben", "tresor_freigabe",
                history_table="tresor_freigabe_history"),
    PruneEntity("tresor", "Passwort-Tresore", "tresor",
                history_table="tresor_history",
                children=(
                    ChildRef("tresor_eintrag", "tresor_id"),
                    ChildRef("tresor_freigabe", "tresor_id"),
                )),
    # --- Spielbetrieb: Mannschafts-Termine (#95, Blatt vor mannschaft) ---
    PruneEntity("termin_zusage", "Termin-Zusagen", "termin_zusage",
                history_table="termin_zusage_history"),
    PruneEntity("termin", "Termine", "termine",
                history_table="termine_history",
                children=(ChildRef("termin_zusage", "termin_id"),)),
    PruneEntity("termin_serie", "Terminserien", "termin_serie",
                history_table="termin_serie_history",
                children=(ChildRef("termine", "serie_id"),)),
    # --- Mitglied-Domäne (Blatt → Wurzel) ---
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
                children=(
                    ChildRef("mitglied_mannschaft", "mannschaft_id"),
                    ChildRef("termin_serie", "mannschaft_id"),
                    ChildRef("termine", "mannschaft_id"),
                )),
    PruneEntity("mitglied", "Mitglieder", "mitglied",
                history_table="mitglied_history",
                children=(
                    ChildRef("beitrag_sollstellung", "mitglied_id"),
                    ChildRef("gebuehr_forderung", "mitglied_id"),
                    ChildRef("mitglied_abteilung", "mitglied_id"),
                    ChildRef("mitglied_funktion", "mitglied_id"),
                    ChildRef("mitglied_kontakt", "mitglied_id"),
                    ChildRef("mitglied_mannschaft", "mitglied_id"),
                    ChildRef("schluessel_chip", "mitglied_id"),
                    ChildRef("termin_zusage", "mitglied_id"),
                    ChildRef("tuer_zutritt_log", "mitglied_id"),   # Dauerprotokoll: nie soft-deleted
                    ChildRef("ul_abrechnung", "mitglied_id"),
                    ChildRef("ul_satz", "mitglied_id"),
                )),
    # --- Tickets-Domäne (Blatt → Wurzel) ---
    PruneEntity("ticket_teilnehmer", "Ticket-Teilnehmer", "ticket_teilnehmer",
                history_table="ticket_teilnehmer_history"),
    PruneEntity("ticket_bereich_berechtigung", "Ticket-Bereichsrechte",
                "ticket_bereich_berechtigungen",
                history_table="ticket_bereich_berechtigungen_history"),
    PruneEntity("ticket_kommentar", "Ticket-Kommentare", "ticket_kommentare",
                history_table="ticket_kommentare_history",
                children=(ChildRef("ticket_anhaenge", "kommentar_id"),)),
    PruneEntity("ticket", "Tickets", "tickets",
                history_table="tickets_history",
                children=(
                    ChildRef("ticket_kommentare", "ticket_id"),
                    ChildRef("ticket_anhaenge", "ticket_id"),
                    ChildRef("ticket_teilnehmer", "ticket_id"),
                )),
    PruneEntity("ticket_kategorie", "Ticket-Kategorien", "ticket_kategorien",
                history_table="ticket_kategorien_history",
                children=(ChildRef("tickets", "kategorie_id"),)),
    PruneEntity("ticket_bereich", "Ticket-Bereiche", "ticket_bereiche",
                history_table="ticket_bereiche_history",
                children=(
                    ChildRef("tickets", "bereich_id"),
                    ChildRef("ticket_bereich_berechtigungen", "bereich_id"),
                )),
    # --- Stammdaten (Blatt → Wurzel) ---
    PruneEntity("funktion_permission", "Funktionsrechte", "funktion_permission",
                history_table="funktion_permission_history"),
    PruneEntity("funktion", "Funktionen", "funktion",
                history_table="funktion_history",
                children=(
                    ChildRef("funktion_permission", "funktion_id"),       # FK auf funktion.id
                    ChildRef("mitglied_funktion", "funktion", parent_col="key"),  # lose über key
                )),
    PruneEntity("abteilung", "Abteilungen", "abteilung",
                history_table="abteilung_history",
                children=(
                    ChildRef("mitglied_abteilung", "abteilung_id"),
                    ChildRef("mitglied_funktion", "abteilung_id"),
                    ChildRef("mannschaft", "abteilung_id"),
                    ChildRef("beitragsregel", "abteilung_id"),
                    ChildRef("beitragsregel", "ausnahme_funktion_abteilung_id"),
                    ChildRef("beitragsregel", "bedingung_funktion_abteilung_id"),
                    ChildRef("gebuehr", "abteilung_id"),
                    ChildRef("kassen", "abteilung_id"),
                    ChildRef("user_permissions", "abteilung_id"),
                    ChildRef("tuer_schloss", "abteilung_id"),
                    ChildRef("ul_abrechnung", "abteilung_id"),
                    ChildRef("ul_satz", "abteilung_id"),
                )),
)


# --- Reine SQL-Bausteine (ohne DB testbar) ----------------------------------------
# Hilfsausdruck: deleted_at/created_at-Spalten sind teils TEXT (ISO-Strings), teils
# TIMESTAMP. Erst nach ::text casten – dann ist NULLIF(...,'') für beide Typen gültig
# (bei TIMESTAMP gäbe der direkte Vergleich mit '' einen Cast-Fehler) – und zurück nach
# timestamptz. Leere Strings (TEXT) werden zu NULL.
def _ts(col: str) -> str:
    return f"NULLIF({col}::text, '')::timestamptz"


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
        f"WHERE deleted_at IS NOT NULL AND deleted_at::text <> ''"
    )
    return sql, []


def build_active_count_sql(entity: PruneEntity) -> tuple[str, list]:
    """Zahl der aktiven (nicht gelöschten) Einträge – reines Mengengefühl, wird nie geprunt."""
    sql = (
        f"SELECT COUNT(*) AS n FROM {entity.table} "
        f"WHERE deleted_at IS NULL OR deleted_at::text = ''"
    )
    return sql, []


def build_original_candidate_ids_sql(
    entity: PruneEntity,
    retention_days: int,
    keep_min: int,
    history_retention_days: int,
) -> tuple[str, list]:
    """SELECT der IDs aller endgültig löschbaren Original-Datensätze (alle 5 Tore).

    Einzige Quelle der Tor-Logik – COUNT (Report) und DELETE (Prune) bauen beide darauf
    auf, damit „Vorschau = Aktion" garantiert ist. Tunables werden explizit übergeben.
    """
    params: list = []
    where = [
        f"r.del < now() - make_interval(days => %s)",   # Tor 2: Datum
        "r.rn > %s",                                      # Tor 3: Mindestanzahl
    ]
    params.append(retention_days)
    params.append(keep_min)

    for child in entity.children:                         # Tor 4: keine Kind-Referenz
        if child.parent_col == "id":
            cond = "c.{fk} = r.id".format(fk=child.fk)
        else:                                             # Bezug über andere Eltern-Spalte
            cond = (
                f"c.{child.fk} = (SELECT p.{child.parent_col} "
                f"FROM {entity.table} p WHERE p.id = r.id)"
            )
        where.append(f"NOT EXISTS (SELECT 1 FROM {child.table} c WHERE {cond})")

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
        "   WHERE deleted_at IS NOT NULL AND deleted_at::text <> '' "
        ") "
        "SELECT r.id FROM ranked r WHERE " + " AND ".join(where)
    )
    return sql, params


def build_original_candidate_count_sql(
    entity: PruneEntity,
    retention_days: int,
    keep_min: int,
    history_retention_days: int,
) -> tuple[str, list]:
    """Zahl der endgültig löschbaren Original-Datensätze (zählt das ID-SELECT)."""
    ids_sql, params = build_original_candidate_ids_sql(
        entity, retention_days, keep_min, history_retention_days
    )
    return f"SELECT COUNT(*) AS n FROM ({ids_sql}) c", params


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


def build_history_prune_delete_sql(entity: PruneEntity) -> tuple[str, list]:
    """DELETE der abgeflossenen History-Zeilen – gleiche WHERE-Logik wie der Zähler."""
    assert entity.history_table is not None
    sql = (
        f"DELETE FROM {entity.history_table} "
        f"WHERE {_history_effective_ts()} < now() - make_interval(days => %s)"
    )
    return sql, []  # history_retention_days wird vom Service als Param ergänzt


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

    def page_view_retention(self) -> tuple[int, bool]:
        """Aufbewahrung der Protokoll-Seitenaufrufe in Tagen + ob ein Override gesetzt ist."""
        o = self._db.prune_einstellungen.get_all().get(ACCESS_LOG_PAGE)
        if o:
            return o["retention_days"], True
        return DEFAULT_PAGE_VIEW_RETENTION_DAYS, False

    def _access_log_report_row(self) -> dict:
        """Sonder-Bereich „Seitenaufrufe (Protokoll)": Hard-Delete nach Alter, kein Soft-Delete."""
        days, is_override = self.page_view_retention()
        return {
            "name": ACCESS_LOG_PAGE,
            "label": "Seitenaufrufe (Protokoll)",
            "table": "access_log",
            "soft_delete": False,            # kein Papierkorb/keep_min/History
            "retention_days": days,
            "keep_min": None,
            "history_retention_days": None,
            "is_override": is_override,
            "eintraege": self._db.access_log_repository.count(category="page"),
            "im_papierkorb": None,
            "loeschbar": self._db.access_log_repository.count_page_views_older_than(days),
            "history_table": None,
            "history_gesamt": None,
            "history_loeschbar": None,
        }

    def einstellungen(self) -> list[dict]:
        """Konfigurations-Sicht für die Admin-UI: Struktur + wirksame Tunables je Entität."""
        cfg = self.effective_config()
        rows = [
            {
                "name": e.name,
                "label": e.label,
                "table": e.table,
                "history_table": e.history_table,
                "soft_delete": True,
                **cfg[e.name],
            }
            for e in PRUNE_REGISTRY
        ]
        rows.append(self._access_log_report_row())
        return rows

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
            akt_sql, akt_params = build_active_count_sql(entity)
            eintraege = self._count(akt_sql, akt_params)

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
                "soft_delete": True,
                "retention_days": c["retention_days"],
                "keep_min": c["keep_min"],
                "history_retention_days": c["history_retention_days"],
                "is_override": c["is_override"],
                "eintraege": eintraege,
                "im_papierkorb": im_papierkorb,
                "loeschbar": loeschbar,
                "history_table": entity.history_table,
                "history_gesamt": history_gesamt,
                "history_loeschbar": history_loeschbar,
            })

        # Sonder-Bereich: Protokoll-Seitenaufrufe (Hard-Delete nach Alter)
        protokoll = self._access_log_report_row()
        summe_loeschbar += protokoll["loeschbar"]
        entities.append(protokoll)

        return {
            "dry_run": True,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "entities": entities,
            "summe_loeschbar": summe_loeschbar,
            "summe_history_loeschbar": summe_history,
            "summe_history_gesamt": summe_history_gesamt,
        }

    def prune(self, dry_run: bool = True) -> dict:
        """Führt die Bereinigung aus (oder zeigt sie als Dry-Run).

        ``dry_run=True`` liefert exakt den ``report()``. Bei ``dry_run=False`` wird in EINER
        Transaktion gelöscht – atomar, bei Fehler vollständiger Rollback. Reihenfolge:

          1. History zuerst (datums-only) – ändert keine der Original-Tore (Tor 5 prüft nur
             Zeilen NEUER als der History-Cutoff, die hier nicht angefasst werden).
          2. Kandidaten-IDs je Entität einmalig einsammeln (= Snapshot, = Report-Zahlen);
             bei Anhang-Entitäten zusätzlich die Datei-Namen der Kandidaten.
          3. Diese IDs Blatt→Wurzel löschen.
          4. NACH dem Commit die zugehörigen Dateien von der Platte entfernen (best-effort):
             eine verwaiste Datei ist der harmlosere Fehlerfall als eine fehlende Datei zu
             einer noch existierenden Zeile.

        Durch das Einsammeln VOR dem Löschen gilt „Vorschau = Aktion": es wird genau das
        entfernt, was der Report zeigte – ein in diesem Lauf kinderlos gewordenes Eltern-
        Element wird NICHT mitgerissen, sondern erst im nächsten Lauf entfernt.
        """
        if dry_run:
            return self.report()

        cfg = self.effective_config()
        entities: list[dict] = []
        summe_loeschbar = 0
        summe_history = 0
        # Datei-Namen je Entität, die nach erfolgreichem Commit von Platte sollen.
        dateien: dict[str, list] = {}

        with self._db.cursor() as cur:
            # 1) History prunen (datums-only)
            history_geloescht: dict[str, int] = {}
            for entity in PRUNE_REGISTRY:
                if entity.history_table:
                    hsql, hparams = build_history_prune_delete_sql(entity)
                    cur.execute(hsql, tuple(hparams + [cfg[entity.name]["history_retention_days"]]))
                    history_geloescht[entity.name] = cur.rowcount

            # 2) Kandidaten-IDs einsammeln (Snapshot vor jeglicher Original-Löschung)
            kandidaten: dict[str, list] = {}
            for entity in PRUNE_REGISTRY:
                c = cfg[entity.name]
                ids_sql, params = build_original_candidate_ids_sql(
                    entity, c["retention_days"], c["keep_min"], c["history_retention_days"]
                )
                cur.execute(ids_sql, tuple(params))
                ids = [row["id"] for row in cur.fetchall()]
                kandidaten[entity.name] = ids
                # Datei-Namen der Kandidaten merken (vor dem Löschen lesbar)
                if entity.stored_name_col and ids:
                    cur.execute(
                        f"SELECT {entity.stored_name_col} AS sn FROM {entity.table} "
                        f"WHERE id = ANY(%s) AND {entity.stored_name_col} IS NOT NULL",
                        (ids,),
                    )
                    dateien[entity.name] = [r["sn"] for r in cur.fetchall()]

            # 3) Originale löschen – Blatt→Wurzel (Registry-Reihenfolge)
            for entity in PRUNE_REGISTRY:
                ids = kandidaten[entity.name]
                geloescht = 0
                if ids:
                    cur.execute(
                        f"DELETE FROM {entity.table} WHERE id = ANY(%s)", (ids,)
                    )
                    geloescht = cur.rowcount
                summe_loeschbar += geloescht
                hist = history_geloescht.get(entity.name)
                if hist is not None:
                    summe_history += hist
                entities.append({
                    "name": entity.name,
                    "label": entity.label,
                    "geloescht": geloescht,
                    "history_geloescht": hist,
                    "dateien_geloescht": 0,  # wird nach Commit gesetzt
                })

        # 4) Dateien NACH dem Commit löschen (best-effort, no-raise im AnhangService).
        summe_dateien = 0
        eintrag_by_name = {e["name"]: e for e in entities}
        for name, namen in dateien.items():
            anzahl = sum(1 for sn in namen if self._db.anhang_service.loesche(sn))
            eintrag_by_name[name]["dateien_geloescht"] = anzahl
            summe_dateien += anzahl

        # 5) Sonder-Bereich: Protokoll-Seitenaufrufe (eigene Transaktion, best-effort).
        page_days, _ = self.page_view_retention()
        page_geloescht = self._db.access_log_repository.cleanup_page_views(page_days)
        summe_loeschbar += page_geloescht
        entities.append({
            "name": ACCESS_LOG_PAGE,
            "label": "Seitenaufrufe (Protokoll)",
            "geloescht": page_geloescht,
            "history_geloescht": None,
            "dateien_geloescht": 0,
        })

        return {
            "dry_run": False,
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "entities": entities,
            "summe_geloescht": summe_loeschbar,
            "summe_history_geloescht": summe_history,
            "summe_dateien_geloescht": summe_dateien,
        }
