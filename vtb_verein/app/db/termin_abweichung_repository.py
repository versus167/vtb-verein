"""Repository für Termin-Abweichungen (Schema v84, Ticket #95, Etappe 4).

Die Tabelle ist die Warteschlange offener Fragen aus dem Spielplan-Import. Zwei
Eigenheiten, die den Umgang bestimmen:

* **Melden ist idempotent.** Ein wiederholter Import-Lauf frischt die offene Zeile
  auf, statt eine zweite anzulegen — der partielle Unique-Index (termin_id, feld)
  über ``status='offen'`` erzwingt das auch auf DB-Ebene.
* **Entschiedene Zeilen bleiben stehen.** Sie sind das Protokoll („wer hat wann
  was entschieden") und blockieren keine spätere, erneut auftretende Abweichung —
  deshalb greift der Unique-Index nur auf offene Zeilen.

Der Zugriff läuft über die Kader-ACL des Termins; ein eigenes Recht gibt es nicht.
"""
from typing import Optional

from app.models.termin_abweichung import TerminAbweichung
from app.db.base_repository import BaseRepository

# Status-Werte (identisch zum CHECK in database.py)
STATUS_OFFEN = 'offen'
STATUS_UEBERNOMMEN = 'uebernommen'
STATUS_VERWORFEN = 'verworfen'
# „Hat sich von selbst erledigt": Das Team hat den Termin inzwischen auf den
# DFBnet-Stand gezogen, es gibt nichts mehr zu entscheiden. Bewusst nicht als
# 'verworfen' gebucht – das würde eine Entscheidung behaupten, die niemand traf.
STATUS_HINFAELLIG = 'hinfaellig'
VALID_ENTSCHEIDUNGEN = (STATUS_UEBERNOMMEN, STATUS_VERWORFEN)

# Pseudo-Feld für Spiele, die im Export nicht mehr auftauchen. Ein Termin wird
# deswegen NIE automatisch abgesagt: Der Export ist ein Zeitfenster-Auszug, kein
# Vollbestand — „fehlt" heißt nicht „abgesagt". Praktisch kennt das DFBnet
# Absagen ohnehin kaum; eine Verlegung behält ihre Spielkennung und wird darum
# als Datumsänderung erkannt. Verschwindet ein Spiel trotzdem, wurde es meist
# über das Zeitfenster der Datei hinaus verlegt — seltener wirklich gestrichen
# (Mannschaftsrückzug, Staffel-Umbau).
FELD_ENTFALLEN = 'entfallen'

QUELLE_DFBNET = 'dfbnet'

_COLS = ("id, termin_id, quelle, feld, wert_app, wert_extern, spielstaette_id, "
         "erkannt_am, status, entschieden_von, entschieden_am, version, "
         "created_at, created_by, updated_at, updated_by, deleted_at, deleted_by")


def _map(row) -> TerminAbweichung:
    return TerminAbweichung(
        id=row['id'], termin_id=row['termin_id'], quelle=row['quelle'],
        feld=row['feld'], wert_app=row['wert_app'], wert_extern=row['wert_extern'],
        spielstaette_id=row['spielstaette_id'], erkannt_am=row['erkannt_am'],
        status=row['status'], entschieden_von=row['entschieden_von'],
        entschieden_am=row['entschieden_am'], version=row['version'],
        created_at=row['created_at'], created_by=row['created_by'],
        updated_at=row['updated_at'], updated_by=row['updated_by'],
        deleted_at=row['deleted_at'], deleted_by=row['deleted_by'],
        mannschaft_id=row.get('mannschaft_id'),
        termin_beginn=row.get('termin_beginn'),
        spielstaette_name=row.get('spielstaette_name'),
    )


