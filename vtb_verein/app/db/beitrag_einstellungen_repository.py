"""Repository für die globale Beitrags-Konfiguration (Single-Row, id=1)."""
from app.models.beitrag import BeitragEinstellungen
from app.db.base_repository import BaseRepository

_COLS = """id, quartale_rueckschau,
           version, created_at, created_by, updated_at, updated_by"""


class BeitragEinstellungenRepository(BaseRepository):

    def get(self) -> BeitragEinstellungen:
        with self.cursor() as cur:
            cur.execute(f"SELECT {_COLS} FROM beitrag_einstellungen WHERE id = 1")
            row = cur.fetchone()
            if row is None:
                # Sicherheitsnetz: Single-Row anlegen, falls sie fehlt.
                cur.execute("INSERT INTO beitrag_einstellungen (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
                cur.execute(f"SELECT {_COLS} FROM beitrag_einstellungen WHERE id = 1")
                row = cur.fetchone()
            return BeitragEinstellungen(**dict(row))

    def update(self, e: BeitragEinstellungen, updated_by: str) -> BeitragEinstellungen:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE beitrag_einstellungen
                SET quartale_rueckschau=%s,
                    version=version+1, updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id = 1
                """,
                (e.quartale_rueckschau, updated_by),
            )
        return self.get()
