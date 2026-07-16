"""Repository für Mannschafts-Termine (#95, Spielbetrieb Etappe 1) inkl. Kader-ACL.

Der Zugriff auf Termine ergibt sich aus der Kader-Zugehörigkeit (mitglied_mannschaft),
NICHT aus globalen Rechten: Wer am Stichtag aktiv (von/bis) im Kader ist, liest die
Termine seiner Mannschaft; die Rollen betreuer/uebungsleiter verwalten sie.
Nur das übergreifende Verwalten (alle Mannschaften) hängt am globalen Recht
termine.verwalten – Admins umgehen die ACL ohnehin (das entscheidet die API-Schicht).

Die Aktiv-Definition (von <= Stichtag <= bis) deckt sich mit der Kader-Semantik in
mitglied_mannschaft (von ist dort NOT NULL, bis optional).
"""
from datetime import date
from typing import Optional

from app.models.termin import Termin
from app.db.base_repository import BaseRepository


VALID_TYPEN = ('training', 'spiel', 'sonstiges')
VALID_STATUS = ('geplant', 'abgesagt')
# Kader-Rollen, die Termine ihrer Mannschaft verwalten dürfen ('trainer' mit #103
# abgeschafft, siehe VALID_ROLLEN in mitglied_mannschaft_repository).
VERWALTEN_ROLLEN = ('betreuer', 'uebungsleiter')

# Gemeinsame CTE: aktive Kader-Zugehörigkeiten des Users am Stichtag.
# Erwartet die benannten Parameter %(uid)s (user_id) und %(tag)s (ISO-Datum).
_KADER_CTE = """
    WITH kader AS (
        SELECT mm.mannschaft_id, mm.rolle
        FROM mitglied m
        JOIN mitglied_mannschaft mm ON mm.mitglied_id = m.id AND mm.deleted_at IS NULL
            AND mm.von <= %(tag)s
            AND (mm.bis IS NULL OR mm.bis >= %(tag)s)
        WHERE m.user_id = %(uid)s AND m.deleted_at IS NULL
    )
"""

_COLS = ("id, mannschaft_id, serie_id, typ, beginn, ende, ort, treffpunkt, "
         "treffpunkt_zeit, gegner, heim_auswaerts, extern_ref, status, beschreibung, "
         "version, created_at, created_by, updated_at, updated_by, deleted_at, deleted_by")

# Änderbare Fachfelder (create/update) – status/extern_ref/serie_id laufen bewusst
# über eigene Wege (set_status bzw. späterer Import/Serien-Code).
_EDIT_FIELDS = ('typ', 'beginn', 'ende', 'ort', 'treffpunkt', 'treffpunkt_zeit',
                'gegner', 'heim_auswaerts', 'beschreibung')


def _map(row) -> Termin:
    return Termin(
        id=row['id'], mannschaft_id=row['mannschaft_id'], serie_id=row['serie_id'],
        typ=row['typ'], beginn=row['beginn'], ende=row['ende'], ort=row['ort'],
        treffpunkt=row['treffpunkt'], treffpunkt_zeit=row['treffpunkt_zeit'],
        gegner=row['gegner'], heim_auswaerts=row['heim_auswaerts'],
        extern_ref=row['extern_ref'], status=row['status'],
        beschreibung=row['beschreibung'], version=row['version'],
        created_at=row['created_at'], created_by=row['created_by'],
        updated_at=row['updated_at'], updated_by=row['updated_by'],
        deleted_at=row['deleted_at'], deleted_by=row['deleted_by'],
        mannschaft_name=row.get('mannschaft_name'),
    )


