"""Repository für Termin-Zusagen (RSVP, #95 Spielbetrieb Etappe 2).

Je Termin höchstens eine aktive Antwort pro Mitglied – erzwungen über den
partiellen Unique-Index uix_termin_zusage_active (termin_id, mitglied_id) WHERE
deleted_at IS NULL. Setzen ist ein Upsert: existiert eine aktive Zeile, wird sie per
UPDATE fortgeschrieben (version+1 → History-Trigger); sonst eine neue angelegt.
Zurücknehmen = Soft-Delete. Zugriff/ACL (wer für wen setzen darf) entscheidet die
API-Schicht über die Kader-Zugehörigkeit (siehe TerminRepository).

Gäste: eine aktive ZEILE eines Mitglieds, das am Termin-Datum NICHT im Kader
der Termin-Mannschaft steht, macht dieses Mitglied zum Gast des Termins –
es gibt keine eigene Gast-Tabelle. Verwalter tragen Gäste per set_antwort ein
(sie sagen für jemanden zu) oder laden sie per lade_ein ein (Zeile mit
`antwort IS NULL` – eingeladen, Antwort steht aus). Zurücknehmen beendet den
Gast-Status."""
from app.models.termin_zusage import TerminZusage
from app.db.base_repository import BaseRepository


VALID_ANTWORTEN = ('zu', 'vielleicht', 'ab')

_COLS = ("id, termin_id, mitglied_id, antwort, kommentar, version, "
         "created_at, created_by, updated_at, updated_by, deleted_at, deleted_by")

