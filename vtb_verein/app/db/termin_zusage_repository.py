"""Repository für Termin-Zusagen (RSVP, #95 Spielbetrieb Etappe 2).

Je Termin höchstens eine aktive Antwort pro Kader-Mitglied – erzwungen über den
partiellen Unique-Index uix_termin_zusage_active (termin_id, mitglied_id) WHERE
deleted_at IS NULL. Setzen ist ein Upsert: existiert eine aktive Zeile, wird sie per
UPDATE fortgeschrieben (version+1 → History-Trigger); sonst eine neue angelegt.
Zurücknehmen = Soft-Delete. Zugriff/ACL (wer für wen setzen darf) entscheidet die
API-Schicht über die Kader-Zugehörigkeit (siehe TerminRepository)."""
from app.models.termin_zusage import TerminZusage
from app.db.base_repository import BaseRepository


VALID_ANTWORTEN = ('zu', 'vielleicht', 'ab')

_COLS = ("id, termin_id, mitglied_id, antwort, kommentar, version, "
         "created_at, created_by, updated_at, updated_by, deleted_at, deleted_by")


def _map(row) -> TerminZusage:
    return TerminZusage(
        id=row['id'], termin_id=row['termin_id'], mitglied_id=row['mitglied_id'],
        antwort=row['antwort'], kommentar=row['kommentar'], version=row['version'],
        created_at=row['created_at'], created_by=row['created_by'],
        updated_at=row['updated_at'], updated_by=row['updated_by'],
        deleted_at=row['deleted_at'], deleted_by=row['deleted_by'],
    )


class TerminZusageRepository(BaseRepository):

    # ---------------------------------------------------------------- schreiben
    def set_antwort(self, termin_id: int, mitglied_id: int, antwort: str,
                    kommentar: str | None, gesetzt_von: str) -> TerminZusage:
        """Setzt/ändert die Antwort eines Mitglieds zu einem Termin (Upsert).

        Aktive Zeile -> UPDATE (version+1, Audit-Trigger schreibt History); keine
        aktive Zeile -> INSERT. Eine zuvor zurückgenommene (soft-gelöschte) Antwort
        bleibt bestehen; die neue aktive Zeile ist eindeutig (partieller Unique)."""
        with self.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO termin_zusage (termin_id, mitglied_id, antwort, kommentar,
                                           created_by, updated_by)
                VALUES (%(t)s, %(m)s, %(a)s, %(k)s, %(u)s, %(u)s)
                ON CONFLICT (termin_id, mitglied_id) WHERE deleted_at IS NULL
                DO UPDATE SET antwort = EXCLUDED.antwort, kommentar = EXCLUDED.kommentar,
                              updated_at = CURRENT_TIMESTAMP, updated_by = EXCLUDED.updated_by,
                              version = termin_zusage.version + 1
                RETURNING {_COLS}
                """,
                {"t": termin_id, "m": mitglied_id, "a": antwort,
                 "k": kommentar, "u": gesetzt_von},
            )
            return _map(cur.fetchone())

    def remove_antwort(self, termin_id: int, mitglied_id: int, deleted_by: str) -> bool:
        """Nimmt die (aktive) Antwort eines Mitglieds zurück (Soft-Delete)."""
        with self.cursor() as cur:
            cur.execute(
                "UPDATE termin_zusage SET deleted_at = CURRENT_TIMESTAMP, "
                "deleted_by = %s, version = version + 1 "
                "WHERE termin_id = %s AND mitglied_id = %s AND deleted_at IS NULL",
                (deleted_by, termin_id, mitglied_id),
            )
            return cur.rowcount > 0

    # ------------------------------------------------------------------- lesen
    def counts_for_termine(self, termin_ids: list[int]) -> dict[int, dict]:
        """Aggregat je Termin: {'zu': n, 'vielleicht': n, 'ab': n} (nur aktive)."""
        result = {tid: {'zu': 0, 'vielleicht': 0, 'ab': 0} for tid in termin_ids}
        if not termin_ids:
            return result
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT termin_id, antwort, COUNT(*) AS n
                FROM termin_zusage
                WHERE termin_id = ANY(%s) AND deleted_at IS NULL
                GROUP BY termin_id, antwort
                """,
                (list(termin_ids),),
            )
            for r in cur.fetchall():
                result[r['termin_id']][r['antwort']] = r['n']
        return result

    def answer_for(self, mitglied_id: int, termin_ids: list[int]) -> dict[int, str]:
        """Aktive Antwort eines Mitglieds je Termin (zum Hervorheben der eigenen Wahl)."""
        if not termin_ids:
            return {}
        with self.cursor() as cur:
            cur.execute(
                "SELECT termin_id, antwort FROM termin_zusage "
                "WHERE mitglied_id = %s AND termin_id = ANY(%s) AND deleted_at IS NULL",
                (mitglied_id, list(termin_ids)),
            )
            return {r['termin_id']: r['antwort'] for r in cur.fetchall()}

    def list_kader_with_zusage(self, termin_id: int) -> list[dict]:
        """Aktiver Kader der Termin-Mannschaft (Stichtag = Termin-Datum) inkl. der
        jeweiligen Antwort (None = offen). Mehrfach-Rollen werden zusammengefasst."""
        with self.cursor() as cur:
            cur.execute(
                """
                WITH t AS (
                    SELECT mannschaft_id, LEFT(beginn, 10) AS tag
                    FROM termine WHERE id = %(tid)s AND deleted_at IS NULL
                )
                SELECT m.id AS mitglied_id, m.vorname, m.nachname,
                       string_agg(DISTINCT mm.rolle, ', ' ORDER BY mm.rolle) AS rollen,
                       z.antwort
                FROM t
                JOIN mitglied_mannschaft mm ON mm.mannschaft_id = t.mannschaft_id
                    AND mm.deleted_at IS NULL
                    AND mm.von <= t.tag AND (mm.bis IS NULL OR mm.bis >= t.tag)
                JOIN mitglied m ON m.id = mm.mitglied_id AND m.deleted_at IS NULL
                LEFT JOIN termin_zusage z ON z.termin_id = %(tid)s
                    AND z.mitglied_id = m.id AND z.deleted_at IS NULL
                GROUP BY m.id, m.vorname, m.nachname, z.antwort
                ORDER BY lower(m.nachname), lower(m.vorname)
                """,
                {"tid": termin_id},
            )
            return [
                {"mitglied_id": r['mitglied_id'],
                 "name": f"{r['vorname'] or ''} {r['nachname'] or ''}".strip(),
                 "rollen": r['rollen'], "antwort": r['antwort']}
                for r in cur.fetchall()
            ]
