"""Beitragsbefreiungen des Teamtresors (#98): clubdeckel_beitrag_befreiung.

Der Monatsbeitrag wird automatisch für alle aktiven Kader-Mitglieder gebucht —
befreite Mitglieder (z. B. Langzeitverletzte) stehen hier. Muster wie die
Wart-ACL: eine Zeile je (deckel, mitglied), Reaktivierung statt Neu-Insert.
"""
from app.db.base_repository import BaseRepository


class ClubdeckelBefreiungRepository(BaseRepository):

    def ist_befreit(self, deckel_id: int, mitglied_id: int) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM clubdeckel_beitrag_befreiung "
                "WHERE deckel_id = %s AND mitglied_id = %s AND deleted_at IS NULL LIMIT 1",
                (deckel_id, mitglied_id),
            )
            return cur.fetchone() is not None

    def list_for_deckel(self, deckel_id: int) -> list[dict]:
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT b.id, b.deckel_id, b.mitglied_id, b.version,
                       m.vorname || ' ' || m.nachname AS mitglied_name
                FROM clubdeckel_beitrag_befreiung b
                JOIN mitglied m ON m.id = b.mitglied_id
                WHERE b.deckel_id = %s AND b.deleted_at IS NULL
                ORDER BY lower(m.nachname), lower(m.vorname)
                """,
                (deckel_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def set_befreiung(self, deckel_id: int, mitglied_id: int, actor: str) -> None:
        """Befreit ein Mitglied (idempotent; reaktiviert soft-gelöschte Zeile)."""
        with self.cursor() as cur:
            cur.execute(
                "SELECT id, deleted_at FROM clubdeckel_beitrag_befreiung "
                "WHERE deckel_id = %s AND mitglied_id = %s "
                "ORDER BY (deleted_at IS NULL) DESC, id DESC LIMIT 1",
                (deckel_id, mitglied_id),
            )
            row = cur.fetchone()
            if row and row['deleted_at'] is None:
                return
            if row:
                cur.execute(
                    "UPDATE clubdeckel_beitrag_befreiung "
                    "SET deleted_at=NULL, deleted_by=NULL, "
                    "updated_at=CURRENT_TIMESTAMP, updated_by=%s, version=version+1 "
                    "WHERE id=%s",
                    (actor, row['id']),
                )
                return
            cur.execute(
                "INSERT INTO clubdeckel_beitrag_befreiung "
                "(deckel_id, mitglied_id, created_by, updated_by) VALUES (%s,%s,%s,%s)",
                (deckel_id, mitglied_id, actor, actor),
            )

    def revoke(self, deckel_id: int, mitglied_id: int, actor: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE clubdeckel_beitrag_befreiung "
                "SET deleted_at=CURRENT_TIMESTAMP, deleted_by=%s, version=version+1 "
                "WHERE deckel_id=%s AND mitglied_id=%s AND deleted_at IS NULL",
                (actor, deckel_id, mitglied_id),
            )
            return cur.rowcount > 0
