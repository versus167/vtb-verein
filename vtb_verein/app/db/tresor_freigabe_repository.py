"""Repository für Tresor-Freigaben (ACL, #85).

Eine Freigabe verknüpft einen Tresor mit einem Principal (User / Abteilung / Funktion)
und einer Zugriffsstufe (read | write). Reaktiviert soft-gelöschte Einträge beim erneuten
Vergeben (analog KasseBerechtigungRepository).
"""
from typing import Optional

from app.models.tresor import TresorFreigabe
from app.db.base_repository import BaseRepository

_SELECT = """
    SELECT fr.id, fr.tresor_id, fr.principal_typ, fr.principal_id, fr.zugriff,
           fr.version, fr.created_at, fr.created_by, fr.updated_at, fr.updated_by,
           fr.deleted_at, fr.deleted_by,
           CASE fr.principal_typ
               WHEN 'user'      THEN u.username
               WHEN 'abteilung' THEN a.name
               WHEN 'funktion'  THEN f.name
           END AS principal_name
    FROM tresor_freigabe fr
    LEFT JOIN users     u ON fr.principal_typ = 'user'      AND u.id = fr.principal_id
    LEFT JOIN abteilung a ON fr.principal_typ = 'abteilung' AND a.id = fr.principal_id
    LEFT JOIN funktion  f ON fr.principal_typ = 'funktion'  AND f.id = fr.principal_id
"""


def _map(row) -> TresorFreigabe:
    return TresorFreigabe(**dict(row))


class TresorFreigabeRepository(BaseRepository):

    def list_for_tresor(self, tresor_id: int) -> list[TresorFreigabe]:
        with self.cursor() as cur:
            cur.execute(
                _SELECT + " WHERE fr.tresor_id = %s AND fr.deleted_at IS NULL "
                          "ORDER BY fr.principal_typ, principal_name NULLS LAST",
                (tresor_id,),
            )
            return [_map(r) for r in cur.fetchall()]

    def get(self, tresor_id: int, principal_typ: str, principal_id: int) -> Optional[TresorFreigabe]:
        with self.cursor() as cur:
            cur.execute(
                _SELECT + " WHERE fr.tresor_id = %s AND fr.principal_typ = %s "
                          "AND fr.principal_id = %s AND fr.deleted_at IS NULL",
                (tresor_id, principal_typ, principal_id),
            )
            row = cur.fetchone()
            return _map(row) if row else None

    def set_freigabe(self, tresor_id: int, principal_typ: str, principal_id: int,
                     zugriff: str, actor: str) -> TresorFreigabe:
        """Legt eine Freigabe an oder aktualisiert/reaktiviert eine bestehende."""
        with self.cursor() as cur:
            cur.execute(
                "SELECT id FROM tresor_freigabe "
                "WHERE tresor_id=%s AND principal_typ=%s AND principal_id=%s",
                (tresor_id, principal_typ, principal_id),
            )
            existing = cur.fetchone()
            if existing is None:
                cur.execute(
                    "INSERT INTO tresor_freigabe "
                    "(tresor_id, principal_typ, principal_id, zugriff, created_by, updated_by) "
                    "VALUES (%s,%s,%s,%s,%s,%s)",
                    (tresor_id, principal_typ, principal_id, zugriff, actor, actor),
                )
            else:
                cur.execute(
                    "UPDATE tresor_freigabe SET zugriff=%s, deleted_at=NULL, deleted_by=NULL, "
                    "updated_at=CURRENT_TIMESTAMP, updated_by=%s, version=version+1 "
                    "WHERE tresor_id=%s AND principal_typ=%s AND principal_id=%s",
                    (zugriff, actor, tresor_id, principal_typ, principal_id),
                )
        return self.get(tresor_id, principal_typ, principal_id)

    def revoke(self, tresor_id: int, principal_typ: str, principal_id: int, actor: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE tresor_freigabe SET deleted_at=CURRENT_TIMESTAMP, deleted_by=%s, "
                "updated_at=CURRENT_TIMESTAMP, updated_by=%s, version=version+1 "
                "WHERE tresor_id=%s AND principal_typ=%s AND principal_id=%s AND deleted_at IS NULL",
                (actor, actor, tresor_id, principal_typ, principal_id),
            )
            return cur.rowcount > 0

    def revoke_alle_freigaben_fuer_tresor(self, tresor_id: int, actor: str) -> int:
        """Beim Löschen eines Tresors alle Freigaben mit-entziehen."""
        with self.cursor() as cur:
            cur.execute(
                "UPDATE tresor_freigabe SET deleted_at=CURRENT_TIMESTAMP, deleted_by=%s, "
                "updated_at=CURRENT_TIMESTAMP, updated_by=%s, version=version+1 "
                "WHERE tresor_id=%s AND deleted_at IS NULL",
                (actor, actor, tresor_id),
            )
            return cur.rowcount

    def revoke_alle_freigaben_fuer_user(self, user_id: int, actor: str) -> int:
        """Beim Löschen eines Users dessen persönliche Freigaben entziehen
        (Abteilungs-/Funktions-Freigaben bleiben – sie hängen nicht am User)."""
        with self.cursor() as cur:
            cur.execute(
                "UPDATE tresor_freigabe SET deleted_at=CURRENT_TIMESTAMP, deleted_by=%s, "
                "updated_at=CURRENT_TIMESTAMP, updated_by=%s, version=version+1 "
                "WHERE principal_typ='user' AND principal_id=%s AND deleted_at IS NULL",
                (actor, actor, user_id),
            )
            return cur.rowcount
