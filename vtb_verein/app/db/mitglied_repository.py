'''
Created on 21.02.2026

Mitglied Repository - All database operations for Mitglied entity.

@author: AI Assistant
'''

from typing import Optional
from psycopg import Connection as PgConnection
from app.models.mitglied import Mitglied
from app.db.base_repository import BaseRepository


# Spaltenliste für SELECTs. email/telefon sind seit Schema v24 keine Spalten mehr,
# sondern werden aus dem jeweils primären Kontakt (mitglied_kontakt) abgeleitet, damit
# Mitglied.email / Mitglied.telefon weiterhin den Primärkontakt liefern.
_MITGLIED_COLS = """
        id, mitgliedsnummer, vorname, nachname, geburtsdatum,
        strasse, plz, ort, land,
        (SELECT k.wert FROM mitglied_kontakt k
           WHERE k.mitglied_id = mitglied.id AND k.typ = 'email'
             AND k.ist_primaer AND k.deleted_at IS NULL LIMIT 1) AS email,
        (SELECT k.wert FROM mitglied_kontakt k
           WHERE k.mitglied_id = mitglied.id AND k.typ = 'telefon'
             AND k.ist_primaer AND k.deleted_at IS NULL LIMIT 1) AS telefon,
        eintrittsdatum, austrittsdatum, status,
        zahlungsart, iban, bic, kontoinhaber, abgerechnet_bis,
        geschlecht, bemerkungen, sepa_mandatsref, sepa_mandatsdatum,
        trainerlizenz_nr, qualifikation, trainerlizenz_gueltig_bis, trainerlizenz_gueltig_von,
        user_id, version, created_at, created_by, updated_at, updated_by
"""


