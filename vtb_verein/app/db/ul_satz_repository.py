"""Repository für konfigurierbare Übungsleiter-Vergütungsvereinbarungen.

Auflösung (spezifischster gewinnt): ÜL-individuell (mitglied_id gesetzt) →
Abteilung → vereinsweit; auf jeder Stufe schlägt der exakte Lizenz-Treffer den
lizenz-unabhängigen Satz (lizenz_klassifikation IS NULL). Die aufgelöste
Vereinbarung — Satzwert *und* Vergütungsart — wird beim Einreichen einer
Abrechnung als Snapshot eingefroren.
"""
from typing import Optional

from app.models.ul_stunden import ULSatz
from app.db.base_repository import BaseRepository


_SELECT = """
    SELECT s.id, s.mitglied_id, s.abteilung_id, s.lizenz_klassifikation,
           s.verguetungsart, s.satz, s.gueltig_ab,
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
                "s.lizenz_klassifikation NULLS FIRST"
            )
            return [_map(r) for r in cur.fetchall()]

    def get(self, id: int) -> Optional[ULSatz]:
        with self.cursor() as cur:
            cur.execute(_SELECT + " WHERE s.id=%s AND s.deleted_at IS NULL", (id,))
            row = cur.fetchone()
            return _map(row) if row else None

    def resolve(self, mitglied_id: int, abteilung_id: int,
                lizenz_klassifikation: str) -> Optional[ULSatz]:
        """Liefert die passendste Vereinbarung (Satz + Vergütungsart) oder None.

        Reihenfolge: ÜL-spezifisch vor Abteilung-spezifisch vor vereinsweit, und
        innerhalb jeder Stufe die exakte Lizenz vor dem lizenz-unabhängigen Satz
        (lizenz_klassifikation IS NULL); bei Gleichstand der jüngste gueltig_ab.

        Die Geltungsbereiche stehen bewusst VOR der Lizenz: Eine individuelle
        Vereinbarung soll auch dann greifen, wenn sie für beide Lizenzlagen gilt
        und daneben ein exakter Abteilungssatz existiert.
        """
        with self.cursor() as cur:
            cur.execute(
                _SELECT + """
                WHERE s.deleted_at IS NULL
                  AND (s.lizenz_klassifikation=%s OR s.lizenz_klassifikation IS NULL)
                  AND (s.mitglied_id=%s OR s.mitglied_id IS NULL)
                  AND (s.abteilung_id=%s OR s.abteilung_id IS NULL)
                ORDER BY (s.mitglied_id IS NOT NULL) DESC,
                         (s.abteilung_id IS NOT NULL) DESC,
                         (s.lizenz_klassifikation IS NOT NULL) DESC,
                         s.gueltig_ab DESC NULLS LAST
                LIMIT 1
                """,
                (lizenz_klassifikation, mitglied_id, abteilung_id),
            )
            row = cur.fetchone()
            return _map(row) if row else None

    def create(self, s: ULSatz, created_by: str) -> ULSatz:
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ul_satz
                    (mitglied_id, abteilung_id, lizenz_klassifikation, verguetungsart,
                     satz, gueltig_ab, created_by, updated_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id
                """,
                (s.mitglied_id, s.abteilung_id, s.lizenz_klassifikation, s.verguetungsart,
                 s.satz, s.gueltig_ab, created_by, created_by),
            )
            new_id = cur.fetchone()['id']
        return self.get(new_id)

    def update(self, s: ULSatz, updated_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE ul_satz
                SET mitglied_id=%s, abteilung_id=%s, lizenz_klassifikation=%s,
                    verguetungsart=%s, satz=%s, gueltig_ab=%s, version=version+1,
                    updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id=%s AND version=%s AND deleted_at IS NULL
                """,
                (s.mitglied_id, s.abteilung_id, s.lizenz_klassifikation,
                 s.verguetungsart, s.satz, s.gueltig_ab, updated_by, s.id, s.version),
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
