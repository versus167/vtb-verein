"""Sammlungen der Teamkasse (#181): clubdeckel_event + clubdeckel_event_opt_out.

Ein Event ist eine EINMALIGE Umlage auf den ganzen Kader („60. Geburtstag
Klaus: 5 € von allen") — der Monatsbeitrag ohne Monat und ohne Automatik.
Gebucht wird gegen den Club (typ='event', −betrag je Teilnehmer); das Buchen
selbst liegt im Buchungs-Repo, weil es in dessen Ledger schreibt.

Der generelle Opt-out („macht bei Sammlungen nicht mit") steckt bewusst im
selben Repo statt in einem eigenen: Er hängt am DECKEL, nicht am Event, ist
aber nur für Events da — eine eigene Datei hätte den Zusammenhang zerrissen.
Muster wie die Beitragsbefreiung: eine Zeile je (deckel, mitglied),
Reaktivierung statt Neu-Insert.
"""
from decimal import Decimal
from typing import Optional

from app.models.clubdeckel import ClubdeckelEvent
from app.db.base_repository import BaseRepository

_COLS = ("id, deckel_id, name, betrag, fuer_mitglied_id, version, "
         "created_at, created_by, updated_at, updated_by, deleted_at, deleted_by")
_E_COLS = ", ".join("e." + c.strip() for c in _COLS.split(","))

# Kennzahlen der schon gebuchten Zeilen. Als Subquery statt JOIN+GROUP BY: Ein
# Event ohne Buchungen soll trotzdem in der Liste stehen, und die Summe ist der
# positive Sammelbetrag (die Buchungen selbst sind negativ).
_GEBUCHT = """
    (SELECT COUNT(*) FROM clubdeckel_buchung b
      WHERE b.event_id = e.id AND b.deleted_at IS NULL) AS gebucht_anzahl,
    COALESCE((SELECT SUM(-b.betrag) FROM clubdeckel_buchung b
      WHERE b.event_id = e.id AND b.deleted_at IS NULL), 0) AS gebucht_summe,
    (SELECT MAX(b.created_at) FROM clubdeckel_buchung b
      WHERE b.event_id = e.id AND b.deleted_at IS NULL) AS gebucht_am
"""


def _map(row) -> ClubdeckelEvent:
    return ClubdeckelEvent(**dict(row))


class ClubdeckelEventRepository(BaseRepository):

    # ---------------------------------------------------------------- Events
    def list_for_deckel(self, deckel_id: int) -> list[ClubdeckelEvent]:
        """Sammlungen des Deckels, neueste zuerst — mit Buchungsstand."""
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_E_COLS},
                       m.vorname || ' ' || m.nachname AS fuer_name,
                       {_GEBUCHT}
                FROM clubdeckel_event e
                LEFT JOIN mitglied m ON m.id = e.fuer_mitglied_id
                WHERE e.deckel_id = %s AND e.deleted_at IS NULL
                ORDER BY e.created_at DESC, e.id DESC
                """,
                (deckel_id,),
            )
            return [_map(r) for r in cur.fetchall()]

    def get(self, event_id: int) -> Optional[ClubdeckelEvent]:
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_E_COLS},
                       m.vorname || ' ' || m.nachname AS fuer_name,
                       {_GEBUCHT}
                FROM clubdeckel_event e
                LEFT JOIN mitglied m ON m.id = e.fuer_mitglied_id
                WHERE e.id = %s AND e.deleted_at IS NULL
                """,
                (event_id,),
            )
            row = cur.fetchone()
            return _map(row) if row else None

    def create(self, deckel_id: int, name: str, betrag: Decimal,
               fuer_mitglied_id: Optional[int], created_by: str) -> ClubdeckelEvent:
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO clubdeckel_event "
                "(deckel_id, name, betrag, fuer_mitglied_id, created_by, updated_by) "
                "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
                (deckel_id, name, betrag, fuer_mitglied_id, created_by, created_by),
            )
            new_id = cur.fetchone()['id']
        return self.get(new_id)

    def update(self, event_id: int, name: str, betrag: Decimal,
               fuer_mitglied_id: Optional[int], updated_by: str,
               expected_version: int) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE clubdeckel_event SET name=%s, betrag=%s, fuer_mitglied_id=%s, "
                "updated_at=CURRENT_TIMESTAMP, updated_by=%s, version=version+1 "
                "WHERE id=%s AND deleted_at IS NULL AND version=%s",
                (name, betrag, fuer_mitglied_id, updated_by, event_id, expected_version),
            )
            return cur.rowcount > 0

    def mark_deleted(self, event_id: int, deleted_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE clubdeckel_event SET deleted_at=CURRENT_TIMESTAMP, "
                "deleted_by=%s, version=version+1 WHERE id=%s AND deleted_at IS NULL",
                (deleted_by, event_id),
            )
            return cur.rowcount > 0

    # --------------------------------------------------------------- Opt-out
    def list_opt_outs(self, deckel_id: int) -> list[dict]:
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT o.id, o.deckel_id, o.mitglied_id, o.version,
                       m.vorname || ' ' || m.nachname AS mitglied_name
                FROM clubdeckel_event_opt_out o
                JOIN mitglied m ON m.id = o.mitglied_id
                WHERE o.deckel_id = %s AND o.deleted_at IS NULL
                ORDER BY lower(m.nachname), lower(m.vorname)
                """,
                (deckel_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def set_opt_out(self, deckel_id: int, mitglied_id: int, actor: str) -> None:
        """Nimmt ein Mitglied generell aus Sammlungen (idempotent; reaktiviert
        eine soft-gelöschte Zeile)."""
        with self.cursor() as cur:
            cur.execute(
                "SELECT id, deleted_at FROM clubdeckel_event_opt_out "
                "WHERE deckel_id = %s AND mitglied_id = %s "
                "ORDER BY (deleted_at IS NULL) DESC, id DESC LIMIT 1",
                (deckel_id, mitglied_id),
            )
            row = cur.fetchone()
            if row and row['deleted_at'] is None:
                return
            if row:
                cur.execute(
                    "UPDATE clubdeckel_event_opt_out "
                    "SET deleted_at=NULL, deleted_by=NULL, "
                    "updated_at=CURRENT_TIMESTAMP, updated_by=%s, version=version+1 "
                    "WHERE id=%s",
                    (actor, row['id']),
                )
                return
            cur.execute(
                "INSERT INTO clubdeckel_event_opt_out "
                "(deckel_id, mitglied_id, created_by, updated_by) VALUES (%s,%s,%s,%s)",
                (deckel_id, mitglied_id, actor, actor),
            )

    def revoke_opt_out(self, deckel_id: int, mitglied_id: int, actor: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE clubdeckel_event_opt_out "
                "SET deleted_at=CURRENT_TIMESTAMP, deleted_by=%s, version=version+1 "
                "WHERE deckel_id=%s AND mitglied_id=%s AND deleted_at IS NULL",
                (actor, deckel_id, mitglied_id),
            )
            return cur.rowcount > 0
