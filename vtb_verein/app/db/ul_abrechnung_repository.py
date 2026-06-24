"""Repository für Übungsleiter-Abrechnungen (Header) und deren Einzeltermine.

Header/Detail-Modell analog gebuehr_forderung: ul_abrechnung (1 je ÜL + Abteilung +
Zeitraum) mit N ul_stunde-Zeilen. Status-Workflow + Fibu-Stempelspalten wie bei den
Gebühren-Forderungen.
"""
from typing import Optional

from app.models.ul_stunden import ULAbrechnung, ULStunde
from app.db.base_repository import BaseRepository


_SELECT = """
    SELECT a.id, a.mitglied_id, a.abteilung_id, a.zeitraum_von, a.zeitraum_bis,
           a.status, a.lizenz_klassifikation, a.foerder_klassifikation,
           a.verguetung_pro_stunde,
           a.eingereicht_am, a.eingereicht_von, a.bestaetigt_am, a.bestaetigt_von,
           a.abgelehnt_grund,
           a.exportiert_in_export_id, a.storno_exportiert_in_export_id,
           m.vorname AS mitglied_vorname, m.nachname AS mitglied_nachname,
           m.mitgliedsnummer AS mitgliedsnummer,
           m.iban AS mitglied_iban, m.kontoinhaber AS mitglied_kontoinhaber,
           ab.name AS abteilung_name, ab.kuerzel AS abteilung_kuerzel,
           a.version, a.created_at, a.created_by, a.updated_at, a.updated_by
    FROM ul_abrechnung a
    LEFT JOIN mitglied m ON m.id = a.mitglied_id
    LEFT JOIN abteilung ab ON ab.id = a.abteilung_id
"""

_SELECT_STUNDE = """
    SELECT id, abrechnung_id, datum, stunden, wochentag, angebot, bemerkung,
           version, created_at, created_by, updated_at, updated_by
    FROM ul_stunde
"""


def _map(row) -> ULAbrechnung:
    return ULAbrechnung(**dict(row))


def _map_stunde(row) -> ULStunde:
    return ULStunde(**dict(row))


