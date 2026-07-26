"""Repository für Rechnungs-Export-Läufe (Header + Delta-Stempel).

Der Lauf-Header wird zusammen mit dem Stempeln der Quellzeilen in EINER Transaktion
angelegt (Muster fibu_export_repository.create_export) – sonst könnte ein paralleler
Lauf dieselben Rechnungen ein zweites Mal mitnehmen.
"""
from typing import Optional

from app.models.rechnung import RechnungExport
from app.db.base_repository import BaseRepository


_COLS = """id, exportiert_am, exportiert_von, dateiname, format,
           anzahl_rechnungen, summe_cent, version,
           created_at, created_by, deleted_at, deleted_by"""


def _map(row) -> RechnungExport:
    return RechnungExport(**dict(row))


class RechnungExportRepository(BaseRepository):

    def get(self, export_id: int) -> Optional[RechnungExport]:
        with self.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM rechnung_exporte WHERE id = %s AND deleted_at IS NULL",
                (export_id,),
            )
            row = cur.fetchone()
            return _map(row) if row else None

    def list_exporte(self) -> list[RechnungExport]:
        with self.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM rechnung_exporte WHERE deleted_at IS NULL "
                f"ORDER BY id DESC"
            )
            return [_map(r) for r in cur.fetchall()]

    def create_export(self, *, exportiert_von: str, dateiname: str,
                      anzahl_rechnungen: int, summe_cent: Optional[int],
                      rechnung_ids: list[int]) -> RechnungExport:
        """Legt den Lauf an und stempelt die Rechnungen – atomar.

        Das `exportiert_in_export_id IS NULL` im UPDATE ist die Absicherung gegen
        einen zeitgleichen zweiten Lauf: schon gestempelte Zeilen bleiben unberührt.
        """
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO rechnung_exporte
                    (exportiert_von, dateiname, format, anzahl_rechnungen, summe_cent, created_by)
                VALUES (%s,%s,'zip',%s,%s,%s)
                RETURNING id
                """,
                (exportiert_von, dateiname, anzahl_rechnungen, summe_cent, exportiert_von),
            )
            export_id = cur.fetchone()["id"]
            if rechnung_ids:
                cur.execute(
                    """
                    UPDATE rechnung
                    SET exportiert_in_export_id=%s, version=version+1,
                        updated_at=CURRENT_TIMESTAMP, updated_by=%s
                    WHERE id = ANY(%s) AND exportiert_in_export_id IS NULL
                    """,
                    (export_id, exportiert_von, list(rechnung_ids)),
                )
            cur.execute(f"SELECT {_COLS} FROM rechnung_exporte WHERE id = %s", (export_id,))
            return _map(cur.fetchone())

    def update_dateiname(self, export_id: int, dateiname: str) -> None:
        """Der Dateiname trägt die Lauf-ID, die erst nach dem INSERT feststeht."""
        with self.cursor() as cur:
            cur.execute(
                "UPDATE rechnung_exporte SET dateiname = %s WHERE id = %s",
                (dateiname, export_id),
            )

    def is_latest(self, export_id: int) -> bool:
        """True, wenn export_id der jüngste lebende Lauf ist (Un-Export-Bedingung)."""
        with self.cursor() as cur:
            cur.execute("SELECT MAX(id) AS max_id FROM rechnung_exporte WHERE deleted_at IS NULL")
            row = cur.fetchone()
            return row is not None and row["max_id"] == export_id

    def un_export(self, export_id: int, *, benutzer: str) -> int:
        """Nimmt einen Lauf zurück: Stempel lösen + Header soft-deleten.

        Liefert die Anzahl wieder offener Rechnungen.
        """
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE rechnung
                SET exportiert_in_export_id=NULL, version=version+1,
                    updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE exportiert_in_export_id=%s
                """,
                (benutzer, export_id),
            )
            geloest = cur.rowcount
            cur.execute(
                """
                UPDATE rechnung_exporte
                SET deleted_at=CURRENT_TIMESTAMP, deleted_by=%s, version=version+1
                WHERE id=%s AND deleted_at IS NULL
                """,
                (benutzer, export_id),
            )
            return geloest