class TerminRepository(BaseRepository):

    # ------------------------------------------------------------------ lesen
    def get(self, termin_id: int) -> Optional[Termin]:
        with self.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM termine WHERE id = %s AND deleted_at IS NULL",
                (termin_id,),
            )
            row = cur.fetchone()
            return _map(row) if row else None

    def list_for_mannschaft(self, mannschaft_id: int, von: Optional[str] = None,
                            bis: Optional[str] = None) -> list[Termin]:
        """Aktive Termine einer Mannschaft, optional gefiltert auf beginn im
        Zeitraum von/bis (ISO-Datum, beide inklusiv), sortiert nach beginn."""
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_COLS} FROM termine
                WHERE mannschaft_id = %(mid)s AND deleted_at IS NULL
                  AND (%(von)s::text IS NULL OR beginn >= %(von)s)
                  AND (%(bis)s::text IS NULL OR LEFT(beginn, 10) <= %(bis)s)
                ORDER BY beginn, id
                """,
                {"mid": mannschaft_id, "von": von, "bis": bis},
            )
            return [_map(r) for r in cur.fetchall()]

    def list_for_user(self, user_id: int, von: Optional[str] = None,
                      bis: Optional[str] = None,
                      stichtag: Optional[str] = None) -> list[dict]:
        """„Meine Termine": Termine aller Mannschaften, in deren Kader der User am
        Stichtag aktiv ist – mit mannschaft_name und der Zugriffsstufe je Termin.
        Zusätzlich Gast-Termine: Termine mit aktiver Zu-/Absage des eigenen
        Mitglieds außerhalb der eigenen Kader (gast=True, Stufe 'lesen')."""
        tag = stichtag or date.today().isoformat()
        with self.cursor() as cur:
            cur.execute(
                _KADER_CTE + f"""
                , zugriff AS (
                    SELECT mannschaft_id, bool_or(rolle = ANY(%(vroll)s)) AS darf_verwalten
                    FROM kader GROUP BY mannschaft_id
                )
                , gast AS (
                    SELECT DISTINCT z.termin_id
                    FROM termin_zusage z
                    JOIN mitglied gm ON gm.id = z.mitglied_id AND gm.deleted_at IS NULL
                    WHERE gm.user_id = %(uid)s AND z.deleted_at IS NULL
                )
                SELECT {', '.join('t.' + c.strip() for c in _COLS.split(','))},
                       ma.name AS mannschaft_name, z.darf_verwalten,
                       (z.mannschaft_id IS NULL) AS ist_gast
                FROM termine t
                LEFT JOIN zugriff z ON z.mannschaft_id = t.mannschaft_id
                JOIN mannschaft ma ON ma.id = t.mannschaft_id AND ma.deleted_at IS NULL
                WHERE t.deleted_at IS NULL
                  AND (z.mannschaft_id IS NOT NULL
                       OR t.id IN (SELECT termin_id FROM gast))
                  AND (%(von)s::text IS NULL OR t.beginn >= %(von)s)
                  AND (%(bis)s::text IS NULL OR LEFT(t.beginn, 10) <= %(bis)s)
                ORDER BY t.beginn, t.id
                """,
                {"uid": user_id, "tag": tag, "von": von, "bis": bis,
                 "vroll": list(VERWALTEN_ROLLEN)},
            )
            rows = cur.fetchall()
        result = []
        for r in rows:
            d = _map(r).__dict__.copy()
            d["zugriff"] = 'verwalten' if r['darf_verwalten'] else 'lesen'
            d["gast"] = r['ist_gast']
            result.append(d)
        return result

    # ----------------------------------------------------------------- ACL
    def get_access_for_user(self, user_id: int, mannschaft_id: int,
                            stichtag: Optional[str] = None) -> Optional[str]:
        """Effektive Zugriffsstufe des Users auf die Termine einer Mannschaft:
        None (kein Zugriff) | 'lesen' | 'verwalten'. Mehrfach-Zugehörigkeit
        (z. B. spieler + uebungsleiter) ergibt die höchste Stufe. Admin-/termine.verwalten-
        Bypass regelt die API-Schicht."""
        tag = stichtag or date.today().isoformat()
        with self.cursor() as cur:
            cur.execute(
                _KADER_CTE + """
                SELECT bool_or(rolle = ANY(%(vroll)s)) AS darf_verwalten
                FROM kader WHERE mannschaft_id = %(mid)s
                """,
                {"uid": user_id, "tag": tag, "mid": mannschaft_id,
                 "vroll": list(VERWALTEN_ROLLEN)},
            )
            row = cur.fetchone()
            if row is None or row['darf_verwalten'] is None:
                return None
            return 'verwalten' if row['darf_verwalten'] else 'lesen'

    def get_kader_mitglied_id(self, user_id: int, mannschaft_id: int,
                              stichtag: Optional[str] = None) -> Optional[int]:
        """mitglied_id des Users im aktiven Kader der Mannschaft (am Stichtag) – für die
        eigene Zu-/Absage. None, wenn der User dort kein aktives Kader-Mitglied ist."""
        tag = stichtag or date.today().isoformat()
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT m.id
                FROM mitglied m
                JOIN mitglied_mannschaft mm ON mm.mitglied_id = m.id
                    AND mm.deleted_at IS NULL AND mm.mannschaft_id = %(mid)s
                    AND mm.von <= %(tag)s AND (mm.bis IS NULL OR mm.bis >= %(tag)s)
                WHERE m.user_id = %(uid)s AND m.deleted_at IS NULL
                LIMIT 1
                """,
                {"uid": user_id, "mid": mannschaft_id, "tag": tag},
            )
            row = cur.fetchone()
            return row['id'] if row else None

    def is_mitglied_in_kader(self, mitglied_id: int, mannschaft_id: int,
                             stichtag: Optional[str] = None) -> bool:
        """Ob ein Mitglied am Stichtag aktiv im Kader der Mannschaft steht
        (On-behalf-Prüfung, wenn ein Verwalter für ein anderes Mitglied setzt)."""
        tag = stichtag or date.today().isoformat()
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM mitglied_mannschaft
                WHERE mitglied_id = %(mid)s AND mannschaft_id = %(man)s
                  AND deleted_at IS NULL
                  AND von <= %(tag)s AND (bis IS NULL OR bis >= %(tag)s)
                LIMIT 1
                """,
                {"mid": mitglied_id, "man": mannschaft_id, "tag": tag},
            )
            return cur.fetchone() is not None

    def is_mitglied_in_abteilung(self, mitglied_id: int, mannschaft_id: int,
                                 stichtag: Optional[str] = None) -> bool:
        """Ob ein Mitglied am Stichtag der Abteilung von `mannschaft_id` angehört
        (mitglied_abteilung, Zeitfenster wie in der Tresor-ACL) – Gast-Kreis für
        Termin-Einträge. Eine Kader-Zugehörigkeit ist bewusst NICHT nötig:
        Abteilungs-Mitglied genügt (z. B. AH-Spieler hilft in der Ersten aus)."""
        tag = stichtag or date.today().isoformat()
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM mitglied_abteilung mab
                WHERE mab.mitglied_id = %(mid)s AND mab.deleted_at IS NULL
                  AND (mab.von IS NULL OR mab.von <= %(tag)s)
                  AND (mab.bis IS NULL OR mab.bis >= %(tag)s)
                  AND mab.abteilung_id = (SELECT abteilung_id FROM mannschaft
                                          WHERE id = %(man)s)
                LIMIT 1
                """,
                {"mid": mitglied_id, "man": mannschaft_id, "tag": tag},
            )
            return cur.fetchone() is not None

    def list_gast_kandidaten(self, mannschaft_id: int,
                             stichtag: Optional[str] = None) -> list[dict]:
        """Gast-Kandidaten für Termine der Mannschaft: Mitglieder, die am Stichtag
        der Abteilung der Mannschaft angehören (mitglied_abteilung) und NICHT im
        Kader der Mannschaft selbst stehen – eine eigene Kader-Zugehörigkeit ist
        keine Voraussetzung. Ihre Mannschaften (falls vorhanden) kommen als
        Auswahl-Label mit."""
        tag = stichtag or date.today().isoformat()
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT m.id AS mitglied_id, m.vorname, m.nachname,
                       string_agg(DISTINCT ma.name, ', ' ORDER BY ma.name) AS mannschaften
                FROM mitglied m
                JOIN mitglied_abteilung mab ON mab.mitglied_id = m.id
                    AND mab.deleted_at IS NULL
                    AND (mab.von IS NULL OR mab.von <= %(tag)s)
                    AND (mab.bis IS NULL OR mab.bis >= %(tag)s)
                    AND mab.abteilung_id = (SELECT abteilung_id FROM mannschaft
                                            WHERE id = %(man)s)
                LEFT JOIN mitglied_mannschaft mm ON mm.mitglied_id = m.id
                    AND mm.deleted_at IS NULL
                    AND mm.von <= %(tag)s AND (mm.bis IS NULL OR mm.bis >= %(tag)s)
                LEFT JOIN mannschaft ma ON ma.id = mm.mannschaft_id AND ma.deleted_at IS NULL
                WHERE m.deleted_at IS NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM mitglied_mannschaft k
                      WHERE k.mitglied_id = m.id AND k.mannschaft_id = %(man)s
                        AND k.deleted_at IS NULL
                        AND k.von <= %(tag)s AND (k.bis IS NULL OR k.bis >= %(tag)s)
                  )
                GROUP BY m.id, m.vorname, m.nachname
                ORDER BY lower(m.nachname), lower(m.vorname)
                """,
                {"man": mannschaft_id, "tag": tag},
            )
            return [
                {"mitglied_id": r['mitglied_id'],
                 "name": f"{r['vorname'] or ''} {r['nachname'] or ''}".strip(),
                 "mannschaften": r['mannschaften']}
                for r in cur.fetchall()
            ]

    def list_kader_user_ids(self, mannschaft_id: int,
                            stichtag: Optional[str] = None) -> list[int]:
        """user_ids der am Stichtag aktiven Kader-Mitglieder MIT Benutzerkonto –
        Empfängerkreis für Termin-Benachrichtigungen (DISTINCT: Doppelrollen
        zählen einmal). Aktiv/gesperrt filtert der Versand über user.active."""
        tag = stichtag or date.today().isoformat()
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT m.user_id
                FROM mitglied m
                JOIN mitglied_mannschaft mm ON mm.mitglied_id = m.id
                    AND mm.deleted_at IS NULL AND mm.mannschaft_id = %(mid)s
                    AND mm.von <= %(tag)s AND (mm.bis IS NULL OR mm.bis >= %(tag)s)
                WHERE m.user_id IS NOT NULL AND m.deleted_at IS NULL
                """,
                {"mid": mannschaft_id, "tag": tag},
            )
            return [r['user_id'] for r in cur.fetchall()]

    def list_mannschaften_for_user(self, user_id: int,
                                   stichtag: Optional[str] = None) -> list[dict]:
        """Aktive Mannschaften, in deren Kader der User am Stichtag steht, mit der
        jeweils höchsten Zugriffsstufe – für Team-Auswahl und Nav-/Dashboard-Probe."""
        tag = stichtag or date.today().isoformat()
        with self.cursor() as cur:
            cur.execute(
                _KADER_CTE + """
                SELECT ma.id, ma.name, ma.saison, a.name AS abteilung_name,
                       bool_or(k.rolle = ANY(%(vroll)s)) AS darf_verwalten
                FROM kader k
                JOIN mannschaft ma ON ma.id = k.mannschaft_id AND ma.deleted_at IS NULL
                JOIN abteilung a ON a.id = ma.abteilung_id
                GROUP BY ma.id, ma.name, ma.saison, a.name
                ORDER BY lower(a.name), lower(ma.name)
                """,
                {"uid": user_id, "tag": tag, "vroll": list(VERWALTEN_ROLLEN)},
            )
            return [
                {"id": r['id'], "name": r['name'], "saison": r['saison'],
                 "abteilung_name": r['abteilung_name'],
                 "zugriff": 'verwalten' if r['darf_verwalten'] else 'lesen'}
                for r in cur.fetchall()
            ]

    def list_all_mannschaften(self) -> list[dict]:
        """Alle aktiven Mannschaften – für termine.verwalten/Admin (immer 'verwalten')."""
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT ma.id, ma.name, ma.saison, a.name AS abteilung_name
                FROM mannschaft ma
                JOIN abteilung a ON a.id = ma.abteilung_id
                WHERE ma.deleted_at IS NULL
                ORDER BY lower(a.name), lower(ma.name)
                """
            )
            return [
                {"id": r['id'], "name": r['name'], "saison": r['saison'],
                 "abteilung_name": r['abteilung_name'], "zugriff": 'verwalten'}
                for r in cur.fetchall()
            ]

    # ----------------------------------------------------------------- schreiben
    def create(self, mannschaft_id: int, typ: str, beginn: str,
               ende: Optional[str], ort: Optional[str], treffpunkt: Optional[str],
               treffpunkt_zeit: Optional[str], gegner: Optional[str],
               heim_auswaerts: Optional[str], beschreibung: Optional[str],
               created_by: str) -> Termin:
        with self.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO termine (mannschaft_id, {', '.join(_EDIT_FIELDS)},
                                     created_by, updated_by)
                VALUES ({', '.join(['%s'] * (len(_EDIT_FIELDS) + 3))})
                RETURNING id
                """,
                (mannschaft_id, typ, beginn, ende, ort, treffpunkt, treffpunkt_zeit,
                 gegner, heim_auswaerts, beschreibung, created_by, created_by),
            )
            new_id = cur.fetchone()['id']
        return self.get(new_id)

    def update(self, termin_id: int, typ: str, beginn: str, ende: Optional[str],
               ort: Optional[str], treffpunkt: Optional[str],
               treffpunkt_zeit: Optional[str], gegner: Optional[str],
               heim_auswaerts: Optional[str], beschreibung: Optional[str],
               updated_by: str, expected_version: int) -> bool:
        with self.cursor() as cur:
            cur.execute(
                f"""
                UPDATE termine SET {', '.join(f'{f}=%s' for f in _EDIT_FIELDS)},
                       updated_at=CURRENT_TIMESTAMP, updated_by=%s, version=version+1
                WHERE id=%s AND deleted_at IS NULL AND version=%s
                """,
                (typ, beginn, ende, ort, treffpunkt, treffpunkt_zeit, gegner,
                 heim_auswaerts, beschreibung, updated_by, termin_id, expected_version),
            )
            return cur.rowcount > 0

    def set_status(self, termin_id: int, status: str, updated_by: str,
                   expected_version: int) -> bool:
        """Termin absagen ('abgesagt') bzw. reaktivieren ('geplant')."""
        with self.cursor() as cur:
            cur.execute(
                "UPDATE termine SET status=%s, "
                "updated_at=CURRENT_TIMESTAMP, updated_by=%s, version=version+1 "
                "WHERE id=%s AND deleted_at IS NULL AND version=%s",
                (status, updated_by, termin_id, expected_version),
            )
            return cur.rowcount > 0

    def mark_deleted(self, termin_id: int, deleted_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE termine SET deleted_at=CURRENT_TIMESTAMP, deleted_by=%s, "
                "version=version+1 WHERE id=%s AND deleted_at IS NULL",
                (deleted_by, termin_id),
            )
            return cur.rowcount > 0
