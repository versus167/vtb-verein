"""
Repository für das Zugriffsprotokoll (`access_log`).

Append-only Log für Anmelde- und Aktivitätsereignisse:
- Auth-Events (login_success, login_failed, logout, magic_link_*) – category 'auth',
  dauerhaft aufbewahrt.
- Seitenaufrufe (page_view) – category 'page', wird nach 90 Tagen geprunt.

Das Log IST der Audit-Datensatz: kein Soft-Delete, keine *_history, keine Trigger.
Schreibzugriffe sind best-effort gedacht – die Aufrufer fangen Fehler ab, damit das
Protokollieren nie den Auth-/Request-Pfad bricht. Passwörter werden niemals gespeichert.
"""
from typing import Optional, Dict, Any, List

from app.db.database import Database


class AccessLogRepository:
    """Repository für das append-only Zugriffsprotokoll."""

    def __init__(self, db: Database):
        self.db = db

    def log(
        self,
        event_type: str,
        *,
        category: str = "auth",
        user_id: Optional[int] = None,
        username: Optional[str] = None,
        ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> None:
        """Schreibt einen Protokolleintrag (ein INSERT)."""
        with self.db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO access_log (
                    event_type, category, user_id, username, ip, user_agent, detail
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (event_type, category, user_id, username, ip, user_agent, detail),
            )

    @staticmethod
    def _filters(
        event_type: Optional[str],
        category: Optional[str],
        username: Optional[str],
        user_id: Optional[int],
        since: Optional[str],
        until: Optional[str],
        ip: Optional[str] = None,
    ) -> tuple[str, list]:
        """Baut die gemeinsame WHERE-Klausel für list()/count()."""
        clauses: list[str] = []
        params: list = []
        if event_type:
            clauses.append("event_type = %s")
            params.append(event_type)
        if category:
            clauses.append("category = %s")
            params.append(category)
        if username:
            clauses.append("username ILIKE %s")
            params.append(f"%{username}%")
        if user_id is not None:
            clauses.append("user_id = %s")
            params.append(user_id)
        if ip:
            clauses.append("ip = %s")
            params.append(ip)
        if since:
            clauses.append("created_at >= %s")
            params.append(since)
        if until:
            clauses.append("created_at < %s")
            params.append(until)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return where, params

    def list(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        event_type: Optional[str] = None,
        category: Optional[str] = None,
        username: Optional[str] = None,
        user_id: Optional[int] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        ip: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Protokollzeilen (neueste zuerst), gefiltert + paginiert."""
        where, params = self._filters(event_type, category, username, user_id, since, until, ip)
        with self.db.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, event_type, category, user_id, username, ip, user_agent,
                       detail, created_at
                FROM access_log
                {where}
                ORDER BY created_at DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            return cur.fetchall()

    def count(
        self,
        *,
        event_type: Optional[str] = None,
        category: Optional[str] = None,
        username: Optional[str] = None,
        user_id: Optional[int] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        ip: Optional[str] = None,
    ) -> int:
        """Gesamtzahl passender Zeilen (für die Pagination / Rate-Limiting)."""
        where, params = self._filters(event_type, category, username, user_id, since, until, ip)
        with self.db.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS n FROM access_log {where}", tuple(params))
            return cur.fetchone()["n"]

    def distinct_usernames(self) -> List[str]:
        """Alle im Protokoll vorkommenden Benutzernamen (alphabetisch, ohne NULL/leer).

        Speist das Benutzer-Dropdown des Zugriffsprotokoll-Filters – zeigt nur
        Benutzer, die tatsächlich Einträge haben (inkl. inzwischen gelöschter).
        """
        with self.db.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT username
                FROM access_log
                WHERE username IS NOT NULL AND username <> ''
                ORDER BY username
                """
            )
            return [r["username"] for r in cur.fetchall()]

    def count_page_views_older_than(self, days: int = 90) -> int:
        """Zahl der Seitenaufrufe (category 'page') älter als `days` Tage – für die Vorschau."""
        with self.db.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS n FROM access_log
                WHERE category = 'page' AND created_at < now() - make_interval(days => %s)
                """,
                (days,),
            )
            return cur.fetchone()["n"]

    def cleanup_page_views(self, days: int = 90) -> int:
        """Hard-Delete von Seitenaufrufen älter als `days` Tage (Prune-Job).

        Betrifft nur category 'page'; sicherheitsrelevante Auth-Events bleiben unberührt.
        """
        with self.db.cursor() as cur:
            cur.execute(
                """
                DELETE FROM access_log
                WHERE category = 'page'
                  AND created_at < now() - make_interval(days => %s)
                """,
                (days,),
            )
            return cur.rowcount
