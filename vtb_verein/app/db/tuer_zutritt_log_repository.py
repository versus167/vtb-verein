"""Repository für den append-only Zutrittslog (aus v3/lockRecord/list oder importiert).

Idempotenter Sync über das eindeutige `ttlock_record_id` (= recordId der Cloud):
`insert_if_new` nutzt ON CONFLICT DO NOTHING. Zeilen aus einer Fremdanlage
(`quelle='extern'`) haben keine recordId und werden über Schloss + Zeitpunkt + Konto
dedupliziert (`insert_extern_if_new`). Kein Soft-Delete/History – Löschung nur über
das Prune-/DSGVO-Konzept.
"""
from typing import Optional

from psycopg.types.json import Json

from app.models.schliessanlage import TuerZutrittLog, QUELLE_EXTERN
from app.db.base_repository import BaseRepository

_SELECT = """
    SELECT l.id, l.ttlock_record_id, l.schloss_id, l.quelle, l.extern_konto,
           l.record_type, l.record_type_from_lock,
           l.methode, l.erfolg, l.credential, l.key_name, l.ttlock_username,
           l.chip_id, l.mitglied_id, l.lock_date, l.server_date, l.raw, l.created_at,
           s.name AS schloss_name, c.bezeichnung AS chip_bezeichnung,
           m.vorname AS mitglied_vorname, m.nachname AS mitglied_nachname
    FROM tuer_zutritt_log l
    LEFT JOIN tuer_schloss s ON s.id = l.schloss_id
    LEFT JOIN schluessel_chip c ON c.id = l.chip_id
    LEFT JOIN mitglied m ON m.id = l.mitglied_id
"""


def _map(row) -> TuerZutrittLog:
    return TuerZutrittLog(**dict(row))


