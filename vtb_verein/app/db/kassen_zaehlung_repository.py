'''
KassenZaehlungRepository – Zählprotokolle (Kassensturz / Stückelung).

Jede Zählung hält die gezählte Stückelung (JSONB: Cent-Wert → Anzahl) sowie den
Soll-/Ist-Abgleich und verweist auf die erzeugte „Zähl-Buchung" (Träger des
Protokoll-PDFs). Soft-Delete-only (deleted_at); History via DB-Trigger.
'''

from psycopg.types.json import Jsonb

from app.models.kasse import KassenZaehlung
from app.db.base_repository import BaseRepository

_COLS = (
    "id, kasse_id, buchung_id, ausloesende_buchung_id, stueckelung, "
    "ist_cent, soll_cent, differenz_cent, notiz, version, "
    "created_at, created_by, updated_at, updated_by, deleted_at, deleted_by"
)


class KassenZaehlungRepository(BaseRepository):
    """Repository für Kassenzählungen (Zählprotokolle)."""

    # -----------------------------------
    # Read
    # -----------------------------------

    def get(self, zaehlung_id: int) -> KassenZaehlung | None:
        with self.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM kassen_zaehlungen WHERE id = %s",
                (zaehlung_id,),
            )
            row = cur.fetchone()
            return KassenZaehlung(**dict(row)) if row else None

    def list_for_kasse(self, kasse_id: int) -> list[KassenZaehlung]:
        """Aktive Zählungen einer Kasse, neueste zuerst."""
        with self.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM kassen_zaehlungen "
                f"WHERE kasse_id = %s AND deleted_at IS NULL "
                f"ORDER BY created_at DESC, id DESC",
                (kasse_id,),
            )
            return [KassenZaehlung(**dict(r)) for r in cur.fetchall()]

    # -----------------------------------
    # Write
    # -----------------------------------

    def create(self, zaehlung: KassenZaehlung, created_by: str) -> KassenZaehlung:
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO kassen_zaehlungen (
                    kasse_id, buchung_id, ausloesende_buchung_id, stueckelung,
                    ist_cent, soll_cent, differenz_cent, notiz, created_by, updated_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    zaehlung.kasse_id, zaehlung.buchung_id, zaehlung.ausloesende_buchung_id,
                    Jsonb(zaehlung.stueckelung or {}),
                    zaehlung.ist_cent, zaehlung.soll_cent, zaehlung.differenz_cent,
                    zaehlung.notiz, created_by, created_by,
                ),
            )
            new_id = cur.fetchone()["id"]
        return self.get(new_id)

    def mark_deleted(self, zaehlung_id: int, deleted_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE kassen_zaehlungen
                SET deleted_at = CURRENT_TIMESTAMP, deleted_by = %s, version = version + 1
                WHERE id = %s AND deleted_at IS NULL
                """,
                (deleted_by, zaehlung_id),
            )
            return cur.rowcount > 0
