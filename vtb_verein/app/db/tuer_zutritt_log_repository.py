"""Repository für den append-only Zutrittslog (aus v3/lockRecord/list oder importiert).

Idempotenter Sync über das eindeutige `ttlock_record_id` (= recordId der Cloud):
`insert_if_new` nutzt ON CONFLICT DO NOTHING. Zeilen aus einer Fremdanlage
(`quelle='extern'`) haben keine recordId und werden über Schloss + Zeitpunkt + Konto
dedupliziert (`insert_extern_if_new`). Kein Soft-Delete/History – Löschung nur über
das Prune-/DSGVO-Konzept.
"""
from typing import Optional

from psycopg.types.json import Json

from app.models.schliessanlage import (
    TuerZutrittLog, QUELLE_EXTERN, ALARM_RECORD_TYPES, GATEWAY_REMOTE_RECORD_TYPES,
    OEFFNUNG_RECORD_TYPES,
)
from app.db.base_repository import BaseRepository

_SELECT = """
    SELECT l.id, l.ttlock_record_id, l.schloss_id, l.quelle, l.extern_konto,
           l.record_type, l.record_type_from_lock,
           l.methode, l.erfolg, l.credential, l.key_name, l.ttlock_username,
           l.chip_id, l.mitglied_id, l.lock_date, l.server_date, l.raw, l.created_at,
           s.name AS schloss_name, c.bezeichnung AS chip_bezeichnung,
           m.vorname AS mitglied_vorname, m.nachname AS mitglied_nachname,
           cu.username AS chip_user_username
    FROM tuer_zutritt_log l
    LEFT JOIN tuer_schloss s ON s.id = l.schloss_id
    LEFT JOIN schluessel_chip c ON c.id = l.chip_id
    LEFT JOIN mitglied m ON m.id = l.mitglied_id
    LEFT JOIN users cu ON cu.id = c.user_id
"""


def _map(row) -> TuerZutrittLog:
    return TuerZutrittLog(**dict(row))


# --------------------------------------------------------------------- Auswertung
# Alle Zeitangaben der Auswertung sind ORTSZEIT: `lock_date` steht als UTC-ISO in der
# Spalte, „um 6 Uhr aufgeschlossen" meint aber die Uhr an der Tür. Deshalb einmal zentral
# nach Europe/Berlin drehen und als String ausliefern – so kann im Frontend niemand die
# Zeit versehentlich ein zweites Mal umrechnen.
_ORTSZEIT = "(l.lock_date::timestamptz AT TIME ZONE 'Europe/Berlin')"

# Wer war es? Gleiche Auflösungskette wie im Log: Mitglied → Benutzer, auf den der Chip
# läuft → Chip-Bezeichnung → das, was die Anlage selbst mitgeliefert hat. Ausnahme
# Gateway-Fernöffnung: die läuft in der Cloud unter dem Sammelkonto, deren `key_name` ist
# der Kontoname ('ttlock') und wäre in einer Personen-Rangliste schlicht falsch – sie wird
# als eigene „Person" ausgewiesen, bis die Korrelation mit dem access_log den echten
# Auslöser liefert (Phase 5, Teil B).
_WER = """COALESCE(
             NULLIF(TRIM(COALESCE(m.vorname, '') || ' ' || COALESCE(m.nachname, '')), ''),
             cu.username,
             c.bezeichnung,
             CASE WHEN l.record_type = ANY(%(gateway)s) THEN 'Fernöffnung (App)'
                  ELSE l.key_name END,
             l.extern_konto)"""

# Gemeinsamer Filter beider Grundmengen: Zeitraum + Abteilungs-Scope.
_ZEITRAUM_UND_SCOPE = """
      AND (%(ids)s::int[] IS NULL OR l.schloss_id = ANY(%(ids)s))
      AND (%(von)s::timestamptz IS NULL OR l.lock_date::timestamptz >= %(von)s::timestamptz)
"""

