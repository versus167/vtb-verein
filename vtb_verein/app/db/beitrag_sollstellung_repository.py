"""Repository für Beitrag-Sollstellungen."""
from typing import Optional
from app.models.beitrag import BeitragSollstellung
from app.db.base_repository import BaseRepository

_SELECT = """
    SELECT s.id, s.mitglied_id, s.beitragsregel_id, s.zeitraum,
           s.betrag_soll, s.faelligkeitsdatum, s.status, s.bezahlt_am,
           s.kassenbuchung_id,
           s.exportiert_in_export_id, s.storno_exportiert_in_export_id,
           m.vorname AS mitglied_vorname, m.nachname AS mitglied_nachname,
           m.iban AS mitglied_iban, m.kontoinhaber AS mitglied_kontoinhaber,
           r.name AS beitragsregel_name, r.zahler_typ,
           s.version, s.created_at, s.created_by, s.updated_at, s.updated_by
    FROM beitrag_sollstellung s
    JOIN mitglied m ON m.id = s.mitglied_id
    JOIN beitragsregel r ON r.id = s.beitragsregel_id
"""


def _map(row) -> BeitragSollstellung:
    r = dict(row)
    return BeitragSollstellung(
        id=r['id'], mitglied_id=r['mitglied_id'], beitragsregel_id=r['beitragsregel_id'],
        zeitraum=r['zeitraum'], betrag_soll=r['betrag_soll'],
        faelligkeitsdatum=r['faelligkeitsdatum'], status=r['status'],
        bezahlt_am=r['bezahlt_am'], kassenbuchung_id=r['kassenbuchung_id'],
        exportiert_in_export_id=r['exportiert_in_export_id'],
        storno_exportiert_in_export_id=r['storno_exportiert_in_export_id'],
        mitglied_vorname=r['mitglied_vorname'], mitglied_nachname=r['mitglied_nachname'],
        mitglied_iban=r['mitglied_iban'], mitglied_kontoinhaber=r['mitglied_kontoinhaber'],
        beitragsregel_name=r['beitragsregel_name'], zahler_typ=r['zahler_typ'],
        version=r['version'], created_at=r['created_at'], created_by=r['created_by'],
        updated_at=r['updated_at'], updated_by=r['updated_by'],
    )


class BeitragSollstellungRepository(BaseRepository):

    def list_by_zeitraum(self, zeitraum: str) -> list[BeitragSollstellung]:
        with self.cursor() as cur:
            cur.execute(_SELECT + " WHERE s.zeitraum=%s AND s.deleted_at IS NULL ORDER BY m.nachname, m.vorname", (zeitraum,))
            return [_map(row) for row in cur.fetchall()]

    def list_by_mitglied(self, mitglied_id: int) -> list[BeitragSollstellung]:
        with self.cursor() as cur:
            cur.execute(_SELECT + " WHERE s.mitglied_id=%s AND s.deleted_at IS NULL ORDER BY s.zeitraum DESC", (mitglied_id,))
            return [_map(row) for row in cur.fetchall()]

    def exists(self, mitglied_id: int, beitragsregel_id: int, zeitraum: str) -> bool:
        """Duplikat-Schutz: wurde diese Sollstellung bereits angelegt?"""
        with self.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM beitrag_sollstellung WHERE mitglied_id=%s AND beitragsregel_id=%s AND zeitraum=%s AND deleted_at IS NULL LIMIT 1",
                (mitglied_id, beitragsregel_id, zeitraum),
            )
            return cur.fetchone() is not None

    def list_zeitraeume(self) -> list[str]:
        """Vorhandene Zeiträume (distinct) für das Filter-Dropdown, neueste zuerst."""
        with self.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT zeitraum FROM beitrag_sollstellung "
                "WHERE deleted_at IS NULL ORDER BY zeitraum DESC"
            )
            return [row['zeitraum'] for row in cur.fetchall()]

    def create(self, s: BeitragSollstellung, created_by: str) -> BeitragSollstellung:
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO beitrag_sollstellung (
                    mitglied_id, beitragsregel_id, zeitraum, betrag_soll,
                    faelligkeitsdatum, status, created_by, updated_by
                ) VALUES (%s,%s,%s,%s,%s,'offen',%s,%s)
                RETURNING id
                """,
                (s.mitglied_id, s.beitragsregel_id, s.zeitraum, s.betrag_soll,
                 s.faelligkeitsdatum, created_by, created_by),
            )
            new_id = cur.fetchone()['id']
        return self.get(new_id)

    def get(self, id: int) -> Optional[BeitragSollstellung]:
        with self.cursor() as cur:
            cur.execute(_SELECT + " WHERE s.id=%s AND s.deleted_at IS NULL", (id,))
            row = cur.fetchone()
            return _map(row) if row else None

    def mark_bezahlt(self, id: int, bezahlt_am: str, updated_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE beitrag_sollstellung
                SET status='bezahlt', bezahlt_am=%s,
                    version=version+1, updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id=%s AND status='offen' AND deleted_at IS NULL
                """,
                (bezahlt_am, updated_by, id),
            )
            return cur.rowcount > 0

    def mark_storniert(self, id: int, updated_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE beitrag_sollstellung
                SET status='storniert',
                    version=version+1, updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id=%s AND deleted_at IS NULL
                """,
                (updated_by, id),
            )
            return cur.rowcount > 0

    def soft_delete(self, id: int, deleted_by: str) -> bool:
        """Sollstellung soft-löschen (deleted_at), damit eine erneute Abrechnung
        sie wieder neu anlegt. Im Gegensatz zum Storno (bleibt bestehen und
        sperrt die Neu-Anlage über exists()). Nur offene/stornierte – bezahlte
        bleiben vorerst gesperrt (bereits bezahlt; werden nicht neu abgerechnet).
        Hinweis: Im Beitragsflow werden keine Kassenbuchungen erzeugt; wie
        'bezahlt' hier abgebildet wird, ist noch offen."""
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE beitrag_sollstellung
                SET deleted_at=CURRENT_TIMESTAMP, deleted_by=%s,
                    version=version+1, updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id=%s AND deleted_at IS NULL AND status IN ('offen','storniert')
                """,
                (deleted_by, deleted_by, id),
            )
            return cur.rowcount > 0

    def set_kassenbuchung(self, id: int, kassenbuchung_id: int, updated_by: str) -> None:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE beitrag_sollstellung
                SET kassenbuchung_id=%s, status='bezahlt',
                    version=version+1, updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id=%s AND deleted_at IS NULL
                """,
                (kassenbuchung_id, updated_by, id),
            )
