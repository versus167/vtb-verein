'''
Kasse Repository – Datenbankoperationen für Kassen.

@author: AI Assistant
'''

from psycopg import Connection as PgConnection
from app.models.kasse import Kasse
from app.db.base_repository import BaseRepository


class KasseRepository(BaseRepository):
    """Repository für Kassen-CRUD und Bestandsberechnung.

    Handles:
    - Create, Read, Update
    - Soft-Delete
    - Bestandsberechnung direkt per SQL (kein Python-Loop)
    - History via DB-Trigger
    """

    def get_kasse(self, kasse_id: int) -> Kasse:
        """Gibt eine aktive Kasse zurück. KeyError wenn nicht gefunden."""
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, beschreibung, anfangsbestand_cent, abteilung_id,
                       version, created_at, created_by, updated_at, updated_by
                FROM kassen
                WHERE id = %s AND deleted_at IS NULL
                """,
                (kasse_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise KeyError(f"Kasse {kasse_id} nicht gefunden")
            return Kasse(**dict(row))

    def list_kassen(self) -> list[Kasse]:
        """Alle aktiven Kassen, alphabetisch sortiert."""
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, beschreibung, anfangsbestand_cent, abteilung_id,
                       version, created_at, created_by, updated_at, updated_by
                FROM kassen
                WHERE deleted_at IS NULL
                ORDER BY name
                """
            )
            return [Kasse(**dict(row)) for row in cur.fetchall()]

    def create_kasse(self, kasse: Kasse, created_by: str) -> Kasse:
        """Erstellt eine neue Kasse. History via Trigger."""
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO kassen (name, beschreibung, anfangsbestand_cent, abteilung_id,
                                    created_by, updated_at, updated_by)
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP, %s)
                RETURNING id
                """,
                (kasse.name, kasse.beschreibung, kasse.anfangsbestand_cent,
                 kasse.abteilung_id, created_by, created_by),
            )
            kasse_id = cur.fetchone()['id']
            cur.execute(
                """
                SELECT id, name, beschreibung, anfangsbestand_cent, abteilung_id,
                       version, created_at, created_by, updated_at, updated_by
                FROM kassen WHERE id = %s
                """,
                (kasse_id,),
            )
            return Kasse(**dict(cur.fetchone()))

    def update_kasse(self, kasse: Kasse, updated_by: str) -> bool:
        """Aktualisiert eine Kasse (Optimistic Locking via version). History via Trigger.

        Returns:
            True wenn erfolgreich, False bei Version-Konflikt oder nicht gefunden.
        """
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE kassen
                SET name = %s, beschreibung = %s, anfangsbestand_cent = %s, abteilung_id = %s,
                    version = version + 1,
                    updated_at = CURRENT_TIMESTAMP,
                    updated_by = %s
                WHERE id = %s AND version = %s AND deleted_at IS NULL
                """,
                (kasse.name, kasse.beschreibung, kasse.anfangsbestand_cent,
                 kasse.abteilung_id, updated_by, kasse.id, kasse.version),
            )
            if cur.rowcount == 0:
                return False
            cur.execute("SELECT version, updated_at FROM kassen WHERE id = %s", (kasse.id,))
            row = dict(cur.fetchone())
            kasse.version = row["version"]
            kasse.updated_at = row["updated_at"]
            kasse.updated_by = updated_by
            return True

    def mark_kasse_deleted(self, kasse_id: int, deleted_by: str) -> bool:
        """Soft-Delete einer Kasse. History via Trigger.

        Hinweis: Prüfung auf aktive Buchungen ist Aufgabe des Service-Layers.

        Returns:
            True wenn gelöscht, False wenn nicht gefunden oder bereits gelöscht.
        """
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE kassen
                SET deleted_at = CURRENT_TIMESTAMP,
                    deleted_by = %s,
                    version = version + 1
                WHERE id = %s AND deleted_at IS NULL
                """,
                (deleted_by, kasse_id),
            )
            return cur.rowcount == 1

    # -----------------------------------
    # Bestandsberechnung
    # -----------------------------------

    def get_bestand_cent(self, kasse_id: int) -> int:
        """Berechnet den aktuellen Kassenbestand in Cent per SQL.

        Anfangsbestand + Summe aller aktiven Einnahmen - Summe aller aktiven Ausgaben.
        Stornierte (deleted_at IS NOT NULL) und exportierte Buchungen fließen ein,
        solange sie nicht storniert sind.
        """
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT k.anfangsbestand_cent
                     + COALESCE(SUM(b.einnahme_cent), 0)
                     - COALESCE(SUM(b.ausgabe_cent), 0) AS bestand_cent
                FROM kassen k
                LEFT JOIN kassenbuchungen b
                       ON b.kasse_id = k.id
                      AND b.deleted_at IS NULL
                WHERE k.id = %s AND k.deleted_at IS NULL
                """,
                (kasse_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise KeyError(f"Kasse {kasse_id} nicht gefunden")
            return row['bestand_cent'] or 0

    def get_bestand_zum_datum_cent(self, kasse_id: int, bis_datum: str) -> int:
        """Berechnet den Kassenbestand bis einschließlich einem bestimmten Datum.

        Nützlich für den PDF-Kassenbericht (Anfangsbestand einer Periode).
        """
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT k.anfangsbestand_cent
                     + COALESCE(SUM(b.einnahme_cent), 0)
                     - COALESCE(SUM(b.ausgabe_cent), 0) AS bestand_cent
                FROM kassen k
                LEFT JOIN kassenbuchungen b
                       ON b.kasse_id = k.id
                      AND b.deleted_at IS NULL
                      AND b.buchungsdatum <= %s
                WHERE k.id = %s AND k.deleted_at IS NULL
                """,
                (bis_datum, kasse_id),
            )
            row = cur.fetchone()
            if row is None:
                raise KeyError(f"Kasse {kasse_id} nicht gefunden")
            return row['bestand_cent'] or 0

    # -----------------------------------
    # Future: Prune Operations
    # -----------------------------------

    def prune_deleted_kassen(self, days_old: int) -> int:
        """Hard-Delete von Kassen die seit >days_old Tagen soft-deleted sind.

        TODO: Implementieren wenn benötigt. Vorher auf aktive Buchungen prüfen.

        Returns:
            Anzahl physisch gelöschter Datensätze.
        """
        raise NotImplementedError("Prune-Operationen werden später implementiert")