class TerminAbweichungRepository(BaseRepository):

    # ------------------------------------------------------------------ lesen
    def get(self, abweichung_id: int) -> Optional[TerminAbweichung]:
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT {', '.join('a.' + c.strip() for c in _COLS.split(','))},
                       t.mannschaft_id, t.beginn AS termin_beginn,
                       s.name AS spielstaette_name
                FROM termin_abweichung a
                JOIN termine t ON t.id = a.termin_id
                LEFT JOIN spielstaette s ON s.id = a.spielstaette_id
                WHERE a.id = %s AND a.deleted_at IS NULL
                """,
                (abweichung_id,),
            )
            row = cur.fetchone()
            return _map(row) if row else None

    def list_for_termin(self, termin_id: int, *,
                        nur_offen: bool = False) -> list[TerminAbweichung]:
        """Abweichungen eines Termins – offene zuerst, dann die entschiedenen.

        Das Protokoll gehört mit in den Dialog: Wer sieht, dass die Verlegung
        vorige Woche schon verworfen wurde, entscheidet anders als jemand, der
        nur die offene Frage sieht.
        """
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT {', '.join('a.' + c.strip() for c in _COLS.split(','))},
                       t.mannschaft_id, t.beginn AS termin_beginn,
                       s.name AS spielstaette_name
                FROM termin_abweichung a
                JOIN termine t ON t.id = a.termin_id
                LEFT JOIN spielstaette s ON s.id = a.spielstaette_id
                WHERE a.termin_id = %s AND a.deleted_at IS NULL
                  AND (%s = FALSE OR a.status = 'offen')
                ORDER BY (a.status <> 'offen'), a.erkannt_am DESC, a.id
                """,
                (termin_id, nur_offen),
            )
            return [_map(r) for r in cur.fetchall()]

    def counts_offen(self, termin_ids: list[int]) -> dict[int, int]:
        """Offene Abweichungen je Termin – Grundlage des Badges an der Termin-Karte."""
        if not termin_ids:
            return {}
        with self.cursor() as cur:
            cur.execute(
                "SELECT termin_id, COUNT(*) AS anzahl FROM termin_abweichung "
                "WHERE termin_id = ANY(%s) AND status = 'offen' AND deleted_at IS NULL "
                "GROUP BY termin_id",
                (termin_ids,),
            )
            return {r['termin_id']: r['anzahl'] for r in cur.fetchall()}

    def hat_unerledigte(self, termin_id: int, feld: str) -> bool:
        """Gibt es zu diesem Feld schon eine offene ODER entschiedene Zeile?

        Nur für 'entfallen' gedacht: Dort fehlt der Schnappschuss-Mechanismus, der
        sonst verhindert, dass ein Lauf eine längst beantwortete Frage erneut
        stellt. Eine hinfällige Zeile blockiert bewusst nicht — verschwindet das
        Spiel später wieder, ist das eine neue Frage.
        """
        with self.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM termin_abweichung "
                "WHERE termin_id = %s AND feld = %s AND deleted_at IS NULL "
                "  AND status <> %s LIMIT 1",
                (termin_id, feld, STATUS_HINFAELLIG),
            )
            return cur.fetchone() is not None

    # -------------------------------------------------------------- schreiben
    def melden(self, termin_id: int, feld: str, *, wert_app: Optional[str],
               wert_extern: Optional[str], erkannt_von: str,
               spielstaette_id: Optional[int] = None,
               quelle: str = QUELLE_DFBNET) -> tuple[int, bool]:
        """Abweichung melden – vorhandene offene Zeile wird aufgefrischt.

        Der Import läuft womöglich wöchentlich; jeder Lauf würde sonst dieselbe
        Frage erneut stellen. Beim Auffrischen zieht die `version` mit, die alte
        Fassung steht damit in der History.

        Liefert `(id, neu)`. Das Flag trennt die erste Meldung vom Auffrischen –
        nur bei einer wirklich neuen Frage sollen Betreuer/ÜL benachrichtigt
        werden, sonst pingt jeder wöchentliche Lauf dieselben Leute erneut an.
        """
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE termin_abweichung
                   SET wert_app = %(app)s, wert_extern = %(extern)s,
                       spielstaette_id = %(sst)s, erkannt_am = CURRENT_TIMESTAMP,
                       updated_at = CURRENT_TIMESTAMP, updated_by = %(usr)s,
                       version = version + 1
                 WHERE termin_id = %(tid)s AND feld = %(feld)s
                   AND status = 'offen' AND deleted_at IS NULL
                RETURNING id
                """,
                {"app": wert_app, "extern": wert_extern, "sst": spielstaette_id,
                 "usr": erkannt_von, "tid": termin_id, "feld": feld},
            )
            row = cur.fetchone()
            if row is not None:
                return row['id'], False
            cur.execute(
                """
                INSERT INTO termin_abweichung (termin_id, quelle, feld, wert_app,
                    wert_extern, spielstaette_id, created_by, updated_by)
                VALUES (%(tid)s, %(quelle)s, %(feld)s, %(app)s, %(extern)s,
                        %(sst)s, %(usr)s, %(usr)s)
                RETURNING id
                """,
                {"tid": termin_id, "quelle": quelle, "feld": feld, "app": wert_app,
                 "extern": wert_extern, "sst": spielstaette_id, "usr": erkannt_von},
            )
            return cur.fetchone()['id'], True

    def entscheiden(self, abweichung_id: int, status: str, entschieden_von: str,
                    expected_version: int) -> bool:
        """Offene Abweichung entscheiden (übernommen/verworfen). Nur aus 'offen'
        heraus – eine getroffene Entscheidung wird nicht stillschweigend ersetzt."""
        with self.cursor() as cur:
            cur.execute(
                "UPDATE termin_abweichung SET status = %s, entschieden_von = %s, "
                "entschieden_am = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP, "
                "updated_by = %s, version = version + 1 "
                "WHERE id = %s AND status = 'offen' AND deleted_at IS NULL "
                "  AND version = %s",
                (status, entschieden_von, entschieden_von, abweichung_id,
                 expected_version),
            )
            return cur.rowcount > 0

    def als_hinfaellig(self, termin_id: int, felder: list[str],
                       updated_by: str) -> int:
        """Offene Fragen schließen, die sich erledigt haben – ohne Entscheidung."""
        if not felder:
            return 0
        with self.cursor() as cur:
            cur.execute(
                "UPDATE termin_abweichung SET status = %s, "
                "updated_at = CURRENT_TIMESTAMP, updated_by = %s, version = version + 1 "
                "WHERE termin_id = %s AND feld = ANY(%s) AND status = 'offen' "
                "  AND deleted_at IS NULL",
                (STATUS_HINFAELLIG, updated_by, termin_id, felder),
            )
            return cur.rowcount

    def entfallen_zuruecknehmen(self, termin_ids: list[int], updated_by: str) -> int:
        """'entfallen'-Meldungen schließen, deren Spiel wieder im Export steht."""
        if not termin_ids:
            return 0
        with self.cursor() as cur:
            cur.execute(
                "UPDATE termin_abweichung SET status = %s, "
                "updated_at = CURRENT_TIMESTAMP, updated_by = %s, version = version + 1 "
                "WHERE termin_id = ANY(%s) AND feld = %s AND status = 'offen' "
                "  AND deleted_at IS NULL",
                (STATUS_HINFAELLIG, updated_by, termin_ids, FELD_ENTFALLEN),
            )
            return cur.rowcount

    def mark_deleted(self, abweichung_id: int, deleted_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE termin_abweichung SET deleted_at = CURRENT_TIMESTAMP, "
                "deleted_by = %s, version = version + 1 "
                "WHERE id = %s AND deleted_at IS NULL",
                (deleted_by, abweichung_id),
            )
            return cur.rowcount > 0
