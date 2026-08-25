"""Repository für die Fristen der Ticket-Erinnerungen (Single-Row, id=1) – #179-Nachgang.

Aufbau wie `fibu_`/`schliessanlage_einstellungen`: eine Zeile, die nie gelöscht
wird, jede Änderung per Audit-Trigger in `ticket_erinnerung_einstellungen_history`.
"""
from app.models.ticket import TicketErinnerungEinstellungen
from app.db.base_repository import BaseRepository

_COLS = """id,
           unbeachtet_aktiv, unbeachtet_tage_sicherheit, unbeachtet_tage_hoch,
           unbeachtet_tage_normal, unbeachtet_tage_niedrig, unbeachtet_wiederholung_tage,
           stillstand_aktiv, stillstand_tage_sicherheit, stillstand_tage_hoch,
           stillstand_tage_normal, stillstand_tage_niedrig, stillstand_wiederholung_tage,
           version, created_at, created_by, updated_at, updated_by"""

_SETZBAR = (
    "unbeachtet_aktiv", "unbeachtet_tage_sicherheit", "unbeachtet_tage_hoch",
    "unbeachtet_tage_normal", "unbeachtet_tage_niedrig", "unbeachtet_wiederholung_tage",
    "stillstand_aktiv", "stillstand_tage_sicherheit", "stillstand_tage_hoch",
    "stillstand_tage_normal", "stillstand_tage_niedrig", "stillstand_wiederholung_tage",
)


class TicketErinnerungEinstellungenRepository(BaseRepository):

    def get(self) -> TicketErinnerungEinstellungen:
        with self.cursor() as cur:
            cur.execute(f"SELECT {_COLS} FROM ticket_erinnerung_einstellungen WHERE id = 1")
            row = cur.fetchone()
            if row is None:
                # Sicherheitsnetz: Single-Row anlegen, falls sie fehlt.
                cur.execute("INSERT INTO ticket_erinnerung_einstellungen (id) VALUES (1) "
                            "ON CONFLICT (id) DO NOTHING")
                cur.execute(f"SELECT {_COLS} FROM ticket_erinnerung_einstellungen WHERE id = 1")
                row = cur.fetchone()
            return TicketErinnerungEinstellungen(**dict(row))

    def update(self, e: TicketErinnerungEinstellungen,
               updated_by: str) -> TicketErinnerungEinstellungen:
        self.get()          # stellt sicher, dass die Zeile existiert
        zuweisungen = ", ".join(f"{spalte}=%s" for spalte in _SETZBAR)
        with self.cursor() as cur:
            cur.execute(
                f"""
                UPDATE ticket_erinnerung_einstellungen
                SET {zuweisungen},
                    version=version+1, updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id = 1
                """,
                tuple(getattr(e, spalte) for spalte in _SETZBAR) + (updated_by,),
            )
        return self.get()
