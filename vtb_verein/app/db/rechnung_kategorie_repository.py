"""Repository für Rechnungs-Kategorien (vereinsweite Stammdaten).

Die Kategorie trägt das Aufwandskonto (sachkonto) und optionale Kostenstelle/
Kostenträger – damit reicht dem Einreicher eine einzige Auswahl.
"""
from typing import Optional

from app.models.rechnung import RechnungKategorie
from app.db.base_repository import BaseRepository


_SELECT = """
    SELECT id, name, beschreibung, sachkonto, kostenstelle, kostentraeger,
           version, created_at, created_by, updated_at, updated_by,
           deleted_at, deleted_by
    FROM rechnung_kategorie
"""


def _map(row) -> RechnungKategorie:
    return RechnungKategorie(**dict(row))


class RechnungKategorieRepository(BaseRepository):

    def get(self, id: int) -> Optional[RechnungKategorie]:
        with self.cursor() as cur:
            cur.execute(_SELECT + " WHERE id = %s AND deleted_at IS NULL", (id,))
            row = cur.fetchone()
            return _map(row) if row else None

    def list_alle(self) -> list[RechnungKategorie]:
        with self.cursor() as cur:
            cur.execute(_SELECT + " WHERE deleted_at IS NULL ORDER BY name")
            return [_map(r) for r in cur.fetchall()]

    def create(self, k: RechnungKategorie, created_by: str) -> RechnungKategorie:
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO rechnung_kategorie
                    (name, beschreibung, sachkonto, kostenstelle, kostentraeger,
                     created_by, updated_at, updated_by)
                VALUES (%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP,%s)
                RETURNING id
                """,
                (k.name, k.beschreibung, k.sachkonto, k.kostenstelle, k.kostentraeger,
                 created_by, created_by),
            )
            new_id = cur.fetchone()["id"]
        return self.get(new_id)

    def update(self, k: RechnungKategorie, updated_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE rechnung_kategorie
                SET name=%s, beschreibung=%s, sachkonto=%s,
                    kostenstelle=%s, kostentraeger=%s,
                    version=version+1, updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id=%s AND version=%s AND deleted_at IS NULL
                """,
                (k.name, k.beschreibung, k.sachkonto, k.kostenstelle, k.kostentraeger,
                 updated_by, k.id, k.version),
            )
            return cur.rowcount == 1

    def soft_delete(self, id: int, deleted_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE rechnung_kategorie
                SET deleted_at=CURRENT_TIMESTAMP, deleted_by=%s,
                    version=version+1, updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id=%s AND deleted_at IS NULL
                """,
                (deleted_by, deleted_by, id),
            )
            return cur.rowcount == 1

    def wird_verwendet(self, id: int) -> bool:
        """True, wenn noch lebende Rechnungen auf die Kategorie zeigen.

        Verhindert, dass eine Kategorie verschwindet, auf die exportierte oder
        laufende Rechnungen verweisen – der Name steckt nicht denormalisiert
        in der Rechnung.
        """
        with self.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM rechnung WHERE kategorie_id = %s AND deleted_at IS NULL LIMIT 1",
                (id,),
            )
            return cur.fetchone() is not None