class MitgliedRepository(BaseRepository):
    """Repository for Mitglied CRUD operations.

    Handles:
    - Create, Read, Update operations
    - Soft-delete (mark as deleted)
    - Mitgliedsnummer management
    - History tracking (via database triggers)
    """

    def get_next_mitgliedsnummer(self) -> int:
        """Get the next available Mitgliedsnummer.

        Returns the highest mitgliedsnummer + 1, including deleted members.
        Starts at 1 if no members exist.
        """
        with self.cursor() as cur:
            cur.execute("SELECT MAX(mitgliedsnummer) FROM mitglied")
            result = cur.fetchone()['max']
            return (result + 1) if result is not None else 1

    def is_mitgliedsnummer_available(self, nummer: int, exclude_id: int = None) -> bool:
        """Check if a Mitgliedsnummer is available.

        Args:
            nummer: The Mitgliedsnummer to check
            exclude_id: Optional member ID to exclude from check (for updates)

        Returns:
            bool: True if nummer is available, False if already in use
        """
        with self.cursor() as cur:
            if exclude_id:
                cur.execute(
                    "SELECT 1 FROM mitglied WHERE mitgliedsnummer = %s AND id != %s LIMIT 1",
                    (nummer, exclude_id)
                )
            else:
                cur.execute(
                    "SELECT 1 FROM mitglied WHERE mitgliedsnummer = %s LIMIT 1",
                    (nummer,)
                )
            return cur.fetchone() is None

    def get_mitglied(self, id: int) -> Mitglied:
        """Get a single Mitglied by ID (only non-deleted)."""
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_MITGLIED_COLS}
                FROM mitglied
                WHERE id = %s AND deleted_at IS NULL
                """,
                (id,),
            )
            row = cur.fetchone()
            if row is None:
                raise KeyError(f"Mitglied {id} nicht gefunden")
            return Mitglied(**dict(row))

    def list_mitglieder(self) -> list[Mitglied]:
        """List all active (non-deleted) Mitglieder."""
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_MITGLIED_COLS}
                FROM mitglied
                WHERE deleted_at IS NULL
                ORDER BY nachname, vorname
                """
            )
            return [Mitglied(**dict(row)) for row in cur.fetchall()]

    def list_mitglieder_for_standard_view(self) -> list[tuple[Mitglied, bool]]:
        """List Mitglieder for standard view (active + recently left).

        Returns members that:
        - Have no austrittsdatum (active members), OR
        - Have austrittsdatum within the last 6 months

        Returns:
            list[tuple[Mitglied, bool]]: List of (member, recently_left) tuples
                where recently_left=True for members who left within 6 months
        """
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_MITGLIED_COLS},
                       CASE
                           WHEN austrittsdatum IS NOT NULL
                                AND austrittsdatum >= CURRENT_DATE - INTERVAL '6 months'
                           THEN 1
                           ELSE 0
                       END as recently_left
                FROM mitglied
                WHERE deleted_at IS NULL
                  AND (
                      austrittsdatum IS NULL
                      OR austrittsdatum >= CURRENT_DATE - INTERVAL '6 months'
                  )
                ORDER BY nachname, vorname
                """
            )
            results = []
            for row in cur.fetchall():
                row_dict = dict(row)
                recently_left = bool(row_dict.pop('recently_left'))
                mitglied = Mitglied(**row_dict)
                results.append((mitglied, recently_left))
            return results

    def create_mitglied(self, mitglied: Mitglied, created_by: str) -> Mitglied:
        """Create a new Mitglied.

        If mitgliedsnummer is None, automatically assigns the next available number.
        History is written automatically via trigger.

        Kontaktdaten (email/telefon) werden NICHT hier gespeichert, sondern separat
        über das MitgliedKontaktRepository (Schema v24, voll normalisiert).
        """
        with self.cursor() as cur:
            # Auto-assign mitgliedsnummer if not provided
            if mitglied.mitgliedsnummer is None:
                mitglied.mitgliedsnummer = self.get_next_mitgliedsnummer()

            cur.execute(
                """
                INSERT INTO mitglied (
                    mitgliedsnummer, vorname, nachname, geburtsdatum,
                    strasse, plz, ort, land,
                    eintrittsdatum, austrittsdatum, status,
                    zahlungsart, iban, bic, kontoinhaber, abgerechnet_bis,
                    geschlecht, bemerkungen, sepa_mandatsref, sepa_mandatsdatum,
                    trainerlizenz_nr, qualifikation, trainerlizenz_gueltig_bis, trainerlizenz_gueltig_von,
                    user_id, created_by, updated_at, updated_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, %s)
                RETURNING id
                """,
                (
                    mitglied.mitgliedsnummer, mitglied.vorname, mitglied.nachname, mitglied.geburtsdatum,
                    mitglied.strasse, mitglied.plz, mitglied.ort, mitglied.land,
                    mitglied.eintrittsdatum, mitglied.austrittsdatum, mitglied.status,
                    mitglied.zahlungsart, mitglied.iban, mitglied.bic, mitglied.kontoinhaber, mitglied.abgerechnet_bis,
                    mitglied.geschlecht, mitglied.bemerkungen, mitglied.sepa_mandatsref, mitglied.sepa_mandatsdatum,
                    mitglied.trainerlizenz_nr, mitglied.qualifikation, mitglied.trainerlizenz_gueltig_bis,
                    mitglied.trainerlizenz_gueltig_von,
                    mitglied.user_id, created_by, created_by
                ),
            )
            mitglied.id = cur.fetchone()['id']

            # Fetch complete created record
            cur.execute(
                f"""
                SELECT {_MITGLIED_COLS}
                FROM mitglied
                WHERE id = %s
                """,
                (mitglied.id,),
            )
            row = cur.fetchone()
            return Mitglied(**dict(row))

    def update_mitglied(self, mitglied: Mitglied, updated_by: str) -> bool:
        """Update a Mitglied. History is written automatically via trigger.

        Kontaktdaten (email/telefon) werden separat über das MitgliedKontaktRepository
        gepflegt und hier nicht berührt.

        Returns:
            bool: True if update successful, False if version conflict or not found
        """
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE mitglied
                SET mitgliedsnummer = %s, vorname = %s, nachname = %s, geburtsdatum = %s,
                    strasse = %s, plz = %s, ort = %s, land = %s,
                    eintrittsdatum = %s, austrittsdatum = %s, status = %s,
                    zahlungsart = %s, iban = %s, bic = %s, kontoinhaber = %s, abgerechnet_bis = %s,
                    geschlecht = %s, bemerkungen = %s, sepa_mandatsref = %s, sepa_mandatsdatum = %s,
                    trainerlizenz_nr = %s, qualifikation = %s, trainerlizenz_gueltig_bis = %s,
                    trainerlizenz_gueltig_von = %s,
                    user_id = %s,
                    version = version + 1,
                    updated_at = CURRENT_TIMESTAMP,
                    updated_by = %s
                WHERE id = %s AND version = %s AND deleted_at IS NULL
                """,
                (
                    mitglied.mitgliedsnummer, mitglied.vorname, mitglied.nachname, mitglied.geburtsdatum,
                    mitglied.strasse, mitglied.plz, mitglied.ort, mitglied.land,
                    mitglied.eintrittsdatum, mitglied.austrittsdatum, mitglied.status,
                    mitglied.zahlungsart, mitglied.iban, mitglied.bic, mitglied.kontoinhaber, mitglied.abgerechnet_bis,
                    mitglied.geschlecht, mitglied.bemerkungen, mitglied.sepa_mandatsref, mitglied.sepa_mandatsdatum,
                    mitglied.trainerlizenz_nr, mitglied.qualifikation, mitglied.trainerlizenz_gueltig_bis,
                    mitglied.trainerlizenz_gueltig_von,
                    mitglied.user_id,
                    updated_by, mitglied.id, mitglied.version
                ),
            )
            if cur.rowcount == 0:
                return False

            # Get new state
            cur.execute(
                """
                SELECT version, updated_at
                FROM mitglied
                WHERE id = %s
                """,
                (mitglied.id,),
            )
            row = cur.fetchone()
            mitglied.version = row["version"]
            mitglied.updated_at = row["updated_at"]
            mitglied.updated_by = updated_by
            return True

    def get_by_user_id(self, user_id: int) -> Optional[Mitglied]:
        """Gibt den Mitglied-Datensatz zurück, der mit einem User verknüpft ist."""
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_MITGLIED_COLS}
                FROM mitglied
                WHERE user_id = %s AND deleted_at IS NULL
                """,
                (user_id,),
            )
            row = cur.fetchone()
            return Mitglied(**dict(row)) if row else None

    def get_history(self, mitglied_id: int) -> list[dict]:
        """Gibt alle History-Einträge eines Mitglieds zurück (für Änderungsanzeige).

        Hinweis: mitglied_history behält die eingefrorenen Spalten email/telefon für
        Datensätze vor Schema v24; neuere Kontaktänderungen stehen in mitglied_kontakt_history.
        """
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT id, version, mitgliedsnummer, vorname, nachname, geburtsdatum,
                       geschlecht, strasse, plz, ort, land, email, telefon,
                       eintrittsdatum, austrittsdatum, status,
                       zahlungsart, iban, bic, kontoinhaber, abgerechnet_bis,
                       user_id, created_at, created_by, updated_at, updated_by,
                       deleted_at, deleted_by
                FROM mitglied_history
                WHERE id = %s
                ORDER BY version ASC
                """,
                (mitglied_id,),
            )
            return [dict(row) for row in cur.fetchall()]

    def mark_mitglied_deleted(self, mitglied_id: int, deleted_by: str) -> bool:
        """Soft-delete: Mark Mitglied as deleted.

        Note: Does NOT check for dependencies - that's business logic in the service layer.

        Returns:
            bool: True if marked as deleted, False if not found or already deleted
        """
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE mitglied
                SET deleted_at = CURRENT_TIMESTAMP,
                    deleted_by = %s,
                    version = version + 1
                WHERE id = %s AND deleted_at IS NULL
                """,
                (deleted_by, mitglied_id)
            )
            return cur.rowcount == 1

    def restore_mitglied(self, mitglied_id: int, restored_by: str) -> bool:
        """Hebt einen Soft-Delete eines Mitglieds auf (deleted_at/deleted_by → NULL).

        History wird per Trigger geschrieben.

        Returns:
            bool: True wenn wiederhergestellt, False wenn nicht gefunden oder nicht gelöscht
        """
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE mitglied
                SET deleted_at = NULL,
                    deleted_by = NULL,
                    version = version + 1,
                    updated_at = CURRENT_TIMESTAMP,
                    updated_by = %s
                WHERE id = %s AND deleted_at IS NOT NULL
                """,
                (restored_by, mitglied_id)
            )
            return cur.rowcount == 1

    def restore_mitglied_by_user_id(self, user_id: int, restored_by: str) -> bool:
        """Stellt den (gelöschten) Mitglied-Datensatz eines Users wieder her.

        Nötig beim Wiederherstellen einer Person: get_by_user_id blendet gelöschte
        Datensätze aus, daher hier direkt über user_id.

        Returns:
            bool: True wenn ein gelöschtes Mitglied reaktiviert wurde
        """
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE mitglied
                SET deleted_at = NULL,
                    deleted_by = NULL,
                    version = version + 1,
                    updated_at = CURRENT_TIMESTAMP,
                    updated_by = %s
                WHERE user_id = %s AND deleted_at IS NOT NULL
                """,
                (restored_by, user_id)
            )
            return cur.rowcount == 1
