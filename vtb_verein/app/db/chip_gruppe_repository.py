"""Repository für Chip-Rechtegruppen (#169).

Eine Gruppe („Übungsleiter") bündelt Schlösser und wird Chips dauerhaft
zugeordnet. Dieses Repo hält ausschließlich den SOLL-Zustand — welche Türen
gehören zur Gruppe, welche Chips tragen sie. Was daraus an den Schlössern
tatsächlich passiert (IC-Karten anlegen/entfernen), macht der
:class:`ZutrittService` beim Abgleich.

Die beiden n:m-Tabellen werden nie hart gelöscht: Ein Entzug ist ein Vorgang,
den man später nachvollziehen können muss („warum kam diese Tür weg?"), deshalb
Soft-Delete + History wie überall. Ein erneutes Zuordnen belebt die alte Zeile
wieder (`restore`), statt eine zweite anzulegen — der partielle Unique-Index
lässt ohnehin nur eine lebende je Paar zu.
"""
from typing import Optional

from app.models.schliessanlage import ChipGruppe
from app.db.base_repository import BaseRepository

_SELECT = """
    SELECT g.id, g.name, g.beschreibung,
           (SELECT COUNT(*) FROM chip_gruppe_schloss gs
             WHERE gs.gruppe_id = g.id AND gs.deleted_at IS NULL) AS anzahl_schloesser,
           (SELECT COUNT(*) FROM chip_gruppe_zuordnung gz
             WHERE gz.gruppe_id = g.id AND gz.deleted_at IS NULL) AS anzahl_chips,
           g.version, g.created_at, g.created_by, g.updated_at, g.updated_by,
           g.deleted_at, g.deleted_by
    FROM chip_gruppe g
"""


def _map(row) -> ChipGruppe:
    return ChipGruppe(**dict(row))


