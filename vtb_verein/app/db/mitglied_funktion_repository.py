from dataclasses import dataclass
from typing import Optional
from app.db.base_repository import BaseRepository


@dataclass
class MitgliedFunktion:
    id: Optional[int] = None
    mitglied_id: Optional[int] = None
    abteilung_id: Optional[int] = None
    abteilung_name: Optional[str] = None
    funktion: str = ''
    von: Optional[str] = None
    bis: Optional[str] = None
    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None


class MitgliedFunktionRepository(BaseRepository):

    _SELECT = """
        SELECT mf.id, mf.mitglied_id, mf.abteilung_id,
               a.name AS abteilung_name,
               mf.funktion, mf.von, mf.bis,
               mf.version, mf.created_at, mf.created_by,
               mf.updated_at, mf.updated_by,
               mf.deleted_at, mf.deleted_by
        FROM mitglied_funktion mf
        LEFT JOIN abteilung a ON a.id = mf.abteilung_id
    """

    def get(self, id: int) -> Optional[MitgliedFunktion]:
        with self.cursor() as cur:
            cur.execute(self._SELECT + " WHERE mf.id = %s", (id,))
            row = cur.fetchone()
            return MitgliedFunktion(**dict(row)) if row else None

    def list_mitglieder_mit_funktion(self, funktion: str) -> list[dict]:
        """Aktive Inhaber einer Funktion (distinct je Mitglied) – z. B. für die ÜL-Auswahl
        bei der Fremderfassung. von/bis sind ISO-Datum-Texte (lexikografisch vergleichbar).

        Liefert zusätzlich die Trainerlizenz-Gültigkeit für den ÜL-Auswahlfilter (#64):
        `lizenz_aktuell_gueltig` = HEUTE liegt im Fenster [gueltig_von, gueltig_bis]
        (server-seitig per CURRENT_DATE, damit konsistent mit lizenz_fuer)."""
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT m.id, m.vorname, m.nachname, m.mitgliedsnummer,
                       m.trainerlizenz_gueltig_von, m.trainerlizenz_gueltig_bis,
                       (m.trainerlizenz_gueltig_von IS NOT NULL
                        AND m.trainerlizenz_gueltig_bis IS NOT NULL
                        AND m.trainerlizenz_gueltig_von <= CURRENT_DATE::text
                        AND m.trainerlizenz_gueltig_bis >= CURRENT_DATE::text) AS lizenz_aktuell_gueltig
                FROM mitglied_funktion mf
                JOIN mitglied m ON m.id = mf.mitglied_id AND m.deleted_at IS NULL
                WHERE mf.funktion = %s AND mf.deleted_at IS NULL
                  AND (mf.von IS NULL OR mf.von <= CURRENT_DATE::text)
                  AND (mf.bis IS NULL OR mf.bis >= CURRENT_DATE::text)
                ORDER BY m.nachname, m.vorname
                """,
                (funktion,),
            )
            return [dict(r) for r in cur.fetchall()]

    def abteilung_ids_fuer_funktion(self, mitglied_id: int, funktion: str) -> list[Optional[int]]:
        """abteilung_id je aktiver Zuordnung dieser Funktion (NULL = vereinsweit) – für die
        Abteilungs-Vorauswahl bei der Fremderfassung. von/bis als ISO-Text verglichen."""
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT abteilung_id FROM mitglied_funktion
                WHERE mitglied_id = %s AND funktion = %s AND deleted_at IS NULL
                  AND (von IS NULL OR von <= CURRENT_DATE::text)
                  AND (bis IS NULL OR bis >= CURRENT_DATE::text)
                """,
                (mitglied_id, funktion),
            )
            return [r['abteilung_id'] for r in cur.fetchall()]

    def list_for_mitglied(self, mitglied_id: int) -> list[MitgliedFunktion]:
        with self.cursor() as cur:
            cur.execute(
                self._SELECT + " WHERE mf.mitglied_id = %s AND mf.deleted_at IS NULL ORDER BY mf.funktion, a.name",
                (mitglied_id,),
            )
            return [MitgliedFunktion(**dict(row)) for row in cur.fetchall()]

    def create(self, mitglied_id: int, abteilung_id: Optional[int], funktion: str,
               von: Optional[str], bis: Optional[str], created_by: str) -> MitgliedFunktion:
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO mitglied_funktion
                    (mitglied_id, abteilung_id, funktion, von, bis, created_by, updated_at, updated_by)
                VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, %s)
                RETURNING id
                """,
                (mitglied_id, abteilung_id, funktion, von, bis, created_by, created_by),
            )
            new_id = cur.fetchone()['id']
            cur.execute(self._SELECT + " WHERE mf.id = %s", (new_id,))
            return MitgliedFunktion(**dict(cur.fetchone()))

    def update(self, id: int, abteilung_id: Optional[int], funktion: str,
               von: Optional[str], bis: Optional[str],
               updated_by: str, expected_version: int) -> bool:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE mitglied_funktion
                SET abteilung_id = %s, funktion = %s, von = %s, bis = %s,
                    version = version + 1,
                    updated_at = CURRENT_TIMESTAMP,
                    updated_by = %s
                WHERE id = %s AND version = %s AND deleted_at IS NULL
                """,
                (abteilung_id, funktion, von, bis, updated_by, id, expected_version),
            )
            return cur.rowcount == 1

    def mark_deleted(self, id: int, deleted_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE mitglied_funktion
                SET deleted_at = CURRENT_TIMESTAMP,
                    deleted_by = %s,
                    version = version + 1
                WHERE id = %s AND deleted_at IS NULL
                """,
                (deleted_by, id),
            )
            return cur.rowcount == 1
