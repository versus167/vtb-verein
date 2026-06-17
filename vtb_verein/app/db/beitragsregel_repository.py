"""Repository für Beitragsregeln."""
from typing import Optional
from app.models.beitrag import Beitragsregel
from app.db.base_repository import BaseRepository

_SELECT = """
    SELECT r.id, r.name, r.abteilung_id, a.name AS abteilung_name,
           r.betrag_pro_monat, r.einzug_turnus,
           r.gueltig_ab, r.gueltig_bis,
           r.bedingung_raw, r.bedingung_abteilung_status,
           r.bedingung_funktionen, r.bedingung_funktion_abteilung_id,
           r.ausnahme_funktionen, r.ausnahme_abteilung_ids,
           r.bedingung_alter_min, r.bedingung_alter_max,
           r.zahler_typ,
           r.version, r.created_at, r.created_by, r.updated_at, r.updated_by
    FROM beitragsregel r
    LEFT JOIN abteilung a ON a.id = r.abteilung_id AND a.deleted_at IS NULL
"""


def _map(row) -> Beitragsregel:
    r = dict(row)
    return Beitragsregel(
        id=r['id'], name=r['name'],
        abteilung_id=r['abteilung_id'], abteilung_name=r['abteilung_name'],
        betrag_pro_monat=r['betrag_pro_monat'], einzug_turnus=r['einzug_turnus'],
        gueltig_ab=r['gueltig_ab'], gueltig_bis=r['gueltig_bis'],
        bedingung_raw=r['bedingung_raw'],
        bedingung_abteilung_status=r['bedingung_abteilung_status'],
        bedingung_funktionen=r['bedingung_funktionen'] or [],
        bedingung_funktion_abteilung_id=r['bedingung_funktion_abteilung_id'],
        ausnahme_funktionen=r['ausnahme_funktionen'] or [],
        ausnahme_abteilung_ids=r['ausnahme_abteilung_ids'] or [],
        bedingung_alter_min=r['bedingung_alter_min'],
        bedingung_alter_max=r['bedingung_alter_max'],
        zahler_typ=r['zahler_typ'],
        version=r['version'], created_at=r['created_at'], created_by=r['created_by'],
        updated_at=r['updated_at'], updated_by=r['updated_by'],
    )


class BeitragsregelRepository(BaseRepository):

    def list_all(self) -> list[Beitragsregel]:
        with self.cursor() as cur:
            cur.execute(_SELECT + " WHERE r.deleted_at IS NULL ORDER BY r.name")
            return [_map(row) for row in cur.fetchall()]

    def list_aktive(self, stichtag: str) -> list[Beitragsregel]:
        """Regeln die am Stichtag gültig sind."""
        with self.cursor() as cur:
            cur.execute(
                _SELECT + """
                WHERE r.deleted_at IS NULL
                  AND r.gueltig_ab <= %s
                  AND (r.gueltig_bis IS NULL OR r.gueltig_bis >= %s)
                ORDER BY r.name
                """,
                (stichtag, stichtag),
            )
            return [_map(row) for row in cur.fetchall()]

    def get(self, id: int) -> Optional[Beitragsregel]:
        with self.cursor() as cur:
            cur.execute(_SELECT + " WHERE r.id = %s AND r.deleted_at IS NULL", (id,))
            row = cur.fetchone()
            return _map(row) if row else None

    def create(self, r: Beitragsregel, created_by: str) -> Beitragsregel:
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO beitragsregel (
                    name, abteilung_id, betrag_pro_monat, einzug_turnus,
                    gueltig_ab, gueltig_bis, bedingung_raw, bedingung_abteilung_status,
                    bedingung_funktionen, bedingung_funktion_abteilung_id,
                    ausnahme_funktionen, ausnahme_abteilung_ids,
                    bedingung_alter_min, bedingung_alter_max,
                    zahler_typ, created_by, updated_by
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::integer[],%s,%s,%s,%s,%s)
                RETURNING id
                """,
                (r.name, r.abteilung_id, r.betrag_pro_monat, r.einzug_turnus,
                 r.gueltig_ab, r.gueltig_bis, r.bedingung_raw, r.bedingung_abteilung_status,
                 r.bedingung_funktionen, r.bedingung_funktion_abteilung_id,
                 r.ausnahme_funktionen, r.ausnahme_abteilung_ids,
                 r.bedingung_alter_min, r.bedingung_alter_max,
                 r.zahler_typ, created_by, created_by),
            )
            new_id = cur.fetchone()['id']
        return self.get(new_id)

    def update(self, r: Beitragsregel, updated_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE beitragsregel
                SET name=%s, abteilung_id=%s, betrag_pro_monat=%s, einzug_turnus=%s,
                    gueltig_ab=%s, gueltig_bis=%s,
                    bedingung_raw=%s, bedingung_abteilung_status=%s,
                    bedingung_funktionen=%s, bedingung_funktion_abteilung_id=%s,
                    ausnahme_funktionen=%s, ausnahme_abteilung_ids=%s::integer[],
                    bedingung_alter_min=%s, bedingung_alter_max=%s,
                    zahler_typ=%s,
                    version=version+1, updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id=%s AND version=%s AND deleted_at IS NULL
                """,
                (r.name, r.abteilung_id, r.betrag_pro_monat, r.einzug_turnus,
                 r.gueltig_ab, r.gueltig_bis,
                 r.bedingung_raw, r.bedingung_abteilung_status,
                 r.bedingung_funktionen, r.bedingung_funktion_abteilung_id,
                 r.ausnahme_funktionen, r.ausnahme_abteilung_ids,
                 r.bedingung_alter_min, r.bedingung_alter_max,
                 r.zahler_typ,
                 updated_by, r.id, r.version),
            )
            return cur.rowcount > 0

    def mark_deleted(self, id: int, deleted_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE beitragsregel
                SET deleted_at=CURRENT_TIMESTAMP, deleted_by=%s, version=version+1
                WHERE id=%s AND deleted_at IS NULL
                """,
                (deleted_by, id),
            )
            return cur.rowcount > 0
