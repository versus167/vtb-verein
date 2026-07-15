"""Repository für Terminserien (#95): wöchentliche Vorlage + rollierende Materialisierung.

Der Generator erzeugt konkrete `termine`-Instanzen bis zum Horizont (HORIZONT_TAGE)
und merkt sich das Wasserzeichen `materialisiert_bis` je Serie. Zwei Schutzmechanismen
gegen Wiedergänger/Duplikate: (1) das Wasserzeichen wird nie rückwärts bewegt —
einzeln gelöschte/abgesagte Instanzen unterhalb werden nie neu erzeugt (auch
prune-sicher); (2) beim Erzeugen wird jedes Datum übersprungen, an dem die Serie
bereits eine aktive Instanz hat (relevant nach Kürzen+Wiederverlängern des Endes).

Serien-Änderungen wirken nur auf zukünftige Instanzen, die noch EXAKT den alten
Serienwerten entsprechen (IS NOT DISTINCT FROM) und 'geplant' sind — individuell
geänderte, abgesagte und vergangene bleiben unberührt. Serie löschen räumt dagegen
ALLE Instanzen ab heute ab (auch geänderte/abgesagte); Vergangenheit bleibt.
ACL (wer darf?) entscheidet die API-Schicht über die Kader-Rollen (TerminRepository).
"""
from datetime import date, timedelta
from typing import Optional

from app.models.termin_serie import TerminSerie
from app.db.base_repository import BaseRepository


# Rollierender Materialisierungs-Horizont (Tage im Voraus).
HORIZONT_TAGE = 56

# Serien nur für wiederkehrende Nicht-Spiel-Termine.
VALID_SERIE_TYPEN = ('training', 'sonstiges')

_COLS = ("id, mannschaft_id, typ, beginn_zeit, ende_zeit, ort, treffpunkt, "
         "treffpunkt_zeit, beschreibung, start_datum, ende_datum, materialisiert_bis, "
         "version, created_at, created_by, updated_at, updated_by, deleted_at, deleted_by")

# Änderbare Fachfelder der Serie (start_datum/Wochentag bewusst NICHT dabei).
_EDIT_FIELDS = ('typ', 'beginn_zeit', 'ende_zeit', 'ort', 'treffpunkt',
                'treffpunkt_zeit', 'beschreibung', 'ende_datum')

# Match „Instanz entspricht noch den Serienwerten %(prefix)s…" — Zeitanteil der
# Wandzeit 'YYYY-MM-DDTHH:MM': Datum = LEFT(beginn,10), Uhrzeit = SUBSTR(beginn,12).
_UNVERAENDERT = """
      AND typ = %({p}typ)s
      AND SUBSTR(beginn, 12) = %({p}beginn_zeit)s
      AND ende IS NOT DISTINCT FROM (CASE WHEN %({p}ende_zeit)s::text IS NULL
            THEN NULL ELSE LEFT(beginn, 10) || 'T' || %({p}ende_zeit)s END)
      AND ort IS NOT DISTINCT FROM %({p}ort)s
      AND treffpunkt IS NOT DISTINCT FROM %({p}treffpunkt)s
      AND treffpunkt_zeit IS NOT DISTINCT FROM %({p}treffpunkt_zeit)s
      AND beschreibung IS NOT DISTINCT FROM %({p}beschreibung)s
"""


def _map(row) -> TerminSerie:
    return TerminSerie(
        id=row['id'], mannschaft_id=row['mannschaft_id'], typ=row['typ'],
        beginn_zeit=row['beginn_zeit'], ende_zeit=row['ende_zeit'], ort=row['ort'],
        treffpunkt=row['treffpunkt'], treffpunkt_zeit=row['treffpunkt_zeit'],
        beschreibung=row['beschreibung'], start_datum=row['start_datum'],
        ende_datum=row['ende_datum'], materialisiert_bis=row['materialisiert_bis'],
        version=row['version'], created_at=row['created_at'], created_by=row['created_by'],
        updated_at=row['updated_at'], updated_by=row['updated_by'],
        deleted_at=row['deleted_at'], deleted_by=row['deleted_by'],
    )


