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
        if status == 'exportiert':
            # "an Fibu übergeben": exportiert und (noch) nicht storniert – deckt sich
            # mit dem indigofarbenen Status-Chip in der Forderungsliste.
            where += " AND f.exportiert_in_export_id IS NOT NULL AND f.status <> 'storniert'"
        elif status == 'offen':
            # "Erstellt": angelegt, aber noch nicht an die Fibu übergeben (und nicht
            # storniert) – schließt bereits übergebene Forderungen aus, deckt sich mit
            # dem orangefarbenen Status-Chip.
            where += " AND f.status = 'offen' AND f.exportiert_in_export_id IS NULL"
        elif status:
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

    def list_deleted(self) -> list[GebuehrForderung]:
        """Papierkorb: soft-gelöschte Forderungen (neueste Löschung zuerst)."""
        with self.cursor() as cur:
            cur.execute(
                _SELECT + " WHERE f.deleted_at IS NOT NULL ORDER BY f.deleted_at DESC, m.nachname, m.vorname"
            )
            return [_map(r) for r in cur.fetchall()]

    def list_deleted_for_mitglied(self, mitglied_id: int) -> list[GebuehrForderung]:
        with self.cursor() as cur:
            cur.execute(
                _SELECT + " WHERE f.mitglied_id = %s AND f.deleted_at IS NOT NULL ORDER BY f.deleted_at DESC",
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

    def soft_delete(self, id: int, deleted_by: str) -> bool:
        """Soft-Delete (Papierkorb). Nur offene/stornierte – bezahlte bleiben
        gesperrt. Anders als beim Storno verschwindet die Forderung damit aus
        der aktiven Sicht und kann über den Papierkorb wiederhergestellt werden.

        Bereits an die Fibu übergebene Forderungen (exportiert_in_export_id gesetzt)
        sind gesperrt: deren Rücknahme läuft ausschließlich über Storno
        (Gegenbuchung im nächsten Export), sonst gäbe es eine Fibu-Buchung ohne
        passenden VTB-Beleg."""
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE gebuehr_forderung
                SET deleted_at=CURRENT_TIMESTAMP, deleted_by=%s,
                    version=version+1, updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id=%s AND deleted_at IS NULL AND status IN ('offen','storniert')
                  AND exportiert_in_export_id IS NULL
                """,
                (deleted_by, deleted_by, id),
            )
            return cur.rowcount > 0

    def restore(self, id: int, restored_by: str) -> bool:
        """Aus dem Papierkorb wiederherstellen. Verweigert, wenn dadurch ein
        Duplikat entstünde (für dieselbe Gebühr besteht bereits eine aktive,
        nicht stornierte Forderung) – stornierte Forderungen sind immer
        wiederherstellbar."""
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE gebuehr_forderung f
                SET deleted_at=NULL, deleted_by=NULL,
                    version=version+1, updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE f.id=%s AND f.deleted_at IS NOT NULL
                  AND (
                    f.status = 'storniert'
                    OR NOT EXISTS (
                        SELECT 1 FROM gebuehr_forderung d
                        WHERE d.mitglied_id = f.mitglied_id AND d.gebuehr_id = f.gebuehr_id
                          AND d.status <> 'storniert' AND d.deleted_at IS NULL
                    )
                  )
                """,
                (restored_by, id),
            )
            return cur.rowcount > 0
