'''
Kassenbuchung Repository – Datenbankoperationen für Kassenbuchungen.

@author: AI Assistant
'''

import sqlite3
from app.models.kasse import Kassenbuchung
from app.db.base_repository import BaseRepository


class KassenbuchungRepository(BaseRepository):
    """Repository für Kassenbuchungen.

    Handles:
    - Create, Read, Update (Belegnummer ist read-only nach Erstellen)
    - Soft-Delete (stornieren)
    - History-Abfrage für UI-Einblendung
    - Laufenden Bestand per SQL berechnen
    - History via DB-Trigger
    """

    # -----------------------------------
    # Read-Operationen
    # -----------------------------------

    def get_kassenbuchung(self, buchung_id: int) -> Kassenbuchung:
        """Gibt eine Buchung zurück (auch stornierte). KeyError wenn nicht vorhanden."""
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT id, kasse_id, buchungsdatum, belegnummer, buchungstext,
                       kategorie, einnahme_cent, ausgabe_cent, notiz,
                       exportiert_in_export_id,
                       version, created_at, created_by, updated_at, updated_by,
                       deleted_at, deleted_by
                FROM kassenbuchungen
                WHERE id = ?
                """,
                (buchung_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise KeyError(f"Kassenbuchung {buchung_id} nicht gefunden")
            return Kassenbuchung(**dict(row))

    def list_kassenbuchungen(
        self,
        kasse_id: int,
        von_datum: str | None = None,
        bis_datum: str | None = None,
        include_storniert: bool = False,
    ) -> list[Kassenbuchung]:
        """Listet Buchungen einer Kasse, optional gefiltert nach Zeitraum.

        Args:
            include_storniert: Wenn True, werden auch soft-deleted Buchungen zurückgegeben.
        """
        conditions = ["kasse_id = ?"]
        params: list = [kasse_id]

        if not include_storniert:
            conditions.append("deleted_at IS NULL")
        if von_datum:
            conditions.append("buchungsdatum >= ?")
            params.append(von_datum)
        if bis_datum:
            conditions.append("buchungsdatum <= ?")
            params.append(bis_datum)

        where = " AND ".join(conditions)

        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, kasse_id, buchungsdatum, belegnummer, buchungstext,
                       kategorie, einnahme_cent, ausgabe_cent, notiz,
                       exportiert_in_export_id,
                       version, created_at, created_by, updated_at, updated_by,
                       deleted_at, deleted_by
                FROM kassenbuchungen
                WHERE {where}
                ORDER BY buchungsdatum ASC, id ASC
                """,
                params,
            )
            return [Kassenbuchung(**dict(row)) for row in cur.fetchall()]

    def get_history(self, buchung_id: int) -> list[dict]:
        """Gibt alle History-Einträge einer Buchung zurück (für UI-Einblendung).

        Lazy laden: Nur aufrufen wenn der Nutzer den History-Expander öffnet.
        """
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT id, version, kasse_id, buchungsdatum, belegnummer, buchungstext,
                       kategorie, einnahme_cent, ausgabe_cent, notiz,
                       exportiert_in_export_id,
                       created_at, created_by, updated_at, updated_by,
                       deleted_at, deleted_by
                FROM kassenbuchungen_history
                WHERE id = ?
                ORDER BY version ASC
                """,
                (buchung_id,),
            )
            return [dict(row) for row in cur.fetchall()]

    def get_naechste_belegnummer(self, kasse_id: int) -> str:
        """Ermittelt die nächste Belegnummer für eine Kasse.

        Format: Einfache laufende Ganzzahl als String (z.B. '1', '2', '42').
        Lücken durch stornierte Buchungen werden NICHT wiederverwendet.
        """
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT MAX(CAST(belegnummer AS INTEGER))
                FROM kassenbuchungen
                WHERE kasse_id = ?
                """,
                (kasse_id,),
            )
            row = cur.fetchone()
            letzte_nr = row[0] if row and row[0] is not None else 0
            return str(letzte_nr + 1)

    # -----------------------------------
    # Write-Operationen
    # -----------------------------------

    def create_kassenbuchung(self, buchung: Kassenbuchung, created_by: str) -> Kassenbuchung:
        """Erstellt eine neue Buchung. Belegnummer muss bereits gesetzt sein. History via Trigger."""
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO kassenbuchungen (
                    kasse_id, buchungsdatum, belegnummer, buchungstext,
                    kategorie, einnahme_cent, ausgabe_cent, notiz,
                    created_by, updated_at, updated_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
                """,
                (
                    buchung.kasse_id, buchung.buchungsdatum, buchung.belegnummer,
                    buchung.buchungstext, buchung.kategorie,
                    buchung.einnahme_cent, buchung.ausgabe_cent,
                    buchung.notiz, created_by, created_by,
                ),
            )
            buchung_id = cur.lastrowid
            cur.execute(
                """
                SELECT id, kasse_id, buchungsdatum, belegnummer, buchungstext,
                       kategorie, einnahme_cent, ausgabe_cent, notiz,
                       exportiert_in_export_id,
                       version, created_at, created_by, updated_at, updated_by,
                       deleted_at, deleted_by
                FROM kassenbuchungen WHERE id = ?
                """,
                (buchung_id,),
            )
            return Kassenbuchung(**dict(cur.fetchone()))

    def update_kassenbuchung(self, buchung: Kassenbuchung, updated_by: str) -> bool:
        """Aktualisiert eine Buchung (Optimistic Locking). Belegnummer wird NICHT geändert.

        Hinweis: Prüfung auf Export-Sperre ist Aufgabe des Service-Layers.

        Returns:
            True wenn erfolgreich, False bei Version-Konflikt oder nicht gefunden.
        """
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE kassenbuchungen
                SET buchungsdatum = ?, buchungstext = ?, kategorie = ?,
                    einnahme_cent = ?, ausgabe_cent = ?, notiz = ?,
                    version = version + 1,
                    updated_at = CURRENT_TIMESTAMP,
                    updated_by = ?
                WHERE id = ? AND version = ? AND deleted_at IS NULL
                """,
                (
                    buchung.buchungsdatum, buchung.buchungstext, buchung.kategorie,
                    buchung.einnahme_cent, buchung.ausgabe_cent, buchung.notiz,
                    updated_by, buchung.id, buchung.version,
                ),
            )
            if cur.rowcount == 0:
                return False
            cur.execute("SELECT version, updated_at FROM kassenbuchungen WHERE id = ?", (buchung.id,))
            row = dict(cur.fetchone())
            buchung.version = row["version"]
            buchung.updated_at = row["updated_at"]
            buchung.updated_by = updated_by
            return True

    def mark_kassenbuchung_deleted(self, buchung_id: int, deleted_by: str) -> bool:
        """Soft-Delete (Stornierung) einer Buchung. History via Trigger.

        Hinweis: Prüfung auf Export-Sperre ist Aufgabe des Service-Layers.

        Returns:
            True wenn storniert, False wenn nicht gefunden oder bereits storniert.
        """
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE kassenbuchungen
                SET deleted_at = CURRENT_TIMESTAMP,
                    deleted_by = ?,
                    version = version + 1
                WHERE id = ? AND deleted_at IS NULL
                """,
                (deleted_by, buchung_id),
            )
            return cur.rowcount == 1

    def mark_buchungen_exportiert(
        self, buchung_ids: list[int], export_id: int
    ) -> int:
        """Setzt exportiert_in_export_id für eine Liste von Buchungs-IDs.

        Returns:
            Anzahl tatsächlich gesperrter Buchungen.
        """
        if not buchung_ids:
            return 0
        placeholders = ",".join("?" * len(buchung_ids))
        with self.cursor() as cur:
            cur.execute(
                f"""
                UPDATE kassenbuchungen
                SET exportiert_in_export_id = ?,
                    version = version + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id IN ({placeholders})
                  AND exportiert_in_export_id IS NULL
                  AND deleted_at IS NULL
                """,
                [export_id] + buchung_ids,
            )
            return cur.rowcount

    # -----------------------------------
    # Future: Prune Operations
    # -----------------------------------

    def prune_stornierte_buchungen(self, days_old: int) -> int:
        """Hard-Delete stornierter Buchungen älter als days_old Tage.

        TODO: Implementieren wenn benötigt.

        Returns:
            Anzahl physisch gelöschter Datensätze.
        """
        raise NotImplementedError("Prune-Operationen werden später implementiert")
