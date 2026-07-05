'''
KassenKategorieRepository – Stammdaten für Kassenbuchungs-Kategorien.

Kategorien steuern die Auswahl bei der Buchungserfassung. Sie sind entweder
allgemein (kasse_id IS NULL, bei jeder Kasse wählbar) oder kassenspezifisch
(nur bei der zugeordneten Kasse wählbar). Die Buchung selbst speichert die
Kategorie weiterhin denormalisiert als Text.

Soft-Delete-only (deleted_at); History via DB-Trigger.
'''

from app.models.kasse import KassenKategorie
from app.db.base_repository import BaseRepository

_COLS = (
    "id, kasse_id, name, loest_zaehlung_aus, gegenkonto, kostentraeger, version, "
    "created_at, created_by, updated_at, updated_by, deleted_at, deleted_by"
)


class KassenKategorieRepository(BaseRepository):
    """Repository für verwaltete Kassen-Kategorien."""

    # -----------------------------------
    # Read
    # -----------------------------------

    def get(self, kategorie_id: int) -> KassenKategorie | None:
        with self.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM kassen_kategorien WHERE id = %s",
                (kategorie_id,),
            )
            row = cur.fetchone()
            return KassenKategorie(**dict(row)) if row else None

    def list_all(self, include_deleted: bool = False) -> list[KassenKategorie]:
        """Alle Kategorien (allgemein + kassenspezifisch) – für die Verwaltung."""
        where = "" if include_deleted else "WHERE deleted_at IS NULL"
        with self.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM kassen_kategorien {where} "
                f"ORDER BY (kasse_id IS NOT NULL), name"
            )
            return [KassenKategorie(**dict(r)) for r in cur.fetchall()]

    def list_for_kasse(self, kasse_id: int) -> list[KassenKategorie]:
        """Effektive Auswahl für eine Kasse: allgemeine ∪ kassenspezifische."""
        with self.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM kassen_kategorien "
                f"WHERE deleted_at IS NULL AND (kasse_id IS NULL OR kasse_id = %s) "
                f"ORDER BY name",
                (kasse_id,),
            )
            return [KassenKategorie(**dict(r)) for r in cur.fetchall()]

    def name_konflikt(
        self, kasse_id: int | None, name: str, exclude_id: int | None = None
    ) -> bool:
        """True, wenn eine aktive Kategorie mit gleichem Namen in der effektiven
        Auswahl der Ziel-Kasse bereits erscheinen würde (case-insensitiv).

        Für allgemeine Kategorien (kasse_id None) wird nur gegen allgemeine
        geprüft; für kassenspezifische gegen allgemeine ∪ diese Kasse.
        """
        if kasse_id is None:
            scope = "kasse_id IS NULL"
            params: list = [name]
        else:
            scope = "(kasse_id IS NULL OR kasse_id = %s)"
            params = [kasse_id, name]
        sql = (
            f"SELECT 1 FROM kassen_kategorien "
            f"WHERE deleted_at IS NULL AND {scope} AND lower(name) = lower(%s)"
        )
        if exclude_id is not None:
            sql += " AND id <> %s"
            params.append(exclude_id)
        with self.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone() is not None

    # -----------------------------------
    # Write
    # -----------------------------------

    def create(self, kategorie: KassenKategorie, created_by: str) -> KassenKategorie:
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO kassen_kategorien (kasse_id, name, loest_zaehlung_aus, gegenkonto, kostentraeger, created_by, updated_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (kategorie.kasse_id, kategorie.name, kategorie.loest_zaehlung_aus,
                 kategorie.gegenkonto, kategorie.kostentraeger, created_by, created_by),
            )
            new_id = cur.fetchone()["id"]
        return self.get(new_id)

    def update(self, kategorie: KassenKategorie, updated_by: str) -> bool:
        """Aktualisiert Name + Geltungsbereich + Zählung-Flag (Optimistic Locking via version)."""
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE kassen_kategorien
                SET name = %s, kasse_id = %s, loest_zaehlung_aus = %s, gegenkonto = %s,
                    kostentraeger = %s,
                    version = version + 1,
                    updated_at = CURRENT_TIMESTAMP, updated_by = %s
                WHERE id = %s AND version = %s AND deleted_at IS NULL
                """,
                (kategorie.name, kategorie.kasse_id, kategorie.loest_zaehlung_aus,
                 kategorie.gegenkonto, kategorie.kostentraeger, updated_by,
                 kategorie.id, kategorie.version),
            )
            return cur.rowcount > 0

    def mark_deleted(self, kategorie_id: int, deleted_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE kassen_kategorien
                SET deleted_at = CURRENT_TIMESTAMP, deleted_by = %s, version = version + 1
                WHERE id = %s AND deleted_at IS NULL
                """,
                (deleted_by, kategorie_id),
            )
            return cur.rowcount > 0