class ChipGruppeRepository(BaseRepository):

    # ---- Gruppe ----------------------------------------------------------

    def get(self, id: int) -> Optional[ChipGruppe]:
        with self.cursor() as cur:
            cur.execute(_SELECT + " WHERE g.id = %s AND g.deleted_at IS NULL", (id,))
            row = cur.fetchone()
            if not row:
                return None
            gruppe = _map(row)
        gruppe.schloss_ids = self.schloss_ids(id)
        return gruppe

    def list_all(self) -> list[ChipGruppe]:
        with self.cursor() as cur:
            cur.execute(_SELECT + " WHERE g.deleted_at IS NULL ORDER BY g.name")
            return [_map(r) for r in cur.fetchall()]

    def find_by_name(self, name: str) -> Optional[ChipGruppe]:
        """Spiegelt den partiellen Unique-Index (LOWER(name) WHERE deleted_at IS NULL)."""
        with self.cursor() as cur:
            cur.execute(
                _SELECT + " WHERE LOWER(g.name) = LOWER(%s) AND g.deleted_at IS NULL",
                (name,),
            )
            row = cur.fetchone()
            return _map(row) if row else None

    def create(self, g: ChipGruppe, created_by: str) -> ChipGruppe:
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO chip_gruppe (name, beschreibung, created_by, updated_by)
                VALUES (%s,%s,%s,%s) RETURNING id
                """,
                (g.name, g.beschreibung, created_by, created_by),
            )
            new_id = cur.fetchone()['id']
        return self.get(new_id)

    def update(self, g: ChipGruppe, updated_by: str) -> Optional[ChipGruppe]:
        """Name/Beschreibung fortschreiben (optimistisch über `version`)."""
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE chip_gruppe
                SET name=%s, beschreibung=%s, version=version+1,
                    updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id=%s AND version=%s AND deleted_at IS NULL
                """,
                (g.name, g.beschreibung, updated_by, g.id, g.version),
            )
            if cur.rowcount == 0:
                return None
        return self.get(g.id)

    def soft_delete(self, id: int, deleted_by: str) -> bool:
        """Gruppe löschen. Die Zuordnungen räumt der Service VORHER weg — hier fällt
        nur die Hülle, damit keine Chips mit einer Gruppen-Leiche zurückbleiben."""
        with self.cursor() as cur:
            cur.execute(
                "UPDATE chip_gruppe SET deleted_at=CURRENT_TIMESTAMP, deleted_by=%s, "
                "version=version+1 WHERE id=%s AND deleted_at IS NULL",
                (deleted_by, id),
            )
            return cur.rowcount > 0

    # ---- Schlösser der Gruppe -------------------------------------------

    def schloss_ids(self, gruppe_id: int) -> list[int]:
        with self.cursor() as cur:
            cur.execute(
                "SELECT schloss_id FROM chip_gruppe_schloss "
                "WHERE gruppe_id=%s AND deleted_at IS NULL ORDER BY schloss_id",
                (gruppe_id,),
            )
            return [r['schloss_id'] for r in cur.fetchall()]

    def set_schloesser(self, gruppe_id: int, schloss_ids: list[int], by: str) -> list[int]:
        """Türliste der Gruppe auf genau `schloss_ids` bringen; gibt die neue Liste zurück."""
        vorher = set(self.schloss_ids(gruppe_id))
        soll = set(schloss_ids)
        for schloss_id in soll - vorher:
            self._paar_setzen("chip_gruppe_schloss", "schloss_id", gruppe_id, schloss_id, by)
        for schloss_id in vorher - soll:
            self._paar_loeschen("chip_gruppe_schloss", "schloss_id", gruppe_id, schloss_id, by)
        return self.schloss_ids(gruppe_id)

    # ---- Chips der Gruppe ------------------------------------------------

    def chip_ids(self, gruppe_id: int) -> list[int]:
        with self.cursor() as cur:
            cur.execute(
                "SELECT chip_id FROM chip_gruppe_zuordnung "
                "WHERE gruppe_id=%s AND deleted_at IS NULL ORDER BY chip_id",
                (gruppe_id,),
            )
            return [r['chip_id'] for r in cur.fetchall()]

    def gruppen_fuer_chip(self, chip_id: int) -> list[ChipGruppe]:
        with self.cursor() as cur:
            cur.execute(
                _SELECT + """
                JOIN chip_gruppe_zuordnung gz
                  ON gz.gruppe_id = g.id AND gz.deleted_at IS NULL
                WHERE gz.chip_id = %s AND g.deleted_at IS NULL
                ORDER BY g.name
                """,
                (chip_id,),
            )
            return [_map(r) for r in cur.fetchall()]

    def soll_schloss_ids_fuer_chip(self, chip_id: int) -> list[int]:
        """Alle Türen, die dem Chip über seine Gruppen zustehen (Vereinigung).

        Die eine Abfrage, aus der der Abgleich seinen SOLL-Zustand zieht: Ein Chip
        in zwei Gruppen bekommt jede Tür genau einmal, und eine gelöschte Gruppe
        zählt nicht mehr mit."""
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT gs.schloss_id
                FROM chip_gruppe_zuordnung gz
                JOIN chip_gruppe g ON g.id = gz.gruppe_id AND g.deleted_at IS NULL
                JOIN chip_gruppe_schloss gs
                  ON gs.gruppe_id = g.id AND gs.deleted_at IS NULL
                JOIN tuer_schloss s ON s.id = gs.schloss_id AND s.deleted_at IS NULL
                WHERE gz.chip_id = %s AND gz.deleted_at IS NULL
                ORDER BY gs.schloss_id
                """,
                (chip_id,),
            )
            return [r['schloss_id'] for r in cur.fetchall()]

    def quelle_gruppe(self, chip_id: int, schloss_id: int) -> Optional[int]:
        """Welche Gruppe des Chips fordert dieses Schloss? (Erste nach Name.)

        Die Herkunft an der Berechtigung ist eine Momentaufnahme: Fordern zwei
        Gruppen dieselbe Tür, steht eine davon dran — für den Abgleich zählt nur,
        DASS sie aus einer Gruppe stammt."""
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT g.id
                FROM chip_gruppe_zuordnung gz
                JOIN chip_gruppe g ON g.id = gz.gruppe_id AND g.deleted_at IS NULL
                JOIN chip_gruppe_schloss gs
                  ON gs.gruppe_id = g.id AND gs.deleted_at IS NULL AND gs.schloss_id = %s
                WHERE gz.chip_id = %s AND gz.deleted_at IS NULL
                ORDER BY g.name
                LIMIT 1
                """,
                (schloss_id, chip_id),
            )
            row = cur.fetchone()
            return row['id'] if row else None

    def chip_zuordnen(self, gruppe_id: int, chip_id: int, by: str) -> None:
        self._paar_setzen("chip_gruppe_zuordnung", "chip_id", gruppe_id, chip_id, by)

    def chip_entfernen(self, gruppe_id: int, chip_id: int, by: str) -> bool:
        return self._paar_loeschen("chip_gruppe_zuordnung", "chip_id", gruppe_id, chip_id, by)

    def alle_chips_entfernen(self, gruppe_id: int, by: str) -> list[int]:
        """Alle Chips aus der Gruppe nehmen (vor dem Löschen); gibt deren IDs zurück,
        damit der Aufrufer sie anschließend abgleichen kann."""
        chips = self.chip_ids(gruppe_id)
        for chip_id in chips:
            self._paar_loeschen("chip_gruppe_zuordnung", "chip_id", gruppe_id, chip_id, by)
        return chips

    # ---- geteilte Mechanik der beiden Paar-Tabellen ----------------------

    def _paar_setzen(self, tabelle: str, spalte: str, gruppe_id: int,
                     wert: int, by: str) -> None:
        """Paar anlegen – oder eine früher gelöschte Zeile wiederbeleben.

        Ohne das Wiederbeleben liefe der partielle Unique-Index zwar nicht ins
        Messer, die History bekäme aber für jedes Hin und Her eine neue id-Reihe."""
        with self.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {tabelle}
                SET deleted_at=NULL, deleted_by=NULL, version=version+1,
                    updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE gruppe_id=%s AND {spalte}=%s AND deleted_at IS NOT NULL
                """,
                (by, gruppe_id, wert),
            )
            if cur.rowcount:
                return
            cur.execute(
                f"""
                INSERT INTO {tabelle} (gruppe_id, {spalte}, created_by, updated_by)
                VALUES (%s,%s,%s,%s)
                ON CONFLICT DO NOTHING
                """,
                (gruppe_id, wert, by, by),
            )

    def _paar_loeschen(self, tabelle: str, spalte: str, gruppe_id: int,
                       wert: int, by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                f"UPDATE {tabelle} SET deleted_at=CURRENT_TIMESTAMP, deleted_by=%s, "
                f"version=version+1 "
                f"WHERE gruppe_id=%s AND {spalte}=%s AND deleted_at IS NULL",
                (by, gruppe_id, wert),
            )
            return cur.rowcount > 0
