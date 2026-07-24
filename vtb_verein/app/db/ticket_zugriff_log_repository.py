"""Repository für das Ticket-„Gesehen"-Log (#130-Nachgang).

Append-only: jede Sicht-Session eines Users auf ein Ticket wird protokolliert
(„wann haben die Verantwortlichen das Ticket gesehen"). Kein History/Soft-Delete –
das Log IST der Audit-Datensatz (analog access_log / tresor_zugriff_log). Der
Username wird als Snapshot mitgeschrieben, damit das Log auch nach dem Löschen des
Users lesbar bleibt. Bereinigung über den zeitbasierten Prune (prune_service),
nicht über das PRUNE_REGISTRY.
"""
from typing import Optional

from app.db.base_repository import BaseRepository

# Doppel-Klicks / Reloads sollen keine Flut an Zeilen erzeugen: innerhalb dieses
# Fensters gilt eine Sicht als dieselbe Session und wird nicht erneut protokolliert.
DEFAULT_THROTTLE_MINUTES = 30


class TicketZugriffLogRepository(BaseRepository):

    def log(self, *, ticket_id: int, user_id: Optional[int], username: Optional[str],
            throttle_minutes: int = DEFAULT_THROTTLE_MINUTES) -> bool:
        """Protokolliert eine Sicht. Überspringt (return False), wenn derselbe User das
        Ticket innerhalb von ``throttle_minutes`` bereits gesehen hat."""
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO ticket_zugriff_log (ticket_id, user_id, username) "
                "SELECT %s, %s, %s "
                "WHERE NOT EXISTS ("
                "  SELECT 1 FROM ticket_zugriff_log "
                "  WHERE ticket_id = %s AND user_id IS NOT DISTINCT FROM %s "
                "    AND created_at > now() - make_interval(mins => %s)"
                ")",
                (ticket_id, user_id, username,
                 ticket_id, user_id, throttle_minutes),
            )
            return cur.rowcount > 0

    def list_seen(self, ticket_id: int) -> list[dict]:
        """Je User eine Zeile: zuletzt/erstmals gesehen + Anzahl Sichten, jüngste zuerst."""
        with self.cursor() as cur:
            cur.execute(
                "SELECT user_id, MAX(username) AS username, "
                "       MAX(created_at) AS zuletzt_gesehen_am, "
                "       MIN(created_at) AS erstmals_gesehen_am, "
                "       COUNT(*) AS anzahl "
                "FROM ticket_zugriff_log "
                "WHERE ticket_id = %s "
                "GROUP BY user_id "
                "ORDER BY MAX(created_at) DESC",
                (ticket_id,),
            )
            return [dict(row) for row in cur.fetchall()]

    def count_older_than(self, days: int) -> int:
        """Zahl der Log-Zeilen älter als ``days`` Tage – für die Prune-Vorschau."""
        with self.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS n FROM ticket_zugriff_log "
                "WHERE created_at < now() - make_interval(days => %s)",
                (days,),
            )
            return cur.fetchone()["n"]

    def count(self) -> int:
        with self.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM ticket_zugriff_log")
            return cur.fetchone()["n"]

    def cleanup_older_than(self, days: int) -> int:
        """Hard-Delete aller Log-Zeilen älter als ``days`` Tage. Gibt die Anzahl zurück."""
        with self.cursor() as cur:
            cur.execute(
                "DELETE FROM ticket_zugriff_log "
                "WHERE created_at < now() - make_interval(days => %s)",
                (days,),
            )
            return cur.rowcount
