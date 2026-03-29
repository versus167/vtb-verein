'''
Kassenbuch Export Repository – Datenbankoperationen für Kassenbuch-Exporte.

@author: AI Assistant
'''

import sqlite3
from app.models.kasse import KassenbuchExport
from app.db.base_repository import BaseRepository


class KassenbuchExportRepository(BaseRepository):
    """Repository für Kassenbuch-Exporte.

    Exporte sind unveränderlich nach dem Erstellen (kein Update).
    Soft-Delete ist möglich (z.B. versehentlicher Export), sperrt aber
    die Buchungen NICHT auf – das ist eine bewusste Entscheidung des Service.
    """

    def get_export(self, export_id: int) -> KassenbuchExport:
        """Gibt einen Export zurück. KeyError wenn nicht gefunden."""
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT id, kasse_id, zeitraum_von, zeitraum_bis,
                       exportiert_am, exportiert_von, dateiname, anzahl_buchungen,
                       version, created_at, created_by,
                       deleted_at, deleted_by
                FROM kassenbuch_exporte
                WHERE id = ?
                """,
                (export_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise KeyError(f"KassenbuchExport {export_id} nicht gefunden")
            return KassenbuchExport(**dict(row))

    def list_exporte(self, kasse_id: int) -> list[KassenbuchExport]:
        """Alle aktiven Exporte einer Kasse, neueste zuerst."""
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT id, kasse_id, zeitraum_von, zeitraum_bis,
                       exportiert_am, exportiert_von, dateiname, anzahl_buchungen,
                       version, created_at, created_by,
                       deleted_at, deleted_by
                FROM kassenbuch_exporte
                WHERE kasse_id = ? AND deleted_at IS NULL
                ORDER BY zeitraum_bis DESC
                """,
                (kasse_id,),
            )
            return [KassenbuchExport(**dict(row)) for row in cur.fetchall()]

    def create_export(self, export: KassenbuchExport, created_by: str) -> KassenbuchExport:
        """Erstellt einen neuen Export-Datensatz. History via Trigger."""
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO kassenbuch_exporte (
                    kasse_id, zeitraum_von, zeitraum_bis,
                    exportiert_am, exportiert_von,
                    dateiname, anzahl_buchungen, created_by
                ) VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?, ?)
                """,
                (
                    export.kasse_id, export.zeitraum_von, export.zeitraum_bis,
                    created_by, export.dateiname, export.anzahl_buchungen, created_by,
                ),
            )
            export_id = cur.lastrowid
            cur.execute(
                """
                SELECT id, kasse_id, zeitraum_von, zeitraum_bis,
                       exportiert_am, exportiert_von, dateiname, anzahl_buchungen,
                       version, created_at, created_by,
                       deleted_at, deleted_by
                FROM kassenbuch_exporte WHERE id = ?
                """,
                (export_id,),
            )
            return KassenbuchExport(**dict(cur.fetchone()))

    def update_dateiname(self, export_id: int, dateiname: str) -> None:
        """Aktualisiert den Dateinamen eines Exports (direkt nach create, um ID einzubauen)."""
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE kassenbuch_exporte
                SET dateiname = ?, version = version + 1
                WHERE id = ?
                """,
                (dateiname, export_id),
            )

    def get_buchungen_fuer_export(
        self, export_id: int
    ) -> list[dict]:
        """Gibt alle Buchungen zurück, die zu einem bestimmten Export gehören.

        Wird für den Re-Export (erneuten Download) alter Exporte genutzt.
        Stornierte Buchungen werden ebenfalls zurückgegeben, da sie zum
        damaligen Zeitpunkt Teil des Exports waren.
        """
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT id, buchungsdatum, belegnummer, buchungstext, kategorie,
                       einnahme_cent, ausgabe_cent
                FROM kassenbuchungen
                WHERE exportiert_in_export_id = ?
                ORDER BY buchungsdatum ASC, id ASC
                """,
                (export_id,),
            )
            return [dict(row) for row in cur.fetchall()]

    def ist_buchung_gesperrt(self, buchung_id: int) -> bool:
        """Prüft ob eine Buchung bereits exportiert (und damit gesperrt) ist."""
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM kassenbuchungen
                WHERE id = ? AND exportiert_in_export_id IS NOT NULL
                """,
                (buchung_id,),
            )
            return cur.fetchone() is not None

    def get_nicht_exportierte_buchungen(
        self, kasse_id: int, bis_datum: str
    ) -> list[dict]:
        """Gibt alle exportierbaren Buchungen zurück (aktiv, nicht exportiert, bis Datum).

        Wird vom Service für den Export-Vorgang genutzt.
        """
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT id, buchungsdatum, belegnummer, buchungstext, kategorie,
                       einnahme_cent, ausgabe_cent
                FROM kassenbuchungen
                WHERE kasse_id = ?
                  AND deleted_at IS NULL
                  AND exportiert_in_export_id IS NULL
                  AND buchungsdatum <= ?
                ORDER BY buchungsdatum ASC, id ASC
                """,
                (kasse_id, bis_datum),
            )
            return [dict(row) for row in cur.fetchall()]
