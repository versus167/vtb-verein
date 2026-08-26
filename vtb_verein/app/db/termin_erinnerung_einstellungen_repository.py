"""Repository für den Vorlauf der Termin-Erinnerungen (Single-Row, id=1) – #95-Nachgang.

Aufbau wie `ticket_erinnerung_einstellungen`: eine Zeile, die nie gelöscht wird,
jede Änderung per Audit-Trigger in `termin_erinnerung_einstellungen_history`.
"""
from app.models.termin import TerminErinnerungEinstellungen
from app.db.base_repository import BaseRepository

_COLS = """id, aktiv, erste_stufe_tage, zweite_stufe_tage,
           version, created_at, created_by, updated_at, updated_by"""

_SETZBAR = ("aktiv", "erste_stufe_tage", "zweite_stufe_tage")


class TerminErinnerungEinstellungenRepository(BaseRepository):

    def get(self) -> TerminErinnerungEinstellungen:
        with self.cursor() as cur:
            cur.execute(f"SELECT {_COLS} FROM termin_erinnerung_einstellungen WHERE id = 1")
            row = cur.fetchone()
            if row is None:
                # Sicherheitsnetz: Single-Row anlegen, falls sie fehlt.
                cur.execute("INSERT INTO termin_erinnerung_einstellungen (id) VALUES (1) "
                            "ON CONFLICT (id) DO NOTHING")
                cur.execute(f"SELECT {_COLS} FROM termin_erinnerung_einstellungen WHERE id = 1")
                row = cur.fetchone()
            return TerminErinnerungEinstellungen(**dict(row))

    def update(self, e: TerminErinnerungEinstellungen,
               updated_by: str) -> TerminErinnerungEinstellungen:
        self.get()          # stellt sicher, dass die Zeile existiert
        zuweisungen = ", ".join(f"{spalte}=%s" for spalte in _SETZBAR)
        with self.cursor() as cur:
            cur.execute(
                f"""
                UPDATE termin_erinnerung_einstellungen
                SET {zuweisungen},
                    version=version+1, updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id = 1
                """,
                tuple(getattr(e, spalte) for spalte in _SETZBAR) + (updated_by,),
            )
        return self.get()