# Seit wann steht die aktuelle Antwort (#215)? Nicht `updated_at` der Zeile: Das
# rückt auch bei einer reinen Kommentar-Änderung oder einem erneuten Setzen
# derselben Antwort vor. Gesucht ist die erste Version nach dem letzten Wechsel
# der Antwort – aus der History, die der Audit-Trigger ohnehin schreibt. Erwartet
# die aktive Zeile als `z`; ohne Zeile (Kader-Mitglied ohne Antwort) bleibt es NULL.
_SEIT_JOIN = """
    LEFT JOIN LATERAL (
        SELECT MIN(h.updated_at) AS seit
        FROM termin_zusage_history h
        WHERE h.id = z.id
          AND h.version > COALESCE((
              SELECT MAX(h2.version) FROM termin_zusage_history h2
              WHERE h2.id = z.id AND h2.antwort IS DISTINCT FROM z.antwort), 0)
    ) s ON TRUE
"""


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
    def set_antwort(self, termin_id: int, mitglied_id: int, antwort: str | None,
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

    def lade_ein(self, termin_id: int, mitglied_id: int, von: str) -> bool:
        """Lädt ein Mitglied zu einem Termin ein: Zeile mit `antwort IS NULL`.

        Anders als set_antwort ein reines INSERT: Eine vorhandene aktive Zeile
        bleibt unangetastet. Wer schon zugesagt hat, darf durch eine zweite
        Einladungsrunde nicht auf „offen" zurückfallen – und aus demselben Grund
        gibt es hier auch kein Update.

        Returns:
            True, wenn die Einladung neu entstanden ist (False = stand schon drin)
        """
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO termin_zusage (termin_id, mitglied_id, antwort, kommentar,
                                           created_by, updated_by)
                VALUES (%(t)s, %(m)s, NULL, NULL, %(u)s, %(u)s)
                ON CONFLICT (termin_id, mitglied_id) WHERE deleted_at IS NULL
                DO NOTHING
                """,
                {"t": termin_id, "m": mitglied_id, "u": von},
            )
            return cur.rowcount > 0

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
                  AND antwort IS NOT NULL   -- eingeladen ≠ geantwortet (v102)
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

    def has_active_zusage(self, termin_id: int, user_id: int) -> bool:
        """Ob das mit dem User verknüpfte Mitglied eine aktive Zu-/Absage zu dem
        Termin hat – öffnet Gästen (Antwort ohne Kader-Zugehörigkeit) den Lese-
        und Selbst-Antwort-Zugriff auf genau diesen Termin."""
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM termin_zusage z
                JOIN mitglied m ON m.id = z.mitglied_id AND m.deleted_at IS NULL
                WHERE z.termin_id = %s AND z.deleted_at IS NULL AND m.user_id = %s
                LIMIT 1
                """,
                (termin_id, user_id),
            )
            return cur.fetchone() is not None

    def list_user_ids_mit_zusage(self, termin_id: int) -> list[int]:
        """user_ids aller Mitglieder mit aktiver Antwort zum Termin (Kader wie
        Gäste) – ergänzt den Kader-Empfängerkreis der Termin-Benachrichtigungen
        um die Gäste (Dubletten filtert der Versand)."""
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT m.user_id
                FROM termin_zusage z
                JOIN mitglied m ON m.id = z.mitglied_id AND m.deleted_at IS NULL
                WHERE z.termin_id = %s AND z.deleted_at IS NULL
                  AND m.user_id IS NOT NULL
                """,
                (termin_id,),
            )
            return [r['user_id'] for r in cur.fetchall()]

    def list_offene_user_ids(self, termin_id: int) -> list[int]:
        """user_ids derer, von denen zu diesem Termin noch keine Meldung vorliegt
        (#95-Nachgang) – Empfängerkreis der Termin-Erinnerung.

        Gefragt sind zwei Gruppen, und zwar dieselben, die auch die Kader-Ansicht
        als „offen" zeigt:

        * der am Termin-Datum aktive **Kader** – ohne aktive Zeile oder mit einer
          Einladung, die noch unbeantwortet ist (`antwort IS NULL`);
        * eingeladene **Gäste** (Zeile mit `antwort IS NULL` ohne Kader-Zugehörigkeit)
          – wer als Gast eingetragen wurde, hat bereits eine Antwort und ist damit raus.

        „Vielleicht" zählt als Meldung: Der Spieler hat geantwortet, mehr weiß er
        selbst noch nicht. Ohne Benutzerkonto gibt es keinen Kanal – solche
        Kader-Mitglieder bleiben hier still übrig (der Betreuer sieht sie in der
        Kader-Liste). Aktiv/gesperrt filtert der Versand über `user.active`.
        """
        with self.cursor() as cur:
            cur.execute(
                """
                WITH t AS (
                    SELECT mannschaft_id, LEFT(beginn, 10) AS tag
                    FROM termine WHERE id = %(tid)s AND deleted_at IS NULL
                ),
                kandidaten AS (
                    SELECT m.id AS mitglied_id, m.user_id
                    FROM t
                    JOIN mitglied_mannschaft mm ON mm.mannschaft_id = t.mannschaft_id
                        AND mm.deleted_at IS NULL
                        AND mm.von <= t.tag AND (mm.bis IS NULL OR mm.bis >= t.tag)
                    JOIN mitglied m ON m.id = mm.mitglied_id AND m.deleted_at IS NULL
                    UNION
                    SELECT m.id AS mitglied_id, m.user_id
                    FROM termin_zusage z
                    JOIN mitglied m ON m.id = z.mitglied_id AND m.deleted_at IS NULL
                    WHERE z.termin_id = %(tid)s AND z.deleted_at IS NULL
                      AND z.antwort IS NULL
                )
                SELECT DISTINCT k.user_id
                FROM kandidaten k
                WHERE k.user_id IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM termin_zusage z2
                      WHERE z2.termin_id = %(tid)s AND z2.mitglied_id = k.mitglied_id
                        AND z2.deleted_at IS NULL AND z2.antwort IS NOT NULL
                  )
                """,
                {"tid": termin_id},
            )
            return [r['user_id'] for r in cur.fetchall()]

    def list_gaeste_with_zusage(self, termin_id: int) -> list[dict]:
        """Gäste des Termins: aktive Antworten von Mitgliedern, die am
        Termin-Datum NICHT im Kader der Termin-Mannschaft stehen."""
        with self.cursor() as cur:
            cur.execute(
                """
                WITH t AS (
                    SELECT mannschaft_id, LEFT(beginn, 10) AS tag
                    FROM termine WHERE id = %(tid)s AND deleted_at IS NULL
                )
                SELECT m.id AS mitglied_id, m.vorname, m.nachname,
                       z.antwort, z.kommentar,
                       COALESCE(s.seit, z.updated_at) AS antwort_seit
                FROM t
                CROSS JOIN termin_zusage z
                JOIN mitglied m ON m.id = z.mitglied_id AND m.deleted_at IS NULL
                """ + _SEIT_JOIN + """
                WHERE z.termin_id = %(tid)s AND z.deleted_at IS NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM mitglied_mannschaft mm
                      WHERE mm.mitglied_id = m.id
                        AND mm.mannschaft_id = t.mannschaft_id
                        AND mm.deleted_at IS NULL
                        AND mm.von <= t.tag AND (mm.bis IS NULL OR mm.bis >= t.tag)
                  )
                ORDER BY lower(m.nachname), lower(m.vorname)
                """,
                {"tid": termin_id},
            )
            return [
                {"mitglied_id": r['mitglied_id'],
                 "name": f"{r['vorname'] or ''} {r['nachname'] or ''}".strip(),
                 "rollen": None, "antwort": r['antwort'],
                 "kommentar": r['kommentar'], "antwort_seit": r['antwort_seit']}
                for r in cur.fetchall()
            ]

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
                       z.antwort, z.kommentar,
                       COALESCE(s.seit, z.updated_at) AS antwort_seit
                FROM t
                JOIN mitglied_mannschaft mm ON mm.mannschaft_id = t.mannschaft_id
                    AND mm.deleted_at IS NULL
                    AND mm.von <= t.tag AND (mm.bis IS NULL OR mm.bis >= t.tag)
                JOIN mitglied m ON m.id = mm.mitglied_id AND m.deleted_at IS NULL
                LEFT JOIN termin_zusage z ON z.termin_id = %(tid)s
                    AND z.mitglied_id = m.id AND z.deleted_at IS NULL
                """ + _SEIT_JOIN + """
                GROUP BY m.id, m.vorname, m.nachname, z.antwort, z.kommentar,
                         s.seit, z.updated_at
                ORDER BY lower(m.nachname), lower(m.vorname)
                """,
                {"tid": termin_id},
            )
            return [
                {"mitglied_id": r['mitglied_id'],
                 "name": f"{r['vorname'] or ''} {r['nachname'] or ''}".strip(),
                 "rollen": r['rollen'], "antwort": r['antwort'],
                 "kommentar": r['kommentar'], "antwort_seit": r['antwort_seit']}
                for r in cur.fetchall()
            ]

    def verlauf(self, termin_id: int) -> list[dict]:
        """Zeitleiste aller Zu-/Absagen eines Termins, neueste zuerst (#215).

        Liest die History, die der Audit-Trigger bei jedem version-Bump schreibt,
        und leitet je Version ab, was passiert ist (`art`):

        * ``eingeladen``      – erste Version ohne Antwort (lade_ein)
        * ``antwort``         – erste Antwort oder Wechsel; ``von`` = vorherige
                                Antwort (None bei der ersten bzw. nach Einladung)
        * ``kommentar``       – Antwort gleich, nur der Kommentar hat sich geändert
        * ``zurueckgenommen`` – Soft-Delete; ``antwort`` = die zurückgenommene
                                (None = Einladung zurückgenommen)

        Erneutes Setzen derselben Antwort mit demselben Kommentar erzeugt zwar
        eine Version, ist aber kein Ereignis und fällt heraus. Nach einer
        Rücknahme beginnt eine neue Zeile (eigene id) – deren erste Antwort
        erscheint deshalb ohne ``von``.

        ``durch_selbst`` sagt, ob das Mitglied selbst geantwortet hat; sonst
        nennt ``durch_name`` den, der es eingetragen hat (Name des mit dem
        Konto verknüpften Mitglieds, ersatzweise der Benutzername).
        """
        with self.cursor() as cur:
            cur.execute(
                """
                WITH h AS (
                    SELECT h.id, h.version, h.mitglied_id, h.antwort, h.kommentar,
                           h.updated_at, h.updated_by, h.deleted_at, h.deleted_by,
                           LAG(h.antwort)    OVER w AS vorher_antwort,
                           LAG(h.kommentar)  OVER w AS vorher_kommentar,
                           LAG(h.deleted_at) OVER w AS vorher_deleted_at,
                           ROW_NUMBER()      OVER w AS nr
                    FROM termin_zusage_history h
                    WHERE h.termin_id = %(tid)s
                    WINDOW w AS (PARTITION BY h.id ORDER BY h.version)
                ),
                e AS (
                    SELECT h.*,
                        CASE
                            WHEN h.deleted_at IS NOT NULL THEN
                                CASE WHEN h.vorher_deleted_at IS NULL
                                     THEN 'zurueckgenommen' END
                            WHEN h.nr = 1 AND h.antwort IS NULL THEN 'eingeladen'
                            WHEN h.nr = 1 THEN 'antwort'
                            WHEN h.antwort IS DISTINCT FROM h.vorher_antwort THEN 'antwort'
                            WHEN h.kommentar IS DISTINCT FROM h.vorher_kommentar
                                THEN 'kommentar'
                        END AS art,
                        CASE WHEN h.deleted_at IS NOT NULL
                             THEN h.deleted_at ELSE h.updated_at END AS zeit,
                        CASE WHEN h.deleted_at IS NOT NULL
                             THEN h.deleted_by ELSE h.updated_by END AS durch
                    FROM h
                )
                SELECT e.id, e.version, e.mitglied_id, e.art, e.antwort,
                       e.vorher_antwort, e.kommentar, e.zeit, e.durch,
                       m.vorname, m.nachname, u.username AS eigener_username,
                       sm.id AS durch_mitglied_id,
                       sm.vorname AS durch_vorname, sm.nachname AS durch_nachname
                FROM e
                JOIN mitglied m ON m.id = e.mitglied_id AND m.deleted_at IS NULL
                LEFT JOIN users u ON u.id = m.user_id
                LEFT JOIN LATERAL (
                    SELECT m2.id, m2.vorname, m2.nachname
                    FROM users u2
                    JOIN mitglied m2 ON m2.user_id = u2.id AND m2.deleted_at IS NULL
                    WHERE u2.username = e.durch
                    ORDER BY m2.id
                    LIMIT 1
                ) sm ON TRUE
                WHERE e.art IS NOT NULL
                ORDER BY e.zeit DESC, e.id DESC, e.version DESC
                """,
                {"tid": termin_id},
            )
            ergebnis = []
            for r in cur.fetchall():
                selbst = r['eigener_username'] is not None and r['durch'] == r['eigener_username']
                durch_name = None
                if not selbst:
                    durch_name = (f"{r['durch_vorname'] or ''} {r['durch_nachname'] or ''}".strip()
                                  if r['durch_mitglied_id'] else r['durch'])
                ergebnis.append({
                    "mitglied_id": r['mitglied_id'],
                    "name": f"{r['vorname'] or ''} {r['nachname'] or ''}".strip(),
                    "art": r['art'],
                    "antwort": r['antwort'],
                    "von": r['vorher_antwort'] if r['art'] == 'antwort' else None,
                    "kommentar": r['kommentar'] if r['art'] in ('antwort', 'kommentar') else None,
                    "zeit": r['zeit'],
                    "durch_selbst": selbst,
                    "durch_mitglied_id": None if selbst else r['durch_mitglied_id'],
                    "durch_name": durch_name,
                })
            return ergebnis
