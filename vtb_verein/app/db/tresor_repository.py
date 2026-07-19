"""Repository für Tresore (#85) inkl. der ACL-Auflösung „welche Tresore darf ein User?".

Der Zugriff auf einen Tresor ergibt sich aus tresor_freigabe (Freigabe an User /
Abteilung / Funktion), NICHT aus globalen Rechten. Nur das reine Verwalten (Tresore
anlegen/löschen, Freigaben pflegen, alle Tresore sehen) hängt am globalen Recht
tresor.verwalten – Admins umgehen die ACL ohnehin (das entscheidet die API-Schicht).

Die Aktiv-Definition der Abteilungs-/Funktions-Zugehörigkeit (von/bis am Stichtag) deckt
sich bewusst mit der effektiven-Rechte-Logik (permission_repository.get_effective_permissions).
"""
from datetime import date
from typing import Optional

from app.models.tresor import Tresor
from app.db.base_repository import BaseRepository


# Gemeinsame CTEs: welche Abteilungen/Funktionen „gehören" dem User am Stichtag?
# Erwartet die benannten Parameter %(uid)s (user_id) und %(tag)s (ISO-Datum).
_ACL_CTE = """
    WITH meine_abteilungen AS (
        SELECT ma.abteilung_id AS pid
        FROM mitglied m
        JOIN mitglied_abteilung ma ON ma.mitglied_id = m.id AND ma.deleted_at IS NULL
            AND (ma.von IS NULL OR ma.von <= %(tag)s)
            AND (ma.bis IS NULL OR ma.bis >= %(tag)s)
        WHERE m.user_id = %(uid)s AND m.deleted_at IS NULL
    ),
    meine_funktionen AS (
        SELECT f.id AS pid
        FROM mitglied m
        JOIN mitglied_funktion mf ON mf.mitglied_id = m.id AND mf.deleted_at IS NULL
            AND (mf.von IS NULL OR mf.von <= %(tag)s)
            AND (mf.bis IS NULL OR mf.bis >= %(tag)s)
        JOIN funktion f ON f.key = mf.funktion AND f.deleted_at IS NULL
        WHERE m.user_id = %(uid)s AND m.deleted_at IS NULL
    )
"""

# Trifft eine tresor_freigabe-Zeile (Alias fr) auf den User zu?
_ACL_MATCH = """
    fr.deleted_at IS NULL AND (
        (fr.principal_typ = 'user' AND fr.principal_id = %(uid)s)
        OR (fr.principal_typ = 'abteilung' AND fr.principal_id IN (SELECT pid FROM meine_abteilungen))
        OR (fr.principal_typ = 'funktion' AND fr.principal_id IN (SELECT pid FROM meine_funktionen))
    )
"""

_COLS = ("id, name, beschreibung, version, "
         "created_at, created_by, updated_at, updated_by, deleted_at, deleted_by")


def _map(row) -> Tresor:
    return Tresor(
        id=row['id'], name=row['name'], beschreibung=row['beschreibung'],
        version=row['version'],
        created_at=row['created_at'], created_by=row['created_by'],
        updated_at=row['updated_at'], updated_by=row['updated_by'],
        deleted_at=row['deleted_at'], deleted_by=row['deleted_by'],
    )


