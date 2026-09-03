"""Repository für Mannschafts-Termine (#95, Spielbetrieb Etappe 1) inkl. Kader-ACL.

Der Zugriff auf Termine ergibt sich aus der Kader-Zugehörigkeit (mitglied_mannschaft),
NICHT aus globalen Rechten: Wer am Stichtag aktiv (von/bis) im Kader ist, liest die
Termine seiner Mannschaft; die Rollen betreuer/uebungsleiter verwalten sie.
Nur das übergreifende Verwalten (alle Mannschaften) hängt am globalen Recht
termine.verwalten – Admins umgehen die ACL ohnehin (das entscheidet die API-Schicht).

Die Aktiv-Definition (von <= Stichtag <= bis) deckt sich mit der Kader-Semantik in
mitglied_mannschaft (von ist dort NOT NULL, bis optional).
"""
from datetime import date, datetime, timedelta
from typing import Optional

from psycopg.types.json import Jsonb

from app.models.termin import Termin
from app.db.base_repository import BaseRepository


# Vorlauf der automatischen Termin-Zuordnung (#167, s. get_laufenden): So lange
# vor dem Anpfiff gehören Buchungen schon zum Termin – Getränke werden beim
# Aufbau geholt, nicht erst nach dem Anpfiff.
TERMIN_FENSTER_VORLAUF = '60 minutes'


def _TERMIN_TS(spalte: str) -> str:
    """Lokale Wandzeit ('YYYY-MM-DDTHH:MM') als timestamp für Zeitvergleiche."""
    return f"to_timestamp({spalte}, 'YYYY-MM-DD\"T\"HH24:MI')::timestamp"


def _jetzt_lokal() -> str:
    """Jetzt als lokale Wandzeit im Termin-Format – dieselbe Zeitbasis wie beginn/ende."""
    return datetime.now().strftime('%Y-%m-%dT%H:%M')


# Fenster des Hinweises „noch nicht beantwortet" an Kachel und Nav-Punkt.
# Zwei Wochen: weit genug, dass ein Wochenendspiel früh auftaucht, eng genug,
# dass die Zahl nicht zur Dauerdekoration wird.
OFFENE_MELDUNGEN_TAGE = 14

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

_COLS = ("id, mannschaft_id, serie_id, typ, beginn, ende, ort, spielstaette_id, treffpunkt, "
         "treffpunkt_zeit, gegner, heim_auswaerts, extern_ref, extern_stand, status, "
         "beschreibung, version, created_at, created_by, updated_at, updated_by, "
         "deleted_at, deleted_by")

# Änderbare Fachfelder (create/update) – status/extern_ref/serie_id laufen bewusst
# über eigene Wege (set_status bzw. späterer Import/Serien-Code).
# spielstaette_id ist seit v80 Pflicht (Grundlage des Platzbelegungsplans, #95).
_EDIT_FIELDS = ('typ', 'beginn', 'ende', 'ort', 'spielstaette_id', 'treffpunkt',
                'treffpunkt_zeit', 'gegner', 'heim_auswaerts', 'beschreibung')

# Felder, die der Spielplan-Import schreiben darf (#95). Absichtlich eine eigene,
# kurze Liste: Treffpunkt, Beschreibung und Typ gehören dem Team, nicht der Quelle.
IMPORT_FELDER = ('beginn', 'ort', 'gegner', 'heim_auswaerts')


def _map(row) -> Termin:
    return Termin(
        id=row['id'], mannschaft_id=row['mannschaft_id'], serie_id=row['serie_id'],
        typ=row['typ'], beginn=row['beginn'], ende=row['ende'], ort=row['ort'],
        spielstaette_id=row['spielstaette_id'],
        spielstaette_name=row.get('spielstaette_name'),
        spielstaette_strasse=row.get('spielstaette_strasse'),
        spielstaette_plz=row.get('spielstaette_plz'),
        spielstaette_ort=row.get('spielstaette_ort'),
        spielstaette_untergrund=row.get('spielstaette_untergrund'),
        treffpunkt=row['treffpunkt'], treffpunkt_zeit=row['treffpunkt_zeit'],
        gegner=row['gegner'], heim_auswaerts=row['heim_auswaerts'],
        extern_ref=row['extern_ref'], extern_stand=row['extern_stand'],
        status=row['status'],
        beschreibung=row['beschreibung'], version=row['version'],
        created_at=row['created_at'], created_by=row['created_by'],
        updated_at=row['updated_at'], updated_by=row['updated_by'],
        deleted_at=row['deleted_at'], deleted_by=row['deleted_by'],
        mannschaft_name=row.get('mannschaft_name'),
    )