def _wochen_daten(start: str, von_exkl: str, bis_inkl: str) -> list[str]:
    """Wöchentliche Seriendaten (Anker `start`) im Fenster (von_exkl, bis_inkl]."""
    anker = date.fromisoformat(start)
    von = max(date.fromisoformat(von_exkl), anker - timedelta(days=7))
    bis = date.fromisoformat(bis_inkl)
    # erstes k mit anker + 7k > von
    k = max(0, (von - anker).days // 7 + 1)
    daten = []
    d = anker + timedelta(days=7 * k)
    while d <= bis:
        if d > date.fromisoformat(von_exkl):
            daten.append(d.isoformat())
        d += timedelta(days=7)
    return daten


class TerminSerieRepository(BaseRepository):

    # ------------------------------------------------------------------ lesen
    def get(self, serie_id: int) -> Optional[TerminSerie]:
        with self.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM termin_serie WHERE id = %s AND deleted_at IS NULL",
                (serie_id,),
            )
            row = cur.fetchone()
            return _map(row) if row else None

    def list_for_mannschaft(self, mannschaft_id: int) -> list[TerminSerie]:
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_COLS} FROM termin_serie
                WHERE mannschaft_id = %s AND deleted_at IS NULL
                ORDER BY start_datum, beginn_zeit, id
                """,
                (mannschaft_id,),
            )
            return [_map(r) for r in cur.fetchall()]

    # ----------------------------------------------------------------- anlegen
    def create(self, mannschaft_id: int, typ: str, beginn_zeit: str,
               ende_zeit: Optional[str], ort: Optional[str], treffpunkt: Optional[str],
               treffpunkt_zeit: Optional[str], beschreibung: Optional[str],
               start_datum: str, ende_datum: Optional[str], created_by: str) -> TerminSerie:
        """Serie anlegen; Wasserzeichen = gestern (Instanzen frühestens ab heute).
        Materialisiert wird separat (materialize_due) — die API ruft das direkt danach."""
        gestern = (date.today() - timedelta(days=1)).isoformat()
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO termin_serie (mannschaft_id, typ, beginn_zeit, ende_zeit,
                    ort, treffpunkt, treffpunkt_zeit, beschreibung, start_datum,
                    ende_datum, materialisiert_bis, created_by, updated_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (mannschaft_id, typ, beginn_zeit, ende_zeit, ort, treffpunkt,
                 treffpunkt_zeit, beschreibung, start_datum, ende_datum,
                 gestern, created_by, created_by),
            )
            new_id = cur.fetchone()['id']
        return self.get(new_id)

    # ---------------------------------------------------------- Materialisierung
    def materialize_due(self, mannschaft_ids: Optional[list[int]] = None,
                        heute: Optional[str] = None) -> int:
        """Erzeugt fällige Instanzen aller (oder der übergebenen) Mannschaften bis
        zum Horizont. Idempotent und parallel-sicher: das Wasserzeichen wird per
        Vergleichs-UPDATE „geclaimt" (rowcount 0 ⇒ anderer Request war schneller).
        Gibt die Zahl der neu erzeugten Instanzen zurück."""
        tag = heute or date.today().isoformat()
        horizont = (date.fromisoformat(tag) + timedelta(days=HORIZONT_TAGE)).isoformat()
        erzeugt = 0
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_COLS} FROM termin_serie
                WHERE deleted_at IS NULL
                  AND materialisiert_bis < LEAST(%(hor)s, COALESCE(ende_datum, %(hor)s))
                  AND (%(mids)s::int[] IS NULL OR mannschaft_id = ANY(%(mids)s))
                """,
                {"hor": horizont, "mids": mannschaft_ids},
            )
            serien = [_map(r) for r in cur.fetchall()]
            for s in serien:
                ziel = min(horizont, s.ende_datum) if s.ende_datum else horizont
                cur.execute(
                    "UPDATE termin_serie SET materialisiert_bis = %s "
                    "WHERE id = %s AND materialisiert_bis = %s AND deleted_at IS NULL",
                    (ziel, s.id, s.materialisiert_bis),
                )
                if cur.rowcount == 0:      # parallele Anfrage hat schon geclaimt
                    continue
                for d in _wochen_daten(s.start_datum, s.materialisiert_bis, ziel):
                    cur.execute(
                        """
                        INSERT INTO termine (mannschaft_id, serie_id, typ, beginn, ende,
                            ort, treffpunkt, treffpunkt_zeit, beschreibung,
                            created_by, updated_by)
                        SELECT %(mid)s, %(sid)s, %(typ)s, %(beginn)s, %(ende)s,
                               %(ort)s, %(tp)s, %(tpz)s, %(besch)s, %(usr)s, %(usr)s
                        WHERE NOT EXISTS (
                            SELECT 1 FROM termine
                            WHERE serie_id = %(sid)s AND LEFT(beginn, 10) = %(tag)s
                              AND deleted_at IS NULL
                        )
                        """,
                        {"mid": s.mannschaft_id, "sid": s.id, "typ": s.typ,
                         "beginn": f"{d}T{s.beginn_zeit}",
                         "ende": f"{d}T{s.ende_zeit}" if s.ende_zeit else None,
                         "ort": s.ort, "tp": s.treffpunkt, "tpz": s.treffpunkt_zeit,
                         "besch": s.beschreibung, "usr": s.created_by, "tag": d},
                    )
                    erzeugt += cur.rowcount
        return erzeugt

    # ---------------------------------------------------------------- ändern
    def update(self, serie_id: int, typ: str, beginn_zeit: str,
               ende_zeit: Optional[str], ort: Optional[str], treffpunkt: Optional[str],
               treffpunkt_zeit: Optional[str], beschreibung: Optional[str],
               ende_datum: Optional[str], updated_by: str,
               expected_version: int, heute: Optional[str] = None) -> bool:
        """Serie fortschreiben UND die neuen Werte auf zukünftige, noch unveränderte,
        geplante Instanzen anwenden. Reihenfolge: erst Instanzen jenseits eines
        gekürzten Endes löschen (Match gegen ALTE Werte), dann die verbleibenden
        umschreiben. Wasserzeichen wird bei Ende-Kürzung mit heruntergeklemmt,
        damit eine spätere Verlängerung wieder nachmaterialisiert."""
        tag = heute or date.today().isoformat()
        with self.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM termin_serie "
                "WHERE id = %s AND deleted_at IS NULL AND version = %s",
                (serie_id, expected_version),
            )
            row = cur.fetchone()
            if row is None:
                return False
            alt = _map(row)
            alt_params = {f"alt_{f}": getattr(alt, f) for f in
                          ('typ', 'beginn_zeit', 'ende_zeit', 'ort', 'treffpunkt',
                           'treffpunkt_zeit', 'beschreibung')}

            # 1) Serie selbst (version-Guard erneut im WHERE — Transaktion hält den Stand)
            cur.execute(
                """
                UPDATE termin_serie SET typ=%(typ)s, beginn_zeit=%(beginn_zeit)s,
                    ende_zeit=%(ende_zeit)s, ort=%(ort)s, treffpunkt=%(treffpunkt)s,
                    treffpunkt_zeit=%(treffpunkt_zeit)s, beschreibung=%(beschreibung)s,
                    ende_datum=%(ende_datum)s,
                    materialisiert_bis = LEAST(materialisiert_bis,
                                               COALESCE(%(ende_datum)s, materialisiert_bis)),
                    version = version + 1, updated_at = CURRENT_TIMESTAMP,
                    updated_by = %(usr)s
                WHERE id = %(sid)s AND deleted_at IS NULL AND version = %(ver)s
                """,
                {"typ": typ, "beginn_zeit": beginn_zeit, "ende_zeit": ende_zeit,
                 "ort": ort, "treffpunkt": treffpunkt, "treffpunkt_zeit": treffpunkt_zeit,
                 "beschreibung": beschreibung, "ende_datum": ende_datum,
                 "usr": updated_by, "sid": serie_id, "ver": expected_version},
            )
            if cur.rowcount == 0:
                return False

            # 2) Ende gekürzt: unveränderte geplante Instanzen dahinter soft-löschen
            if ende_datum is not None and (alt.ende_datum is None or ende_datum < alt.ende_datum):
                cur.execute(
                    f"""
                    UPDATE termine SET deleted_at = CURRENT_TIMESTAMP,
                        deleted_by = %(usr)s, version = version + 1
                    WHERE serie_id = %(sid)s AND deleted_at IS NULL
                      AND status = 'geplant' AND LEFT(beginn, 10) > %(ende)s
                      {_UNVERAENDERT.format(p='alt_')}
                    """,
                    {"sid": serie_id, "usr": updated_by, "ende": ende_datum, **alt_params},
                )

            # 3) Zukünftige unveränderte geplante Instanzen auf die neuen Werte heben
            cur.execute(
                f"""
                UPDATE termine SET typ = %(typ)s,
                    beginn = LEFT(beginn, 10) || 'T' || %(beginn_zeit)s,
                    ende = (CASE WHEN %(ende_zeit)s::text IS NULL
                            THEN NULL ELSE LEFT(beginn, 10) || 'T' || %(ende_zeit)s END),
                    ort = %(ort)s, treffpunkt = %(treffpunkt)s,
                    treffpunkt_zeit = %(treffpunkt_zeit)s, beschreibung = %(beschreibung)s,
                    version = version + 1, updated_at = CURRENT_TIMESTAMP,
                    updated_by = %(usr)s
                WHERE serie_id = %(sid)s AND deleted_at IS NULL
                  AND status = 'geplant' AND LEFT(beginn, 10) >= %(tag)s
                  {_UNVERAENDERT.format(p='alt_')}
                """,
                {"typ": typ, "beginn_zeit": beginn_zeit, "ende_zeit": ende_zeit,
                 "ort": ort, "treffpunkt": treffpunkt, "treffpunkt_zeit": treffpunkt_zeit,
                 "beschreibung": beschreibung, "usr": updated_by, "sid": serie_id,
                 "tag": tag, **alt_params},
            )
            return True

    # ---------------------------------------------------------------- löschen
    def mark_deleted(self, serie_id: int, deleted_by: str,
                     heute: Optional[str] = None) -> bool:
        """Serie soft-löschen + ALLE Instanzen ab heute (auch individuell geänderte
        und abgesagte). Vergangene Instanzen bleiben als Historie stehen."""
        tag = heute or date.today().isoformat()
        with self.cursor() as cur:
            cur.execute(
                "UPDATE termin_serie SET deleted_at = CURRENT_TIMESTAMP, "
                "deleted_by = %s, version = version + 1 "
                "WHERE id = %s AND deleted_at IS NULL",
                (deleted_by, serie_id),
            )
            if cur.rowcount == 0:
                return False
            cur.execute(
                "UPDATE termine SET deleted_at = CURRENT_TIMESTAMP, "
                "deleted_by = %s, version = version + 1 "
                "WHERE serie_id = %s AND deleted_at IS NULL AND LEFT(beginn, 10) >= %s",
                (deleted_by, serie_id, tag),
            )
            return True
