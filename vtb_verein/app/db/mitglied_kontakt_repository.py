"""
MitgliedKontakt Repository – mehrere Kontaktdaten (E-Mail/Telefon/…) je Mitglied.

Voll normalisiert: löst die früheren Einzelspalten mitglied.email/telefon ab.
Pro Mitglied und Typ kann genau ein Kontakt als primär markiert sein (partieller
Unique-Index uix_mitglied_kontakt_primaer). History wird per DB-Trigger geschrieben.
"""
from dataclasses import dataclass
from typing import Optional
from app.db.base_repository import BaseRepository

VALID_TYPEN = ('email', 'telefon', 'mobil', 'fax')


@dataclass
class MitgliedKontakt:
    id: Optional[int] = None
    mitglied_id: Optional[int] = None
    typ: str = ''
    wert: str = ''
    label: Optional[str] = None
    ist_primaer: bool = False
    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None


class MitgliedKontaktRepository(BaseRepository):

    _SELECT = """
        SELECT id, mitglied_id, typ, wert, label, ist_primaer,
               version, created_at, created_by, updated_at, updated_by,
               deleted_at, deleted_by
        FROM mitglied_kontakt
    """

    def get(self, id: int) -> Optional[MitgliedKontakt]:
        with self.cursor() as cur:
            cur.execute(self._SELECT + " WHERE id = %s", (id,))
            row = cur.fetchone()
            return MitgliedKontakt(**dict(row)) if row else None

    def list_for_mitglied(self, mitglied_id: int) -> list[MitgliedKontakt]:
        with self.cursor() as cur:
            cur.execute(
                self._SELECT + """
                WHERE mitglied_id = %s AND deleted_at IS NULL
                ORDER BY typ, ist_primaer DESC, id
                """,
                (mitglied_id,),
            )
            return [MitgliedKontakt(**dict(row)) for row in cur.fetchall()]

    def get_primaer(self, mitglied_id: int, typ: str) -> Optional[str]:
        """Liefert den Wert des primären Kontakts eines Typs (z.B. für Mailing)."""
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT wert FROM mitglied_kontakt
                WHERE mitglied_id = %s AND typ = %s AND ist_primaer AND deleted_at IS NULL
                LIMIT 1
                """,
                (mitglied_id, typ),
            )
            row = cur.fetchone()
            return row['wert'] if row else None

    def create(self, mitglied_id: int, typ: str, wert: str, label: Optional[str],
               ist_primaer: bool, created_by: str) -> MitgliedKontakt:
        with self.cursor() as cur:
            if ist_primaer:
                self._unset_primaer(cur, mitglied_id, typ, exclude_id=None, actor=created_by)
            cur.execute(
                """
                INSERT INTO mitglied_kontakt
                    (mitglied_id, typ, wert, label, ist_primaer, created_by, updated_at, updated_by)
                VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, %s)
                RETURNING id
                """,
                (mitglied_id, typ, wert, label, ist_primaer, created_by, created_by),
            )
            new_id = cur.fetchone()['id']
            cur.execute(self._SELECT + " WHERE id = %s", (new_id,))
            return MitgliedKontakt(**dict(cur.fetchone()))

    def update(self, id: int, typ: str, wert: str, label: Optional[str], ist_primaer: bool,
               updated_by: str, expected_version: int) -> bool:
        with self.cursor() as cur:
            # Mitglied + Typ des Eintrags für die Primär-Bereinigung ermitteln
            cur.execute(
                "SELECT mitglied_id FROM mitglied_kontakt WHERE id = %s AND deleted_at IS NULL",
                (id,),
            )
            row = cur.fetchone()
            if row is None:
                return False
            if ist_primaer:
                self._unset_primaer(cur, row['mitglied_id'], typ, exclude_id=id, actor=updated_by)
            cur.execute(
                """
                UPDATE mitglied_kontakt
                SET typ = %s, wert = %s, label = %s, ist_primaer = %s,
                    version = version + 1,
                    updated_at = CURRENT_TIMESTAMP,
                    updated_by = %s
                WHERE id = %s AND version = %s AND deleted_at IS NULL
                """,
                (typ, wert, label, ist_primaer, updated_by, id, expected_version),
            )
            return cur.rowcount == 1

    def upsert_primaer(self, mitglied_id: int, typ: str, wert: Optional[str], actor: str) -> None:
        """Setzt/aktualisiert den primären Kontakt eines Typs aus einem Einzelfeld
        (Kompatibilität zu den früheren mitglied.email/telefon-Feldern).

        - leerer Wert  → vorhandenen Primärkontakt soft-löschen
        - vorhandener  → Wert aktualisieren
        - keiner       → neuen Primärkontakt anlegen
        """
        wert = (wert or '').strip()
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM mitglied_kontakt
                WHERE mitglied_id = %s AND typ = %s AND ist_primaer AND deleted_at IS NULL
                ORDER BY id LIMIT 1
                """,
                (mitglied_id, typ),
            )
            row = cur.fetchone()
            if not wert:
                if row:
                    cur.execute(
                        """
                        UPDATE mitglied_kontakt
                        SET deleted_at = CURRENT_TIMESTAMP, deleted_by = %s, version = version + 1
                        WHERE id = %s
                        """,
                        (actor, row['id']),
                    )
                return
            if row:
                cur.execute(
                    """
                    UPDATE mitglied_kontakt
                    SET wert = %s, version = version + 1,
                        updated_at = CURRENT_TIMESTAMP, updated_by = %s
                    WHERE id = %s
                    """,
                    (wert, actor, row['id']),
                )
            else:
                self._unset_primaer(cur, mitglied_id, typ, exclude_id=None, actor=actor)
                cur.execute(
                    """
                    INSERT INTO mitglied_kontakt
                        (mitglied_id, typ, wert, ist_primaer, created_by, updated_at, updated_by)
                    VALUES (%s, %s, %s, TRUE, %s, CURRENT_TIMESTAMP, %s)
                    """,
                    (mitglied_id, typ, wert, actor, actor),
                )

    def mark_deleted(self, id: int, deleted_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE mitglied_kontakt
                SET deleted_at = CURRENT_TIMESTAMP,
                    deleted_by = %s,
                    version = version + 1
                WHERE id = %s AND deleted_at IS NULL
                """,
                (deleted_by, id),
            )
            return cur.rowcount == 1

    def _unset_primaer(self, cur, mitglied_id: int, typ: str,
                       exclude_id: Optional[int], actor: str) -> None:
        """Hebt die Primär-Markierung aller anderen aktiven Kontakte dieses Typs auf,
        damit der partielle Unique-Index nicht verletzt wird."""
        cur.execute(
            """
            UPDATE mitglied_kontakt
            SET ist_primaer = FALSE,
                version = version + 1,
                updated_at = CURRENT_TIMESTAMP,
                updated_by = %s
            WHERE mitglied_id = %s AND typ = %s AND ist_primaer AND deleted_at IS NULL
              AND (%s::int IS NULL OR id <> %s)
            """,
            (actor, mitglied_id, typ, exclude_id, exclude_id),
        )
