"""Repository für Kader-Zuordnungen (Mitglied <-> Mannschaft, mit Rolle und Zeitraum)."""
from dataclasses import dataclass
from typing import Optional
from app.db.base_repository import BaseRepository

# 'trainer' wurde mit #103 abgeschafft (== uebungsleiter); Bestand per Migration
# v71 auf 'uebungsleiter' gezogen.
VALID_ROLLEN = ('spieler', 'uebungsleiter', 'betreuer')


@dataclass
class MitgliedMannschaft:
    id: Optional[int] = None
    mitglied_id: Optional[int] = None
    mannschaft_id: Optional[int] = None
    rolle: str = 'spieler'
    von: Optional[str] = None
    bis: Optional[str] = None
    # per JOIN befüllt
    mitglied_vorname: Optional[str] = None
    mitglied_nachname: Optional[str] = None
    mannschaft_name: Optional[str] = None
    abteilung_id: Optional[int] = None
    abteilung_name: Optional[str] = None
    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None


_SELECT = """
    SELECT mm.id, mm.mitglied_id, mm.mannschaft_id, mm.rolle, mm.von, mm.bis,
           p.vorname AS mitglied_vorname, p.nachname AS mitglied_nachname,
           t.name AS mannschaft_name, t.abteilung_id AS abteilung_id,
           a.name AS abteilung_name,
           mm.version, mm.created_at, mm.created_by, mm.updated_at, mm.updated_by,
           mm.deleted_at, mm.deleted_by
    FROM mitglied_mannschaft mm
    LEFT JOIN mitglied p ON p.id = mm.mitglied_id
    LEFT JOIN mannschaft t ON t.id = mm.mannschaft_id
    LEFT JOIN abteilung a ON a.id = t.abteilung_id
"""


def _map(row) -> MitgliedMannschaft:
    return MitgliedMannschaft(**dict(row))


class MitgliedMannschaftRepository(BaseRepository):

    def get(self, id: int) -> Optional[MitgliedMannschaft]:
        with self.cursor() as cur:
            cur.execute(_SELECT + " WHERE mm.id = %s", (id,))
            row = cur.fetchone()
            return _map(row) if row else None

    def list_for_mannschaft(self, mannschaft_id: int) -> list[MitgliedMannschaft]:
        with self.cursor() as cur:
            cur.execute(
                _SELECT + """
                WHERE mm.mannschaft_id = %s AND mm.deleted_at IS NULL
                ORDER BY mm.rolle, p.nachname, p.vorname
                """,
                (mannschaft_id,),
            )
            return [_map(r) for r in cur.fetchall()]

    def list_for_mitglied(self, mitglied_id: int) -> list[MitgliedMannschaft]:
        with self.cursor() as cur:
            cur.execute(
                _SELECT + """
                WHERE mm.mitglied_id = %s AND mm.deleted_at IS NULL
                ORDER BY t.name
                """,
                (mitglied_id,),
            )
            return [_map(r) for r in cur.fetchall()]

    def create(self, mitglied_id: int, mannschaft_id: int, rolle: str,
               von: str, bis: Optional[str], created_by: str) -> MitgliedMannschaft:
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO mitglied_mannschaft
                    (mitglied_id, mannschaft_id, rolle, von, bis, created_by, updated_at, updated_by)
                VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, %s)
                RETURNING id
                """,
                (mitglied_id, mannschaft_id, rolle, von, bis, created_by, created_by),
            )
            new_id = cur.fetchone()['id']
        return self.get(new_id)

    def update(self, id: int, rolle: str, von: str, bis: Optional[str],
               updated_by: str, expected_version: int) -> bool:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE mitglied_mannschaft
                SET rolle=%s, von=%s, bis=%s,
                    version=version+1, updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id=%s AND version=%s AND deleted_at IS NULL
                """,
                (rolle, von, bis, updated_by, id, expected_version),
            )
            return cur.rowcount == 1

    def mark_deleted(self, id: int, deleted_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE mitglied_mannschaft
                SET deleted_at=CURRENT_TIMESTAMP, deleted_by=%s, version=version+1
                WHERE id=%s AND deleted_at IS NULL
                """,
                (deleted_by, id),
            )
            return cur.rowcount == 1
