"""Repository für Gebühren-Forderungen (einmalige Forderung je Mitglied)."""
from typing import Optional
from app.models.gebuehr import GebuehrForderung
from app.db.base_repository import BaseRepository

_SELECT = """
    SELECT f.id, f.mitglied_id, f.gebuehr_id, f.datum, f.betrag_soll,
           f.status, f.bezahlt_am, f.kassenbuchung_id,
           f.exportiert_in_export_id, f.storno_exportiert_in_export_id,
           m.vorname AS mitglied_vorname, m.nachname AS mitglied_nachname,
           m.iban AS mitglied_iban, m.kontoinhaber AS mitglied_kontoinhaber,
           g.name AS gebuehr_name, g.zahler_typ AS zahler_typ,
           f.version, f.created_at, f.created_by, f.updated_at, f.updated_by
    FROM gebuehr_forderung f
    LEFT JOIN mitglied m ON m.id = f.mitglied_id
    LEFT JOIN gebuehr g ON g.id = f.gebuehr_id
"""


def _map(row) -> GebuehrForderung:
    return GebuehrForderung(**dict(row))


class GebuehrForderungRepository(BaseRepository):

    def get(self, id: int) -> Optional[GebuehrForderung]:
        with self.cursor() as cur:
            cur.execute(_SELECT + " WHERE f.id = %s AND f.deleted_at IS NULL", (id,))
            row = cur.fetchone()
            return _map(row) if row else None

    def list_all(self, status: Optional[str] = None) -> list[GebuehrForderung]:
        where = "WHERE f.deleted_at IS NULL"
        params: list = []
        if status:
            where += " AND f.status = %s"
            params.append(status)
        with self.cursor() as cur:
            cur.execute(_SELECT + where + " ORDER BY f.datum DESC, m.nachname, m.vorname", params)
            return [_map(r) for r in cur.fetchall()]

    def list_for_mitglied(self, mitglied_id: int) -> list[GebuehrForderung]:
        with self.cursor() as cur:
            cur.execute(
                _SELECT + " WHERE f.mitglied_id = %s AND f.deleted_at IS NULL ORDER BY f.datum DESC",
                (mitglied_id,),
            )
            return [_map(r) for r in cur.fetchall()]

    def exists(self, mitglied_id: int, gebuehr_id: int) -> bool:
        """True, wenn bereits eine (nicht stornierte) Forderung dieser Gebühr für das Mitglied existiert."""
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM gebuehr_forderung
                WHERE mitglied_id=%s AND gebuehr_id=%s AND status <> 'storniert' AND deleted_at IS NULL
                LIMIT 1
                """,
                (mitglied_id, gebuehr_id),
            )
            return cur.fetchone() is not None

    def create(self, f: GebuehrForderung, created_by: str) -> GebuehrForderung:
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO gebuehr_forderung (mitglied_id, gebuehr_id, datum, betrag_soll, status, created_by, updated_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                RETURNING id
                """,
                (f.mitglied_id, f.gebuehr_id, f.datum, f.betrag_soll, f.status, created_by, created_by),
            )
            new_id = cur.fetchone()['id']
        return self.get(new_id)

    def set_status(self, id: int, status: str, bezahlt_am: Optional[str], updated_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE gebuehr_forderung
                SET status=%s, bezahlt_am=%s, version=version+1,
                    updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id=%s AND deleted_at IS NULL
                """,
                (status, bezahlt_am, updated_by, id),
            )
            return cur.rowcount == 1

    def set_kassenbuchung(self, id: int, kassenbuchung_id: int, updated_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE gebuehr_forderung
                SET kassenbuchung_id=%s, version=version+1,
                    updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id=%s AND deleted_at IS NULL
                """,
                (kassenbuchung_id, updated_by, id),
            )
            return cur.rowcount == 1