class ULAbrechnungRepository(BaseRepository):

    # ------------------------------------------------------------------ Header
    def get(self, id: int) -> Optional[ULAbrechnung]:
        with self.cursor() as cur:
            cur.execute(_SELECT + " WHERE a.id = %s AND a.deleted_at IS NULL", (id,))
            row = cur.fetchone()
            return _map(row) if row else None

    def list_for_mitglied(self, mitglied_id: int, status: Optional[str] = None) -> list[ULAbrechnung]:
        where = "WHERE a.mitglied_id = %s AND a.deleted_at IS NULL"
        params: list = [mitglied_id]
        if status:
            where += " AND a.status = %s"
            params.append(status)
        with self.cursor() as cur:
            cur.execute(_SELECT + where + " ORDER BY a.zeitraum_bis DESC, a.id DESC", params)
            return [_map(r) for r in cur.fetchall()]

    def list_for_abteilungen(self, abteilung_ids: Optional[set[int]],
                             status: Optional[str] = None) -> list[ULAbrechnung]:
        """AL-Sicht. abteilung_ids None = alle Abteilungen (global berechtigt)."""
        where = "WHERE a.deleted_at IS NULL"
        params: list = []
        if abteilung_ids is not None:
            if not abteilung_ids:
                return []
            where += " AND a.abteilung_id = ANY(%s)"
            params.append(list(abteilung_ids))
        if status:
            where += " AND a.status = %s"
            params.append(status)
        with self.cursor() as cur:
            cur.execute(
                _SELECT + where + " ORDER BY a.zeitraum_bis DESC, m.nachname, m.vorname",
                params,
            )
            return [_map(r) for r in cur.fetchall()]

    def list_all(self, status: Optional[str] = None) -> list[ULAbrechnung]:
        return self.list_for_abteilungen(None, status)

    def create(self, a: ULAbrechnung, created_by: str) -> ULAbrechnung:
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ul_abrechnung
                    (mitglied_id, abteilung_id, zeitraum_von, zeitraum_bis, status,
                     lizenz_klassifikation, foerder_klassifikation, created_by, updated_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id
                """,
                (a.mitglied_id, a.abteilung_id, a.zeitraum_von, a.zeitraum_bis, a.status,
                 a.lizenz_klassifikation, a.foerder_klassifikation, created_by, created_by),
            )
            new_id = cur.fetchone()['id']
        return self.get(new_id)

    def update_kopf(self, a: ULAbrechnung, updated_by: str) -> bool:
        """Aktualisiert Kopfdaten – nur im Entwurf, optimistisch über version."""
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE ul_abrechnung
                SET zeitraum_von=%s, zeitraum_bis=%s, lizenz_klassifikation=%s,
                    foerder_klassifikation=%s, version=version+1,
                    updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id=%s AND version=%s AND status='entwurf' AND deleted_at IS NULL
                """,
                (a.zeitraum_von, a.zeitraum_bis, a.lizenz_klassifikation,
                 a.foerder_klassifikation, updated_by, a.id, a.version),
            )
            return cur.rowcount == 1

    def einreichen(self, id: int, *, verguetung_pro_stunde: Optional[float],
                   eingereicht_von: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE ul_abrechnung
                SET status='eingereicht', verguetung_pro_stunde=%s,
                    eingereicht_am=CURRENT_TIMESTAMP, eingereicht_von=%s,
                    abgelehnt_grund=NULL, version=version+1,
                    updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id=%s AND status='entwurf' AND deleted_at IS NULL
                """,
                (verguetung_pro_stunde, eingereicht_von, eingereicht_von, id),
            )
            return cur.rowcount == 1

    def bestaetigen(self, id: int, *, bestaetigt_von: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE ul_abrechnung
                SET status='bestaetigt',
                    bestaetigt_am=CURRENT_TIMESTAMP, bestaetigt_von=%s,
                    version=version+1, updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id=%s AND status='eingereicht' AND deleted_at IS NULL
                """,
                (bestaetigt_von, bestaetigt_von, id),
            )
            return cur.rowcount == 1

    def ablehnen(self, id: int, *, grund: Optional[str], abgelehnt_von: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE ul_abrechnung
                SET status='abgelehnt', abgelehnt_grund=%s,
                    version=version+1, updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id=%s AND status='eingereicht' AND deleted_at IS NULL
                """,
                (grund, abgelehnt_von, id),
            )
            return cur.rowcount == 1

    def zuruecksetzen(self, id: int, *, updated_by: str) -> bool:
        """Bestätigte/abgelehnte Abrechnung zurück auf 'entwurf' – nur solange
        noch nicht an die Fibu übergeben."""
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE ul_abrechnung
                SET status='entwurf', eingereicht_am=NULL, eingereicht_von=NULL,
                    bestaetigt_am=NULL, bestaetigt_von=NULL, verguetung_pro_stunde=NULL,
                    version=version+1, updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id=%s AND status IN ('eingereicht','bestaetigt','abgelehnt')
                  AND exportiert_in_export_id IS NULL AND deleted_at IS NULL
                """,
                (updated_by, id),
            )
            return cur.rowcount == 1

    def soft_delete(self, id: int, deleted_by: str) -> bool:
        """Nur Entwürfe (noch nicht eingereicht) löschbar."""
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE ul_abrechnung
                SET deleted_at=CURRENT_TIMESTAMP, deleted_by=%s,
                    version=version+1, updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id=%s AND status='entwurf' AND deleted_at IS NULL
                """,
                (deleted_by, deleted_by, id),
            )
            return cur.rowcount == 1

    # ------------------------------------------------------------- Sperr-Logik
    def max_gesperrt_bis(self, mitglied_id: int, abteilung_id: int) -> Optional[str]:
        """Spätestes zeitraum_bis über eingereichte/bestätigte Abrechnungen
        dieses ÜL in dieser Abteilung (= Sperr-Wasserzeichen). None = nichts gesperrt."""
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT MAX(zeitraum_bis) AS bis
                FROM ul_abrechnung
                WHERE mitglied_id=%s AND abteilung_id=%s
                  AND status IN ('eingereicht','bestaetigt') AND deleted_at IS NULL
                """,
                (mitglied_id, abteilung_id),
            )
            row = cur.fetchone()
            return row['bis'] if row and row['bis'] else None

    def has_overlap(self, mitglied_id: int, abteilung_id: int, von: str, bis: str,
                    exclude_id: Optional[int] = None) -> bool:
        """True, wenn sich [von,bis] mit einer aktiven (nicht abgelehnten,
        nicht gelöschten) Abrechnung desselben ÜL/derselben Abteilung überschneidet."""
        params: list = [mitglied_id, abteilung_id, bis, von]
        sql = """
            SELECT 1 FROM ul_abrechnung
            WHERE mitglied_id=%s AND abteilung_id=%s
              AND status <> 'abgelehnt' AND deleted_at IS NULL
              AND zeitraum_von <= %s AND zeitraum_bis >= %s
        """
        if exclude_id is not None:
            sql += " AND id <> %s"
            params.append(exclude_id)
        sql += " LIMIT 1"
        with self.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone() is not None

    # ----------------------------------------------------------------- Stunden
    def list_stunden(self, abrechnung_id: int) -> list[ULStunde]:
        with self.cursor() as cur:
            cur.execute(
                _SELECT_STUNDE + " WHERE abrechnung_id=%s AND deleted_at IS NULL "
                                 "ORDER BY datum, id",
                (abrechnung_id,),
            )
            return [_map_stunde(r) for r in cur.fetchall()]

    def get_stunde(self, stunde_id: int) -> Optional[ULStunde]:
        with self.cursor() as cur:
            cur.execute(_SELECT_STUNDE + " WHERE id=%s AND deleted_at IS NULL", (stunde_id,))
            row = cur.fetchone()
            return _map_stunde(row) if row else None

    def add_stunde(self, s: ULStunde, created_by: str) -> ULStunde:
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ul_stunde
                    (abrechnung_id, datum, stunden, wochentag, angebot, bemerkung,
                     created_by, updated_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id
                """,
                (s.abrechnung_id, s.datum, s.stunden, s.wochentag, s.angebot, s.bemerkung,
                 created_by, created_by),
            )
            new_id = cur.fetchone()['id']
        return self.get_stunde(new_id)

    def update_stunde(self, s: ULStunde, updated_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE ul_stunde
                SET datum=%s, stunden=%s, wochentag=%s, angebot=%s, bemerkung=%s,
                    version=version+1, updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id=%s AND deleted_at IS NULL
                """,
                (s.datum, s.stunden, s.wochentag, s.angebot, s.bemerkung, updated_by, s.id),
            )
            return cur.rowcount == 1

    def delete_stunde(self, stunde_id: int, deleted_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE ul_stunde
                SET deleted_at=CURRENT_TIMESTAMP, deleted_by=%s,
                    version=version+1, updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id=%s AND deleted_at IS NULL
                """,
                (deleted_by, deleted_by, stunde_id),
            )
            return cur.rowcount == 1