class TerminRepository(BaseRepository):

    # ------------------------------------------------------------------ lesen
    def get(self, termin_id: int) -> Optional[Termin]:
        """Einzelner Termin – mit denselben Anzeigefeldern wie in den Listen.

        Der JOIN auf die Spielstätte kostet nichts (das Feld ist seit v80 NOT
        NULL) und erspart die Frage, warum Name, Anschrift und Belag mal da sind
        und mal nicht. Die Mannschaft hängt per LEFT JOIN dran: Ihr Name gehört
        in den Spieltitel („VTB AH – SV X"), darf den Termin aber nicht
        verschwinden lassen, wenn das Team soft-gelöscht ist.
        """
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT {', '.join('t.' + c.strip() for c in _COLS.split(','))},
                       ma.name AS mannschaft_name,
                       s.name AS spielstaette_name,
                       s.strasse AS spielstaette_strasse, s.plz AS spielstaette_plz,
                       s.ort AS spielstaette_ort, s.untergrund AS spielstaette_untergrund
                FROM termine t
                LEFT JOIN mannschaft ma ON ma.id = t.mannschaft_id
                JOIN spielstaette s ON s.id = t.spielstaette_id
                WHERE t.id = %s AND t.deleted_at IS NULL
                """,
                (termin_id,),
            )
            row = cur.fetchone()
            return _map(row) if row else None

    def get_by_extern_ref(self, extern_ref: str,
                          mannschaft_id: int) -> Optional[Termin]:
        """Termin einer Mannschaft zu einer DFBnet-Spielkennung (#95).

        Die Spielkennung identifiziert das Spiel, nicht unseren Kalendereintrag:
        Bei einem vereinsinternen Spiel führen beide Mannschaften einen eigenen
        Termin mit derselben Kennung. Eindeutig ist erst das Paar — dafür sorgt
        der partielle Unique-Index (mannschaft_id, extern_ref).
        """
        with self.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM termine "
                "WHERE extern_ref = %s AND mannschaft_id = %s AND deleted_at IS NULL",
                (extern_ref, mannschaft_id),
            )
            row = cur.fetchone()
            return _map(row) if row else None

    def get_laufenden(self, mannschaft_id: int,
                      jetzt: Optional[str] = None) -> Optional[Termin]:
        """Der aktuelle Termin der Mannschaft — Grundlage der automatischen
        Termin-Zuordnung von Teamkassen-Buchungen (#167).

        Die Termine einer Mannschaft teilen die Zeitachse LÜCKENLOS unter sich
        auf: Ein Termin ist ab VORLAUF vor seinem `beginn` zuständig und bleibt
        es, bis der Vorlauf des nächsten anfängt. Sein `ende` spielt bewusst
        keine Rolle — nach dem Abpfiff wird weitergetrunken, und dieses Bier
        gehört noch zum Spiel, nicht ins Nichts.

        Daraus folgt die ganze Abfrage: gesucht ist schlicht der JÜNGSTE Termin,
        dessen Vorlauf schon begonnen hat. Ein Vergleich mit dem Folgetermin
        erübrigt sich, weil dessen Vorlauf ihn automatisch ablöst, sobald er
        selbst der jüngste ist.

        Der letzte Termin einer Mannschaft hat damit kein Ende: Solange kein
        neuer angelegt ist, hängen auch späte Buchungen an ihm. Das ist so
        gewollt (bewusste Entscheidung zu #167) — die Alternative wäre ein
        willkürliches Zeitlimit, nach dem Buchungen unzugeordnet lägen.

        Abgesagte Termine zählen gar nicht mit: Sie sind nicht zuständig und
        lösen den vorherigen auch nicht ab — dort findet nichts statt.

        `beginn` ist lokale Wandzeit als TEXT ('YYYY-MM-DDTHH:MM'), der Vergleich
        läuft deshalb über to_timestamp, nicht über die Audit-TZ-Zeiten.
        """
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT {', '.join('t.' + c.strip() for c in _COLS.split(','))},
                       ma.name AS mannschaft_name,
                       s.name AS spielstaette_name,
                       s.strasse AS spielstaette_strasse, s.plz AS spielstaette_plz,
                       s.ort AS spielstaette_ort, s.untergrund AS spielstaette_untergrund
                FROM termine t
                LEFT JOIN mannschaft ma ON ma.id = t.mannschaft_id
                JOIN spielstaette s ON s.id = t.spielstaette_id
                WHERE t.mannschaft_id = %(mid)s AND t.deleted_at IS NULL
                  AND t.status <> 'abgesagt'
                  AND {_TERMIN_TS('t.beginn')} - %(vorlauf)s::interval
                      <= %(jetzt)s::timestamp
                ORDER BY t.beginn DESC, t.id DESC
                LIMIT 1
                """,
                {"mid": mannschaft_id,
                 "jetzt": jetzt or _jetzt_lokal(),
                 "vorlauf": TERMIN_FENSTER_VORLAUF},
            )
            row = cur.fetchone()
            return _map(row) if row else None

    def get_naechsten(self, mannschaft_id: int,
                      jetzt: Optional[str] = None) -> Optional[Termin]:
        """Der Termin, auf den man sich gerade VORBEREITET (#167, v100).

        Bewusst eine andere Frage als get_laufenden: Dort geht es darum, wohin
        eine Buchung gehört (nach dem Abpfiff gehört das Bier noch zum Spiel).
        Hier geht es darum, welche Speisekarte man gerade pflegt — und das ist
        das nächste Ereignis, das noch nicht vorbei ist. Am Morgen des Spieltags
        ist das das Spiel am Abend, nicht das Training von letzter Woche.

        Gesucht ist deshalb der FRÜHESTE Termin, dessen Ende noch nicht erreicht
        ist; ohne `ende` zählt der Beginn. Während des Termins bleibt er es also,
        danach rückt der nächste nach.
        """
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT {', '.join('t.' + c.strip() for c in _COLS.split(','))},
                       ma.name AS mannschaft_name,
                       s.name AS spielstaette_name,
                       s.strasse AS spielstaette_strasse, s.plz AS spielstaette_plz,
                       s.ort AS spielstaette_ort, s.untergrund AS spielstaette_untergrund
                FROM termine t
                LEFT JOIN mannschaft ma ON ma.id = t.mannschaft_id
                JOIN spielstaette s ON s.id = t.spielstaette_id
                WHERE t.mannschaft_id = %(mid)s AND t.deleted_at IS NULL
                  AND t.status <> 'abgesagt'
                  AND COALESCE(NULLIF(t.ende, ''), t.beginn) >= %(jetzt)s
                ORDER BY t.beginn, t.id
                LIMIT 1
                """,
                {"mid": mannschaft_id, "jetzt": jetzt or _jetzt_lokal()},
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
                SELECT {', '.join('t.' + c.strip() for c in _COLS.split(','))},
                       ma.name AS mannschaft_name,
                       s.name AS spielstaette_name,
                       s.strasse AS spielstaette_strasse, s.plz AS spielstaette_plz, s.ort AS spielstaette_ort,
                       s.untergrund AS spielstaette_untergrund
                FROM termine t
                LEFT JOIN mannschaft ma ON ma.id = t.mannschaft_id
                JOIN spielstaette s ON s.id = t.spielstaette_id
                WHERE t.mannschaft_id = %(mid)s AND t.deleted_at IS NULL
                  AND (%(von)s::text IS NULL OR t.beginn >= %(von)s)
                  AND (%(bis)s::text IS NULL OR LEFT(t.beginn, 10) <= %(bis)s)
                ORDER BY t.beginn, t.id
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
                       ma.name AS mannschaft_name, s.name AS spielstaette_name,
                       s.strasse AS spielstaette_strasse, s.plz AS spielstaette_plz, s.ort AS spielstaette_ort,
                       s.untergrund AS spielstaette_untergrund,
                       z.darf_verwalten,
                       (z.mannschaft_id IS NULL) AS ist_gast
                FROM termine t
                LEFT JOIN zugriff z ON z.mannschaft_id = t.mannschaft_id
                JOIN mannschaft ma ON ma.id = t.mannschaft_id AND ma.deleted_at IS NULL
                JOIN spielstaette s ON s.id = t.spielstaette_id
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

    def anzahl_offene_meldungen(self, user_id: int,
                                tage: int = OFFENE_MELDUNGEN_TAGE,
                                jetzt: Optional[str] = None) -> int:
        """Wie viele der eigenen Termine der nächsten `tage` Tage sind unbeantwortet?

        Zahl hinter dem Hinweis an Kachel und Nav-Punkt (#133-Muster). Der Ausschnitt
        ist bewusst derselbe wie in „Meine Termine" (list_for_user): eigener Kader am
        Stichtag plus Gast-Termine — was der Hinweis zählt, muss der Benutzer hinter
        der Kachel auch finden. Der Verwalter-Bypass gilt hier NICHT: Gezählt wird die
        eigene Meldung, und die schuldet nur, wer selbst antworten darf.

        Offen heißt: keine aktive Antwort — eine unbeantwortete Einladung
        (`antwort IS NULL`) zählt also mit, „vielleicht" nicht. Abgesagte Termine
        bleiben außen vor, und die Untergrenze ist der Moment statt des Tages: An ein
        Spiel von heute Vormittag erinnert am Abend niemand mehr.
        """
        jetzt = jetzt or _jetzt_lokal()
        with self.cursor() as cur:
            cur.execute(
                _KADER_CTE + """
                , ich AS (
                    SELECT id FROM mitglied
                    WHERE user_id = %(uid)s AND deleted_at IS NULL
                )
                SELECT count(*) AS n
                FROM termine t
                WHERE t.deleted_at IS NULL AND t.status = 'geplant'
                  AND t.beginn >= %(jetzt)s
                  AND LEFT(t.beginn, 10) <= %(bis)s
                  AND (t.mannschaft_id IN (SELECT mannschaft_id FROM kader)
                       OR EXISTS (SELECT 1 FROM termin_zusage z
                                  JOIN ich ON ich.id = z.mitglied_id
                                  WHERE z.termin_id = t.id AND z.deleted_at IS NULL))
                  AND NOT EXISTS (SELECT 1 FROM termin_zusage z2
                                  JOIN ich ON ich.id = z2.mitglied_id
                                  WHERE z2.termin_id = t.id AND z2.deleted_at IS NULL
                                    AND z2.antwort IS NOT NULL)
                """,
                {"uid": user_id, "tag": jetzt[:10],
                 "jetzt": jetzt,
                 "bis": (date.fromisoformat(jetzt[:10])
                         + timedelta(days=tage)).isoformat()},
            )
            return cur.fetchone()['n']

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
                             stichtag: Optional[str] = None,
                             vereinsweit: bool = False) -> list[dict]:
        """Gast-Kandidaten für Termine der Mannschaft: Mitglieder, die NICHT im Kader
        der Mannschaft selbst stehen – eine eigene Kader-Zugehörigkeit ist keine
        Voraussetzung. Ihre Mannschaften und ihre am Stichtag aktiven Funktionen
        (Klarname aus `funktion`) kommen als Auswahl-Label mit.

        Standardmäßig auf die Abteilung der Mannschaft begrenzt (mitglied_abteilung
        am Stichtag). `vereinsweit=True` – für Aufrufer mit dem Recht
        `termine.gaeste_vereinsweit` – lässt diese Schranke weg: für die
        gelegentliche abteilungsübergreifende Runde, in der Praxis über den
        Funktions-Filter der Oberfläche („alle Abteilungsleiter").
        """
        tag = stichtag or date.today().isoformat()
        abteilungs_join = """
                JOIN mitglied_abteilung mab ON mab.mitglied_id = m.id
                    AND mab.deleted_at IS NULL
                    AND (mab.von IS NULL OR mab.von <= %(tag)s)
                    AND (mab.bis IS NULL OR mab.bis >= %(tag)s)
                    AND mab.abteilung_id = (SELECT abteilung_id FROM mannschaft
                                            WHERE id = %(man)s)
        """
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT m.id AS mitglied_id, m.vorname, m.nachname,
                       string_agg(DISTINCT ma.name, ', ' ORDER BY ma.name) AS mannschaften,
                       string_agg(DISTINCT f.name, ', ' ORDER BY f.name) AS funktionen
                FROM mitglied m
                {abteilungs_join if not vereinsweit else ''}
                LEFT JOIN mitglied_mannschaft mm ON mm.mitglied_id = m.id
                    AND mm.deleted_at IS NULL
                    AND mm.von <= %(tag)s AND (mm.bis IS NULL OR mm.bis >= %(tag)s)
                LEFT JOIN mannschaft ma ON ma.id = mm.mannschaft_id AND ma.deleted_at IS NULL
                LEFT JOIN mitglied_funktion mf ON mf.mitglied_id = m.id
                    AND mf.deleted_at IS NULL
                    AND (mf.von IS NULL OR mf.von <= %(tag)s)
                    AND (mf.bis IS NULL OR mf.bis >= %(tag)s)
                LEFT JOIN funktion f ON f.key = mf.funktion AND f.deleted_at IS NULL
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
                 "mannschaften": r['mannschaften'],
                 "funktionen": r['funktionen']}
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

    def list_verwalter_user_ids(self, mannschaft_id: int,
                                stichtag: Optional[str] = None) -> list[int]:
        """user_ids der Betreuer/ÜL einer Mannschaft (mit Benutzerkonto).

        Engerer Kreis als `list_kader_user_ids`: Empfänger für Dinge, die eine
        Entscheidung verlangen statt bloß zu informieren – offene Fragen aus dem
        Spielplan-Import gehen an die, die sie beantworten dürfen, nicht an die
        ganze Mannschaft.
        """
        tag = stichtag or date.today().isoformat()
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT m.user_id
                FROM mitglied m
                JOIN mitglied_mannschaft mm ON mm.mitglied_id = m.id
                    AND mm.deleted_at IS NULL AND mm.mannschaft_id = %(mid)s
                    AND mm.rolle = ANY(%(vroll)s)
                    AND mm.von <= %(tag)s AND (mm.bis IS NULL OR mm.bis >= %(tag)s)
                WHERE m.user_id IS NOT NULL AND m.deleted_at IS NULL
                """,
                {"mid": mannschaft_id, "tag": tag, "vroll": list(VERWALTEN_ROLLEN)},
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
               created_by: str, *, spielstaette_id: int) -> Termin:
        with self.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO termine (mannschaft_id, {', '.join(_EDIT_FIELDS)},
                                     created_by, updated_by)
                VALUES ({', '.join(['%s'] * (len(_EDIT_FIELDS) + 3))})
                RETURNING id
                """,
                (mannschaft_id, typ, beginn, ende, ort, spielstaette_id, treffpunkt,
                 treffpunkt_zeit, gegner, heim_auswaerts, beschreibung,
                 created_by, created_by),
            )
            new_id = cur.fetchone()['id']
        return self.get(new_id)

    def update(self, termin_id: int, typ: str, beginn: str, ende: Optional[str],
               ort: Optional[str], treffpunkt: Optional[str],
               treffpunkt_zeit: Optional[str], gegner: Optional[str],
               heim_auswaerts: Optional[str], beschreibung: Optional[str],
               updated_by: str, expected_version: int, *, spielstaette_id: int) -> bool:
        with self.cursor() as cur:
            cur.execute(
                f"""
                UPDATE termine SET {', '.join(f'{f}=%s' for f in _EDIT_FIELDS)},
                       updated_at=CURRENT_TIMESTAMP, updated_by=%s, version=version+1
                WHERE id=%s AND deleted_at IS NULL AND version=%s
                """,
                (typ, beginn, ende, ort, spielstaette_id, treffpunkt, treffpunkt_zeit,
                 gegner, heim_auswaerts, beschreibung, updated_by, termin_id,
                 expected_version),
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

    # ------------------------------------------------- Spielplan-Import (#95)
    def create_aus_import(self, mannschaft_id: int, *, beginn: str,
                          ort: Optional[str], spielstaette_id: int,
                          gegner: Optional[str], heim_auswaerts: Optional[str],
                          beschreibung: Optional[str], extern_ref: str,
                          extern_stand: dict, created_by: str) -> Termin:
        """Spiel aus dem DFBnet anlegen – mit Kennung und Schnappschuss.

        Eigener Weg statt `create`, weil extern_ref/extern_stand bewusst nicht in
        den änderbaren Fachfeldern stehen: Sie gehören dem Import, nicht dem
        Formular.
        """
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO termine (mannschaft_id, typ, beginn, ort, spielstaette_id,
                    gegner, heim_auswaerts, beschreibung, extern_ref, extern_stand,
                    created_by, updated_by)
                VALUES (%(m)s, 'spiel', %(beginn)s, %(ort)s, %(sst)s, %(gegner)s,
                        %(ha)s, %(besch)s, %(ref)s, %(stand)s, %(usr)s, %(usr)s)
                RETURNING id
                """,
                {"m": mannschaft_id, "beginn": beginn, "ort": ort,
                 "sst": spielstaette_id, "gegner": gegner, "ha": heim_auswaerts,
                 "besch": beschreibung, "ref": extern_ref,
                 "stand": Jsonb(extern_stand), "usr": created_by},
            )
            neu_id = cur.fetchone()['id']
        return self.get(neu_id)

    def update_aus_import(self, termin_id: int, *, werte: dict, extern_stand: dict,
                          spielstaette_id: Optional[int] = None,
                          updated_by: str, expected_version: int) -> bool:
        """Einzelne Felder auf den DFBnet-Stand heben und den Schnappschuss mitziehen.

        Bewusst feldweise: Ein Lauf kann die Zeitverlegung übernehmen, während die
        Platzverlegung als offene Abweichung beim Betreuer liegt (#95, Etappe 4).
        `werte` enthält nur die tatsächlich zu schreibenden Felder aus
        IMPORT_FELDER; `extern_stand` ist der vollständige neue Schnappschuss.

        Treffpunkt, Treffpunktzeit und Beschreibung bleiben unberührt — die pflegt
        das Team.
        """
        unbekannt = set(werte) - set(IMPORT_FELDER)
        if unbekannt:
            raise ValueError(f"Nicht importierbare Felder: {', '.join(sorted(unbekannt))}")
        sets = [f"{f}=%({f})s" for f in werte]
        params = dict(werte)
        if spielstaette_id is not None:
            sets.append("spielstaette_id=%(sst)s")
            params['sst'] = spielstaette_id
        with self.cursor() as cur:
            cur.execute(
                f"""
                UPDATE termine SET {', '.join([*sets, 'extern_stand=%(stand)s'])},
                    updated_at=CURRENT_TIMESTAMP, updated_by=%(usr)s,
                    version=version+1
                WHERE id=%(id)s AND deleted_at IS NULL AND version=%(ver)s
                """,
                params | {"stand": Jsonb(extern_stand), "usr": updated_by,
                          "id": termin_id, "ver": expected_version},
            )
            return cur.rowcount > 0

    def list_importierte(self, mannschaft_ids: list[int], von: str,
                         bis: str) -> list[Termin]:
        """Aktive, geplante Spiele mit DFBnet-Kennung im Zeitraum (ISO-Datum).

        Grundlage für „im Export nicht mehr enthalten": Verglichen wird nur
        innerhalb des Datumsfensters der Datei und nur für Mannschaften, die darin
        überhaupt vorkommen — ein Teil-Export darf nicht den halben Kalender als
        entfallen melden. Abgesagte Termine bleiben außen vor, die Frage ist dort
        schon beantwortet. `von` schneidet der Aufrufer zusätzlich bei heute ab:
        Ein gelaufenes Spiel kann nicht mehr entfallen (s. `_entfallene`).
        """
        if not mannschaft_ids:
            return []
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_COLS} FROM termine
                WHERE mannschaft_id = ANY(%(mids)s) AND extern_ref IS NOT NULL
                  AND deleted_at IS NULL AND status = 'geplant'
                  AND LEFT(beginn, 10) BETWEEN %(von)s AND %(bis)s
                ORDER BY beginn, id
                """,
                {"mids": mannschaft_ids, "von": von, "bis": bis},
            )
            return [_map(r) for r in cur.fetchall()]

    def list_geplante_im_fenster(self, von: str, bis: str) -> list[Termin]:
        """Aktive, geplante Termine ALLER Mannschaften mit beginn im Datumsfenster
        (ISO-Datum, beide inklusiv) – Grundlage des Erinnerungslaufs (#95-Nachgang).

        Ohne Mannschafts-Filter, weil der Lauf keine Sicht eines Users hat: Er
        erinnert im ganzen Verein. Abgesagte bleiben außen vor – zu einem Termin,
        der nicht stattfindet, muss niemand mehr melden.
        """
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT {', '.join('t.' + c.strip() for c in _COLS.split(','))},
                       ma.name AS mannschaft_name,
                       s.name AS spielstaette_name,
                       s.strasse AS spielstaette_strasse, s.plz AS spielstaette_plz,
                       s.ort AS spielstaette_ort, s.untergrund AS spielstaette_untergrund
                FROM termine t
                LEFT JOIN mannschaft ma ON ma.id = t.mannschaft_id
                JOIN spielstaette s ON s.id = t.spielstaette_id
                WHERE t.deleted_at IS NULL AND t.status = 'geplant'
                  AND LEFT(t.beginn, 10) BETWEEN %(von)s AND %(bis)s
                ORDER BY t.beginn, t.id
                """,
                {"von": von, "bis": bis},
            )
            return [_map(r) for r in cur.fetchall()]

    def belegung(self, von: str, bis: str) -> list[Termin]:
        """Alle Termine auf EIGENEN Spielstätten im Datumsfenster – der Belegungsplan (#152).

        Der Zuschnitt unterscheidet sich in drei Punkten bewusst von den übrigen
        Termin-Abfragen, und jeder folgt aus der Frage, die ein Platzwart stellt:

        * **Ohne Kader-Filter.** Wer den Platz mäht, muss jede Belegung sehen, nicht nur
          die seiner Mannschaften. Die Zugangsentscheidung fällt deshalb einmal am
          Endpoint über ein globales Recht, nicht hier über die ACL.
        * **Nur eigene Plätze** (``ist_eigen``). Ein Auswärtsspiel belegt nichts, was
          dieser Verein zu pflegen hätte; die beiden Platzhalter-Zeilen fallen darüber
          ebenfalls heraus.
        * **Abgesagte bleiben drin.** Sie sind für den Platzwart die interessantere
          Information: Der Platz ist an dem Tag doch frei. Die Anzeige markiert sie.

        Kein Personenbezug – Mannschaft, Zeit, Typ und Gegner, mehr nicht.
        """
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT {', '.join('t.' + c.strip() for c in _COLS.split(','))},
                       ma.name AS mannschaft_name,
                       s.name AS spielstaette_name,
                       s.strasse AS spielstaette_strasse, s.plz AS spielstaette_plz,
                       s.ort AS spielstaette_ort, s.untergrund AS spielstaette_untergrund
                FROM termine t
                JOIN spielstaette s ON s.id = t.spielstaette_id
                LEFT JOIN mannschaft ma ON ma.id = t.mannschaft_id
                WHERE t.deleted_at IS NULL AND s.deleted_at IS NULL AND s.ist_eigen
                  AND LEFT(t.beginn, 10) BETWEEN %(von)s AND %(bis)s
                ORDER BY t.spielstaette_id, t.beginn, t.id
                """,
                {"von": von, "bis": bis},
            )
            return [_map(r) for r in cur.fetchall()]

    def set_extern_stand(self, termin_id: int, extern_stand: dict) -> None:
        """Schnappschuss nachtragen, ohne den Termin fachlich zu ändern.

        Für den Fall „App und DFBnet sagen dasselbe, es fehlt nur der Stand":
        bewusst OHNE version-Bump und ohne updated_by – fachlich ist nichts
        passiert, und eine History-Zeile für eine reine Buchhaltungsnotiz wäre
        irreführend.
        """
        with self.cursor() as cur:
            cur.execute(
                "UPDATE termine SET extern_stand = %s WHERE id = %s AND deleted_at IS NULL",
                (Jsonb(extern_stand), termin_id),
            )