class TresorRepository(BaseRepository):

    # ------------------------------------------------------------------ lesen
    def get(self, tresor_id: int) -> Optional[Tresor]:
        with self.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM tresor WHERE id = %s AND deleted_at IS NULL",
                (tresor_id,),
            )
            row = cur.fetchone()
            return _map(row) if row else None

    def list_all(self) -> list[dict]:
        """Alle aktiven Tresore mit Eintrags-/Kontaktzähler – für tresor.verwalten/Admin."""
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_COLS}, COALESCE(e.n, 0) AS eintrag_anzahl,
                       COALESCE(k.n, 0) AS kontakt_anzahl
                FROM tresor t
                LEFT JOIN (
                    SELECT tresor_id, COUNT(*) AS n FROM tresor_eintrag
                    WHERE deleted_at IS NULL GROUP BY tresor_id
                ) e ON e.tresor_id = t.id
                LEFT JOIN (
                    SELECT tresor_id, COUNT(*) AS n FROM tresor_kontakt
                    WHERE deleted_at IS NULL GROUP BY tresor_id
                ) k ON k.tresor_id = t.id
                WHERE t.deleted_at IS NULL
                ORDER BY lower(t.name)
                """
            )
            return [self._with_count(r, darf_schreiben=True) for r in cur.fetchall()]

    def list_for_user(self, user_id: int, stichtag: Optional[str] = None) -> list[dict]:
        """Tresore, auf die der User über eine Freigabe (User/Abteilung/Funktion) Zugriff hat,
        inkl. abgeleitetem darf_schreiben (write) und Eintragszähler."""
        tag = stichtag or date.today().isoformat()
        with self.cursor() as cur:
            cur.execute(
                _ACL_CTE + f"""
                , zugriff AS (
                    SELECT fr.tresor_id, bool_or(fr.zugriff = 'write') AS darf_schreiben
                    FROM tresor_freigabe fr
                    WHERE {_ACL_MATCH}
                    GROUP BY fr.tresor_id
                )
                SELECT {_COLS}, z.darf_schreiben, COALESCE(e.n, 0) AS eintrag_anzahl,
                       COALESCE(k.n, 0) AS kontakt_anzahl
                FROM tresor t
                JOIN zugriff z ON z.tresor_id = t.id
                LEFT JOIN (
                    SELECT tresor_id, COUNT(*) AS n FROM tresor_eintrag
                    WHERE deleted_at IS NULL GROUP BY tresor_id
                ) e ON e.tresor_id = t.id
                LEFT JOIN (
                    SELECT tresor_id, COUNT(*) AS n FROM tresor_kontakt
                    WHERE deleted_at IS NULL GROUP BY tresor_id
                ) k ON k.tresor_id = t.id
                WHERE t.deleted_at IS NULL
                ORDER BY lower(t.name)
                """,
                {"uid": user_id, "tag": tag},
            )
            return [self._with_count(r, darf_schreiben=bool(r['darf_schreiben']))
                    for r in cur.fetchall()]

    def get_access_for_user(self, user_id: int, tresor_id: int,
                            stichtag: Optional[str] = None) -> Optional[str]:
        """Effektive Zugriffsstufe des Users auf genau einen Tresor:
        None (kein Zugriff) | 'read' | 'write'. Admin-Bypass regelt die API-Schicht."""
        tag = stichtag or date.today().isoformat()
        with self.cursor() as cur:
            cur.execute(
                _ACL_CTE + f"""
                SELECT bool_or(fr.zugriff = 'write') AS darf_schreiben
                FROM tresor_freigabe fr
                WHERE fr.tresor_id = %(tid)s AND {_ACL_MATCH}
                """,
                {"uid": user_id, "tag": tag, "tid": tresor_id},
            )
            row = cur.fetchone()
            if row is None or row['darf_schreiben'] is None:
                return None
            return 'write' if row['darf_schreiben'] else 'read'

    # ----------------------------------------------------------------- schreiben
    def create(self, name: str, beschreibung: Optional[str], created_by: str) -> Tresor:
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO tresor (name, beschreibung, created_by, updated_by) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                (name, beschreibung, created_by, created_by),
            )
            new_id = cur.fetchone()['id']
        return self.get(new_id)

    def update(self, tresor_id: int, name: str, beschreibung: Optional[str],
               updated_by: str, expected_version: int) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE tresor SET name=%s, beschreibung=%s, "
                "updated_at=CURRENT_TIMESTAMP, updated_by=%s, version=version+1 "
                "WHERE id=%s AND deleted_at IS NULL AND version=%s",
                (name, beschreibung, updated_by, tresor_id, expected_version),
            )
            return cur.rowcount > 0

    def mark_deleted(self, tresor_id: int, deleted_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE tresor SET deleted_at=CURRENT_TIMESTAMP, deleted_by=%s, "
                "version=version+1 WHERE id=%s AND deleted_at IS NULL",
                (deleted_by, tresor_id),
            )
            return cur.rowcount > 0

    # -------------------------------------------------------------------- intern
    @staticmethod
    def _with_count(row, darf_schreiben: bool) -> dict:
        t = _map(row)
        return {
            "id": t.id, "name": t.name, "beschreibung": t.beschreibung,
            "version": t.version,
            "created_at": t.created_at, "created_by": t.created_by,
            "updated_at": t.updated_at, "updated_by": t.updated_by,
            "eintrag_anzahl": row['eintrag_anzahl'],
            "kontakt_anzahl": row['kontakt_anzahl'],
            "darf_schreiben": darf_schreiben,
        }
