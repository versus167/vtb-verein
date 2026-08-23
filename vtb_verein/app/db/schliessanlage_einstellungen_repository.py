"""Repository für die Stammdaten des Bereichs Schließanlage (Single-Row, id=1).

Hält bisher nur die Akku-Überwachung: Ticket-Bereich, Schwelle, Priorität. Aufbau
wie `fibu_einstellungen` – eine Zeile, die nie gelöscht wird, jede Änderung per
Audit-Trigger in `schliessanlage_einstellungen_history`.
"""
from app.models.schliessanlage import SchliessanlageEinstellungen
from app.db.base_repository import BaseRepository

_COLS = """id, akku_ticket_bereich_id, akku_ticket_schwelle, akku_ticket_prioritaet,
           version, created_at, created_by, updated_at, updated_by"""


class SchliessanlageEinstellungenRepository(BaseRepository):

    def get(self) -> SchliessanlageEinstellungen:
        with self.cursor() as cur:
            cur.execute(f"SELECT {_COLS} FROM schliessanlage_einstellungen WHERE id = 1")
            row = cur.fetchone()
            if row is None:
                # Sicherheitsnetz: Single-Row anlegen, falls sie fehlt.
                cur.execute("INSERT INTO schliessanlage_einstellungen (id) VALUES (1) "
                            "ON CONFLICT (id) DO NOTHING")
                cur.execute(f"SELECT {_COLS} FROM schliessanlage_einstellungen WHERE id = 1")
                row = cur.fetchone()
            return SchliessanlageEinstellungen(**dict(row))

    def update(self, e: SchliessanlageEinstellungen, updated_by: str) -> SchliessanlageEinstellungen:
        self.get()          # stellt sicher, dass die Zeile existiert
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE schliessanlage_einstellungen
                SET akku_ticket_bereich_id=%s, akku_ticket_schwelle=%s,
                    akku_ticket_prioritaet=%s,
                    version=version+1, updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id = 1
                """,
                (e.akku_ticket_bereich_id, e.akku_ticket_schwelle,
                 e.akku_ticket_prioritaet, updated_by),
            )
        return self.get()
