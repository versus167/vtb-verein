"""Repository für konfigurierbare Übungsleiter-Vergütungssätze (€/h).

Auflösung (spezifischster gewinnt): ÜL-individuell (mitglied_id gesetzt) →
Abteilung+Lizenz → vereinsweit+Lizenz. Der aufgelöste Satz wird beim Einreichen
einer Abrechnung als Snapshot eingefroren.
"""
from typing import Optional

from app.models.ul_stunden import ULSatz
from app.db.base_repository import BaseRepository


_SELECT = """
    SELECT s.id, s.mitglied_id, s.abteilung_id, s.lizenz_klassifikation, s.satz,
           s.gueltig_ab,
           m.vorname AS mitglied_vorname, m.nachname AS mitglied_nachname,
           ab.name AS abteilung_name,
           s.version, s.created_at, s.created_by, s.updated_at, s.updated_by
    FROM ul_satz s
    LEFT JOIN mitglied m ON m.id = s.mitglied_id
    LEFT JOIN abteilung ab ON ab.id = s.abteilung_id
"""


def _map(row) -> ULSatz:
    return ULSatz(**dict(row))


class ULSatzRepository(BaseRepository):

    def list_all(self) -> list[ULSatz]:
        with self.cursor() as cur:
            cur.execute(
                _SELECT + " WHERE s.deleted_at IS NULL "
                "ORDER BY (s.mitglied_id IS NOT NULL) DESC, ab.name NULLS FIRST, "
                "s.lizenz_klassifikation"
            )
            return [_map(r) for r in cur.fetchall()]

    def get(self, id: int) -> Optional[ULSatz]:
        with self.cursor() as cur:
            cur.execute(_SELECT + " WHERE s.id=%s AND s.deleted_at IS NULL", (id,))
            row = cur.fetchone()
            return _map(row) if row else None

    def resolve(self, mitglied_id: int, abteilung_id: int,
                lizenz_klassifikation: str) -> Optional[float]:
        """Liefert den passendsten Satz (€/h) oder None.

        Reihenfolge: ÜL-spezifisch vor Abteilung-spezifisch vor vereinsweit;
        bei Gleichstand der jüngste gueltig_ab.
        """
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT satz FROM ul_satz
                WHERE deleted_at IS NULL
                  AND lizenz_klassifikation=%s
                  AND (mitglied_id=%s OR mitglied_id IS NULL)
                  AND (abteilung_id=%s OR abteilung_id IS NULL)
                ORDER BY (mitglied_id IS NOT NULL) DESC,
                         (abteilung_id IS NOT NULL) DESC,
                         gueltig_ab DESC NULLS LAST
                LIMIT 1
                """,
                (lizenz_klassifikation, mitglied_id, abteilung_id),
            )
            row = cur.fetchone()
            return row['satz'] if row else None

    def create(self, s: ULSatz, created_by: str) -> ULSatz:
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ul_satz
                    (mitglied_id, abteilung_id, lizenz_klassifikation, satz, gueltig_ab,
                     created_by, updated_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                RETURNING id
                """,
                (s.mitglied_id, s.abteilung_id, s.lizenz_klassifikation, s.satz,
                 s.gueltig_ab, created_by, created_by),
            )
            new_id = cur.fetchone()['id']
        return self.get(new_id)

    def update(self, s: ULSatz, updated_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE ul_satz
                SET mitglied_id=%s, abteilung_id=%s, lizenz_klassifikation=%s,
                    satz=%s, gueltig_ab=%s, version=version+1,
                    updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id=%s AND version=%s AND deleted_at IS NULL
                """,
                (s.mitglied_id, s.abteilung_id, s.lizenz_klassifikation, s.satz,
                 s.gueltig_ab, updated_by, s.id, s.version),
            )
            return cur.rowcount == 1

    def soft_delete(self, id: int, deleted_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE ul_satz
                SET deleted_at=CURRENT_TIMESTAMP, deleted_by=%s,
                    version=version+1, updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id=%s AND deleted_at IS NULL
                """,
                (deleted_by, deleted_by, id),
            )
            return cur.rowcount == 1
