"""
Repository für das Zugriffsprotokoll (`access_log`).

Append-only Log für Anmelde- und Aktivitätsereignisse, getrennt nach `category`:
'auth' (login_success, login_failed, logout, magic_link_*), 'page' (Seitenaufrufe),
'schliessanlage' und Übriges.

**Aufbewahrung steht NICHT hier.** Sie läuft für alle Kategorien über das
`LOG_REGISTRY` in `app/services/prune_service.py` – je Kategorie eine `LogRule`,
einstellbar auf der Datenbereinigungs-Seite. Kein Protokoll wird unbegrenzt
aufbewahrt, auch das Anmelde-Protokoll nicht (Default 365 Tage, Seitenaufrufe 90).
Dieser Docstring behauptete früher das Gegenteil; wer hier nach Fristen sucht,
findet sie in `prune_service.py`.

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

    # ------------------------------------------------------------------
    # Anmelde-Bremse (Brute-Force-Schutz)
    # ------------------------------------------------------------------
    #
    # Bewusst NICHT über list()/count() mit `username`: Dort wird der Benutzername
    # als *Teilstring* verglichen (ILIKE %…%), was den Protokollfilter bequem macht,
    # hier aber gefährlich wäre. Fehlversuche gegen „maximilian" zählten dann auf das
    # Konto „max" ein — ein Angreifer könnte fremde Konten gezielt aussperren, ohne
    # sie überhaupt anzutippen. Deshalb hier exakter Vergleich, normalisiert wie beim
    # Login selbst (getrimmt, klein geschrieben).

    @staticmethod
    def _norm(username: str) -> str:
        return (username or "").strip().lower()

    def count_login_failures(self, *, since: str, username: Optional[str] = None,
                             ip: Optional[str] = None) -> int:
        """Fehlgeschlagene Anmeldeversuche seit ``since`` – für die Anmelde-Bremse.

        Gezählt wird über den *eingetippten* Benutzernamen, nicht über eine
        aufgelöste user_id: Sonst blieben Versuche gegen nicht existierende Konten
        ungezählt, und die Antwort verriete nebenbei, welche Konten es gibt.
        """
        clauses = ["event_type = 'login_failed'", "created_at >= %s"]
        params: list = [since]
        if username is not None:
            clauses.append("lower(btrim(username)) = %s")
            params.append(self._norm(username))
        if ip:
            clauses.append("ip = %s")
            params.append(ip)
        with self.db.cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) AS n FROM access_log WHERE {' AND '.join(clauses)}",
                tuple(params),
            )
            return cur.fetchone()["n"]

    def last_login_success_at(self, username: str) -> Optional[str]:
        """Zeitpunkt der letzten erfolgreichen Anmeldung dieses Kontos (ISO) oder None.

        Setzt die Fehlversuchs-Zählung zurück: Wer sich zwischendurch erfolgreich
        angemeldet hat, startet wieder bei null. Ohne das würde jemand, der sich
        viermal vertippt, sich anmeldet und später noch einmal danebengreift,
        grundlos ausgesperrt.
        """
        with self.db.cursor() as cur:
            cur.execute(
                """
                SELECT created_at FROM access_log
                WHERE event_type = 'login_success' AND lower(btrim(username)) = %s
                ORDER BY created_at DESC LIMIT 1
                """,
                (self._norm(username),),
            )
            row = cur.fetchone()
            if row is None:
                return None
            wert = row["created_at"]
            return wert.isoformat() if hasattr(wert, "isoformat") else wert

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

    def find_schliessanlage_unlock_near(
        self, schloss_id: int, ts_iso: str, window_seconds: int = 120
    ) -> Optional[Dict[str, Any]]:
        """Korrelations-Lookup für die Zutrittslog-Auflösung (#66, Phase-5-Teil B):
        der VTB-User, der dieses Schloss über die App ferngeöffnet hat
        (event_type 'schliessanlage_unlock'), zeitlich am nächsten an `ts_iso` (dem
        lockDate des TTLock-Records) innerhalb ±`window_seconds`.

        Das Schloss steckt nur im Freitext-`detail` (kein strukturiertes Feld) – die
        LIKE-Bedingung ist an das Schreibformat in backend/api/schliessanlage.py gekoppelt:
        'Schloss {id} (…) ferngeöffnet'. Das schließende ' (' trennt z. B. 5 von 50.
        Gibt {'user_id', 'username'} des nächstliegenden Treffers zurück oder None.
        """
        with self.db.cursor() as cur:
            cur.execute(
                """
                SELECT user_id, username
                FROM access_log
                WHERE event_type = 'schliessanlage_unlock'
                  AND detail LIKE %s
                  AND created_at BETWEEN %s::timestamptz - make_interval(secs => %s)
                                     AND %s::timestamptz + make_interval(secs => %s)
                ORDER BY ABS(EXTRACT(EPOCH FROM (created_at - %s::timestamptz)))
                LIMIT 1
                """,
                (f"Schloss {schloss_id} (%", ts_iso, window_seconds,
                 ts_iso, window_seconds, ts_iso),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    # ------------------------------------------------------------------
    # Altlast: die beiden folgenden Methoden ruft niemand mehr auf. Sie stammen
    # aus der Zeit, als nur die Seitenaufrufe eine Frist hatten; seit dem
    # LOG_REGISTRY läuft die Bereinigung generisch über prune_service und deckt
    # alle Kategorien ab. Sie stehen hier nur noch, weil ihr Wortlaut („Auth-Events
    # bleiben unberührt") die irrige Annahme genährt hat, Anmelde-Ereignisse würden
    # dauerhaft aufbewahrt — sie tun es nicht.
    # ------------------------------------------------------------------

    def count_page_views_older_than(self, days: int = 90) -> int:
        """Zahl der Seitenaufrufe (category 'page') älter als `days` Tage.

        UNBENUTZT – die Vorschau der Datenbereinigung rechnet über LOG_REGISTRY.
        """
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
        """Hard-Delete von Seitenaufrufen älter als `days` Tage.

        UNBENUTZT – der Prune-Lauf löscht über LOG_REGISTRY, und zwar in allen
        Kategorien, nicht nur bei den Seitenaufrufen.
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