class TuerZutrittLogRepository(BaseRepository):

    def insert_if_new(self, log: TuerZutrittLog) -> bool:
        """Fügt einen Log-Eintrag ein, falls die recordId noch nicht existiert.
        Gibt True zurück, wenn tatsächlich eingefügt wurde (für Sync-Statistik)."""
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tuer_zutritt_log
                    (ttlock_record_id, schloss_id, record_type, record_type_from_lock,
                     methode, erfolg, credential, key_name, ttlock_username,
                     chip_id, mitglied_id, lock_date, server_date, raw)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (ttlock_record_id) DO NOTHING
                RETURNING id
                """,
                (log.ttlock_record_id, log.schloss_id, log.record_type,
                 log.record_type_from_lock, log.methode, log.erfolg, log.credential,
                 log.key_name, log.ttlock_username, log.chip_id, log.mitglied_id,
                 log.lock_date, log.server_date,
                 Json(log.raw) if log.raw is not None else None),
            )
            return cur.fetchone() is not None

    def insert_extern_if_new(self, log: TuerZutrittLog) -> bool:
        """Importierte Fremd-Log-Zeile einfügen, falls es sie noch nicht gibt.
        Dedupe über den Unique-Index (schloss_id, lock_date, extern_konto) für
        quelle='extern' – derselbe Export lässt sich damit gefahrlos erneut einlesen."""
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tuer_zutritt_log
                    (quelle, extern_konto, schloss_id, record_type, methode, erfolg,
                     key_name, chip_id, mitglied_id, lock_date, raw)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING
                RETURNING id
                """,
                (QUELLE_EXTERN, log.extern_konto, log.schloss_id, log.record_type,
                 log.methode, log.erfolg, log.key_name, log.chip_id, log.mitglied_id,
                 log.lock_date, Json(log.raw) if log.raw is not None else None),
            )
            return cur.fetchone() is not None

    def extern_keys_for_schloss(self, schloss_id: int) -> set[tuple[str, str]]:
        """Bereits importierte (Zeitpunkt, Konto)-Paare eines Schlosses – Grundlage
        für die Vorschau „x neu, y bereits vorhanden", ohne etwas zu schreiben."""
        with self.cursor() as cur:
            cur.execute(
                "SELECT lock_date, COALESCE(extern_konto, '') AS extern_konto "
                "FROM tuer_zutritt_log WHERE schloss_id = %s AND quelle = %s",
                (schloss_id, QUELLE_EXTERN),
            )
            return {(r['lock_date'], r['extern_konto']) for r in cur.fetchall()}

    def resolve_extern_konto(self, konto: str, *, chip_id: int,
                             mitglied_id: Optional[int]) -> int:
        """Bereits importierte Zeilen eines Kontos nachträglich einem Chip zuordnen.

        Nötig, weil die Zuordnung typischerweise erst NACH dem ersten Import entsteht
        (der Bericht zeigt ja gerade die unbekannten Konten). Rührt nur Zeilen an, die
        noch keinen Chip haben – eine schon getroffene Zuordnung wird nie überschrieben.
        Gibt die Zahl der nachgezogenen Zeilen zurück."""
        if not (konto or "").strip():
            return 0
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE tuer_zutritt_log
                SET chip_id = %s, mitglied_id = COALESCE(%s, mitglied_id)
                WHERE quelle = %s AND chip_id IS NULL
                  AND lower(btrim(extern_konto)) = lower(btrim(%s))
                """,
                (chip_id, mitglied_id, QUELLE_EXTERN, konto),
            )
            return cur.rowcount

    def max_server_date(self, schloss_id: int) -> Optional[int]:
        """Sync-Cursor: jüngstes bereits gespeichertes serverDate je Schloss."""
        with self.cursor() as cur:
            cur.execute(
                "SELECT MAX(server_date) AS m FROM tuer_zutritt_log WHERE schloss_id = %s",
                (schloss_id,),
            )
            return cur.fetchone()['m']

    def list_neueste(self, limit: int = 100,
                     schloss_ids: Optional[list[int]] = None) -> list[TuerZutrittLog]:
        """Gesamt-Log über ALLE Schlösser, neueste zuerst; optional auf sichtbare
        Schlösser eingeschränkt (Abteilungs-Scope, Phase 3)."""
        where = ""
        params: list = []
        if schloss_ids is not None:
            if not schloss_ids:
                return []
            where = " WHERE l.schloss_id = ANY(%s)"
            params.append(list(schloss_ids))
        params.append(limit)
        with self.cursor() as cur:
            cur.execute(
                _SELECT + where + " ORDER BY l.lock_date DESC NULLS LAST, l.id DESC LIMIT %s",
                params,
            )
            return [_map(r) for r in cur.fetchall()]

    def list_for_schloss(self, schloss_id: int, limit: int = 200) -> list[TuerZutrittLog]:
        with self.cursor() as cur:
            cur.execute(
                _SELECT + " WHERE l.schloss_id = %s ORDER BY l.lock_date DESC NULLS LAST, l.id DESC "
                          "LIMIT %s",
                (schloss_id, limit),
            )
            return [_map(r) for r in cur.fetchall()]

    def list_for_chip(self, chip_id: int, limit: int = 200) -> list[TuerZutrittLog]:
        with self.cursor() as cur:
            cur.execute(
                _SELECT + " WHERE l.chip_id = %s ORDER BY l.lock_date DESC NULLS LAST, l.id DESC "
                          "LIMIT %s",
                (chip_id, limit),
            )
            return [_map(r) for r in cur.fetchall()]

    def list_for_mitglied(self, mitglied_id: int, limit: int = 50) -> list[TuerZutrittLog]:
        """Eigene Zutritte eines Mitglieds (Self-Service) – über die im Log aufgelöste
        mitglied_id (Kartennummer → Chip → Mitglied)."""
        with self.cursor() as cur:
            cur.execute(
                _SELECT + " WHERE l.mitglied_id = %s ORDER BY l.lock_date DESC NULLS LAST, l.id DESC "
                          "LIMIT %s",
                (mitglied_id, limit),
            )
            return [_map(r) for r in cur.fetchall()]