# Grundmenge „Öffnungen": erfolgreiche Zutritte mit bekanntem Zeitpunkt.
_OEFFNUNGEN = f"""
WITH ereignis AS (
    SELECT l.schloss_id, l.record_type, l.methode, l.mitglied_id, l.chip_id,
           s.name AS schloss_name, {_WER} AS wer,
           {_ORTSZEIT} AS ortszeit
    FROM tuer_zutritt_log l
    LEFT JOIN tuer_schloss s ON s.id = l.schloss_id
    LEFT JOIN schluessel_chip c ON c.id = l.chip_id
    LEFT JOIN mitglied m ON m.id = l.mitglied_id
    LEFT JOIN users cu ON cu.id = c.user_id
    WHERE l.lock_date IS NOT NULL
      AND l.erfolg IS NOT FALSE
      AND (l.record_type = ANY(%(oeffnung)s)
           OR (l.record_type IS NULL AND l.quelle = %(extern)s))
      {_ZEITRAUM_UND_SCOPE}
)
"""

_ZEITFORMAT = 'YYYY-MM-DD"T"HH24:MI'


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

    def auswertung(self, *, schloss_ids: Optional[list[int]] = None,
                   von: Optional[str] = None, top: int = 8) -> dict:
        """Kennzahlen der Zutritts-Auswertung (#161) – alles serverseitig aggregiert.

        `schloss_ids` schränkt auf die sichtbaren Schlösser ein (None = alle), `von` ist
        der UTC-ISO-Beginn des Zeitraums (None = seit jeher). Zurück kommen rohe Zahlen;
        Anteile, Labels und die Auszeichnungen baut ``zutritt_auswertung_service``.
        """
        p = {
            "ids": list(schloss_ids) if schloss_ids is not None else None,
            "von": von,
            "oeffnung": sorted(OEFFNUNG_RECORD_TYPES),
            "extern": QUELLE_EXTERN,
            "alarm": sorted(ALARM_RECORD_TYPES),
            "gateway": sorted(GATEWAY_REMOTE_RECORD_TYPES),
            "top": top,
        }

        def hole(sql: str) -> list[dict]:
            with self.cursor() as cur:
                cur.execute(_OEFFNUNGEN + sql, p)
                return [dict(r) for r in cur.fetchall()]

        kennzahlen = hole("""
            SELECT count(*) AS oeffnungen,
                   count(DISTINCT ortszeit::date) AS aktive_tage,
                   count(DISTINCT wer) AS akteure,
                   count(DISTINCT schloss_id) AS schloesser,
                   to_char(min(ortszeit), 'YYYY-MM-DD') AS erster_tag,
                   to_char(max(ortszeit), 'YYYY-MM-DD') AS letzter_tag
            FROM ereignis
        """)[0]

        schloesser = hole(f"""
            SELECT schloss_id, COALESCE(schloss_name, '?') AS name, count(*) AS anzahl,
                   to_char(max(ortszeit), '{_ZEITFORMAT}') AS letzte
            FROM ereignis GROUP BY schloss_id, schloss_name
            ORDER BY anzahl DESC, name
        """)

        stunden = hole("""
            SELECT EXTRACT(HOUR FROM ortszeit)::int AS stunde, count(*) AS anzahl
            FROM ereignis GROUP BY 1 ORDER BY 1
        """)

        wochentage = hole("""
            SELECT EXTRACT(ISODOW FROM ortszeit)::int AS tag, count(*) AS anzahl
            FROM ereignis GROUP BY 1 ORDER BY 1
        """)

        # methode als Rückfall für Zeilen ohne erkannten recordType (Fremdanlage).
        methoden = hole("""
            SELECT record_type, min(methode) AS methode, count(*) AS anzahl
            FROM ereignis GROUP BY record_type ORDER BY anzahl DESC
        """)

        personen = hole("""
            SELECT wer, count(*) AS anzahl, count(DISTINCT schloss_id) AS schloesser
            FROM ereignis WHERE wer IS NOT NULL
            GROUP BY wer ORDER BY anzahl DESC, wer LIMIT %(top)s
        """)

        tage = hole("""
            SELECT to_char(ortszeit::date, 'YYYY-MM-DD') AS datum, count(*) AS anzahl
            FROM ereignis GROUP BY 1 ORDER BY 1
        """)

        frueheste = hole(f"""
            SELECT wer, schloss_name, to_char(ortszeit, '{_ZEITFORMAT}') AS zeitpunkt,
                   to_char(ortszeit, 'HH24:MI') AS uhrzeit
            FROM ereignis ORDER BY ortszeit::time ASC, ortszeit ASC LIMIT 1
        """)

        spaeteste = hole(f"""
            SELECT wer, schloss_name, to_char(ortszeit, '{_ZEITFORMAT}') AS zeitpunkt,
                   to_char(ortszeit, 'HH24:MI') AS uhrzeit
            FROM ereignis ORDER BY ortszeit::time DESC, ortszeit DESC LIMIT 1
        """)

        wochenende = hole("""
            SELECT wer, count(*) AS anzahl FROM ereignis
            WHERE wer IS NOT NULL AND EXTRACT(ISODOW FROM ortszeit) >= 6
            GROUP BY wer ORDER BY anzahl DESC, wer LIMIT 1
        """)

        nachtaktiv = hole("""
            SELECT wer, count(*) AS anzahl FROM ereignis
            WHERE wer IS NOT NULL AND EXTRACT(HOUR FROM ortszeit) < 5
            GROUP BY wer ORDER BY anzahl DESC, wer LIMIT 1
        """)

        vielfalt = hole("""
            SELECT wer, count(DISTINCT schloss_id) AS schloesser, count(*) AS anzahl
            FROM ereignis WHERE wer IS NOT NULL
            GROUP BY wer ORDER BY schloesser DESC, anzahl DESC, wer LIMIT 1
        """)

        # Fehlversuche und Alarme liegen außerhalb der Öffnungs-Grundmenge – dafür noch
        # einmal über die Rohzeilen mit demselben Zeitraum/Scope.
        with self.cursor() as cur:
            cur.execute(f"""
                SELECT count(*) FILTER (WHERE l.erfolg IS FALSE) AS fehlversuche,
                       count(*) FILTER (WHERE l.record_type = ANY(%(alarm)s)) AS alarme,
                       count(*) AS ereignisse
                FROM tuer_zutritt_log l
                WHERE l.lock_date IS NOT NULL
                  {_ZEITRAUM_UND_SCOPE}
            """, p)
            roh = dict(cur.fetchone())

        return {
            "kennzahlen": {**kennzahlen, **roh},
            "schloesser": schloesser,
            "stunden": stunden,
            "wochentage": wochentage,
            "methoden": methoden,
            "personen": personen,
            "tage": tage,
            "frueheste": frueheste[0] if frueheste else None,
            "spaeteste": spaeteste[0] if spaeteste else None,
            "wochenende": wochenende[0] if wochenende else None,
            "nachtaktiv": nachtaktiv[0] if nachtaktiv else None,
            "vielfalt": vielfalt[0] if vielfalt else None,
        }

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

    def list_selbstauskunft(self, *, mitglied_id: Optional[int] = None,
                            chip_ids: tuple[int, ...] = (),
                            limit: int = 50) -> list[TuerZutrittLog]:
        """Eigene Zutritte des eingeloggten Users (Self-Service), aus beiden Quellen.

        Wer einen Mitgliedsdatensatz hat, findet sich über die im Log aufgelöste
        `mitglied_id` (historisch korrekt: sie steht in der Zeile). Wer keinen hat,
        aber Chips auf seinem Benutzerkonto, wird über diese Chips gefunden — dort
        gibt es keine Spur in der Log-Zeile, also zählt der heutige Inhaber.
        """
        if mitglied_id is None and not chip_ids:
            return []
        with self.cursor() as cur:
            cur.execute(
                _SELECT + """
                WHERE l.mitglied_id = %(mid)s     -- NULL trifft nichts: kein Mitglied
                   OR l.chip_id = ANY(%(chips)s::int[])
                ORDER BY l.lock_date DESC NULLS LAST, l.id DESC
                LIMIT %(limit)s
                """,
                {"mid": mitglied_id, "chips": list(chip_ids), "limit": limit},
            )
            return [_map(r) for r in cur.fetchall()]
