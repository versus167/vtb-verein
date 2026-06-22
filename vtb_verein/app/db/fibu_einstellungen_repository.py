"""Repository für die globale Fibu-Konfiguration (Single-Row, id=1)."""
from app.models.fibu import FibuEinstellungen
from app.db.base_repository import BaseRepository

_COLS = """id, debitor_konto_basis, default_gegenkonto, default_steuerschluessel,
           verein_kostenstelle, default_kostentraeger,
           version, created_at, created_by, updated_at, updated_by"""


class FibuEinstellungenRepository(BaseRepository):

    def get(self) -> FibuEinstellungen:
        with self.cursor() as cur:
            cur.execute(f"SELECT {_COLS} FROM fibu_einstellungen WHERE id = 1")
            row = cur.fetchone()
            if row is None:
                # Sicherheitsnetz: Single-Row anlegen, falls sie fehlt.
                cur.execute("INSERT INTO fibu_einstellungen (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
                cur.execute(f"SELECT {_COLS} FROM fibu_einstellungen WHERE id = 1")
                row = cur.fetchone()
            return FibuEinstellungen(**dict(row))

    def update(self, e: FibuEinstellungen, updated_by: str) -> FibuEinstellungen:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE fibu_einstellungen
                SET debitor_konto_basis=%s, default_gegenkonto=%s, default_steuerschluessel=%s,
                    verein_kostenstelle=%s, default_kostentraeger=%s,
                    version=version+1, updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id = 1
                """,
                (e.debitor_konto_basis, e.default_gegenkonto, e.default_steuerschluessel,
                 e.verein_kostenstelle, e.default_kostentraeger, updated_by),
            )
        return self.get()
