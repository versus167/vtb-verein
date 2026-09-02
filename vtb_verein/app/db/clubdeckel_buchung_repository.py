"""Ledger der Teamkasse (#98): clubdeckel_buchung.

Eine Zeile pro Vorgang und Mitglied; Saldo je Mitglied = SUM(betrag) über aktive
Zeilen, Team-Saldo = −Σ Mitgliedssalden. Konventionen:

- konsum:   betrag = -(menge * artikel.preis) — Preis-Snapshot. Verkauft die
            Artikel-GRUPPE über ein Mitglied (verkaeufer_mitglied_id), entsteht
            zusätzlich die Gegenzeile typ 'verkauf' (+betrag) beim Verkäufer,
            verknüpft über paar_ref (Nullsumme, Team unberührt).
- einkauf:  Team kauft vom Mitglied (z. B. Kasten Bier geliefert) → +betrag.
- zahlung:  Mitglied zahlt an Mitglied (bar/PayPal/…) → PAAR: +betrag beim
            Zahler (Schuld sinkt), −betrag beim Empfänger, gemeinsame paar_ref.
- event:    einmalige Sammlung auf den Kader (#181) → −betrag, event_id.
            Gebucht wird gegen das Team, also eine Einzelzeile wie 'beitrag'.
            Anders als dort zählt beim Nachbuchen nur eine AKTIVE Zeile als
            erledigt: Ein Event bucht immer ein Mensch, und der will nach dem
            Storno („falscher Betrag") korrigieren und erneut buchen können.
- beitrag:  Monatspauschale → −betrag, beitrag_monat 'YYYY-MM'. Automatisch
            nachgebucht über buche_faellige_beitraege; ein Monat gilt als
            erledigt, sobald IRGENDEINE Beitragszeile existiert (auch storniert
            — Storno heißt „erlassen", nicht „bitte nochmal").

Storno einer Paar-Zeile löscht immer das ganze Paar.

termin_id (#167) hält fest, bei welchem Termin gebucht wurde. Sie ist rein
beschreibend — auf Salden und Nullsummen wirkt sie nicht, dient aber als Filter
für Matrix und Tages-/Termin-Auswertung.
"""
import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from app.models.clubdeckel import ClubdeckelBuchung
from app.db.base_repository import BaseRepository

_COLS = ("id, deckel_id, mitglied_id, artikel_id, typ, menge, betrag, "
         "paar_ref, beitrag_monat, notiz, artikel_name, gegen_name, termin_id, "
         "event_id, version, created_at, created_by, updated_at, updated_by, "
         "deleted_at, deleted_by")
_B_COLS = ", ".join("b." + c.strip() for c in _COLS.split(","))

# Anzeigetext eines Termins („Spiel 16.08. 15:00") – als Snapshot NICHT nötig, der
# Termin lebt weiter; deshalb per JOIN aufgelöst statt eingefroren wie artikel_name.
_TERMIN_LABEL = (
    "CASE WHEN t.id IS NULL THEN NULL ELSE "
    "  initcap(t.typ) || ' ' || to_char("
    "    to_timestamp(t.beginn, 'YYYY-MM-DD\"T\"HH24:MI'), 'DD.MM. HH24:MI') END"
)


def _map(row) -> ClubdeckelBuchung:
    return ClubdeckelBuchung(**dict(row))


def _monate(ab: str, bis: str) -> list[str]:
    """Alle Monate 'YYYY-MM' von ab bis bis (beide inklusiv)."""
    jahr, monat = int(ab[:4]), int(ab[5:7])
    ende_jahr, ende_monat = int(bis[:4]), int(bis[5:7])
    result = []
    while (jahr, monat) <= (ende_jahr, ende_monat):
        result.append(f"{jahr:04d}-{monat:02d}")
        monat += 1
        if monat > 12:
            jahr, monat = jahr + 1, 1
    return result


class ClubdeckelBuchungRepository(BaseRepository):

    def get(self, buchung_id: int,
            include_deleted: bool = False) -> Optional[ClubdeckelBuchung]:
        """Eine Buchung lesen. include_deleted=True liefert auch stornierte
        Zeilen (für das Wiederherstellen, #127)."""
        filt = "" if include_deleted else " AND deleted_at IS NULL"
        with self.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM clubdeckel_buchung WHERE id = %s{filt}",
                (buchung_id,),
            )
            row = cur.fetchone()
            return _map(row) if row else None

    def list_for_deckel(self, deckel_id: int, mitglied_id: Optional[int] = None,
                        limit: Optional[int] = None,
                        mit_storniert: bool = False,
                        suche: Optional[str] = None,
                        von: Optional[str] = None, bis: Optional[str] = None,
                        termin_id: Optional[int] = None) -> list[ClubdeckelBuchung]:
        """Buchungen, neueste zuerst — optional nur die eines Mitglieds.
        mit_storniert=True nimmt auch soft-gelöschte Zeilen mit (deleted_at
        gesetzt); die History kann sie dann optional einblenden (#127).
        suche filtert volltextig (ILIKE) über Mitgliedsname, Typ, die
        eingefrorenen Artikel-/Gegenkonto-Bezeichnungen, Notiz und
        Beitragsmonat (#129).
        von/bis (ISO-Zeitstempel) und termin_id grenzen den Tag- bzw.
        Termin-Ausschnitt ein (#167); termin_id sticht das Zeitfenster."""
        filt = "" if mit_storniert else " AND b.deleted_at IS NULL"
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_B_COLS},
                       m.vorname || ' ' || m.nachname AS mitglied_name,
                       {_TERMIN_LABEL} AS termin_label
                FROM clubdeckel_buchung b
                JOIN mitglied m ON m.id = b.mitglied_id
                LEFT JOIN termine t ON t.id = b.termin_id
                WHERE b.deckel_id = %(did)s{filt}
                  AND (%(mid)s::int IS NULL OR b.mitglied_id = %(mid)s)
                  AND (%(tid)s::int IS NULL OR b.termin_id = %(tid)s)
                  AND (%(tid)s::int IS NOT NULL
                       OR ((%(von)s::timestamptz IS NULL
                            OR b.created_at >= %(von)s::timestamptz)
                       AND (%(bis)s::timestamptz IS NULL
                            OR b.created_at < %(bis)s::timestamptz)))
                  AND (%(q)s::text IS NULL OR concat_ws(' ',
                       m.vorname, m.nachname, b.typ, b.artikel_name,
                       b.gegen_name, b.notiz, b.beitrag_monat)
                       ILIKE '%%' || %(q)s || '%%')
                ORDER BY b.created_at DESC, b.id DESC
                LIMIT %(lim)s
                """,
                {"did": deckel_id, "mid": mitglied_id, "lim": limit, "q": suche,
                 "von": von, "bis": bis, "tid": termin_id},
            )
            return [_map(r) for r in cur.fetchall()]

    def matrix(self, deckel_id: int, von: Optional[str] = None,
               bis: Optional[str] = None,
               termin_id: Optional[int] = None) -> dict:
        """Konsum-Gitter Mitglied × Artikel für einen Zeitraum oder einen Termin
        (#167, Vorbild consumptions.php des Club-Tresors).

        Liefert die Zellen (Menge + Betrag je Paar) sowie die Randsummen je
        Artikel und je Mitglied und die Gesamtsumme — alles aus EINEM Aggregat,
        damit Matrix und Tages-/Termin-Auswertung nie auseinanderlaufen können.
        Beträge sind hier positive Verbrauchswerte (−betrag), weil das Gitter
        „was wurde konsumiert" zeigt und kein Saldo ist.

        Gezählt wird nur typ='konsum': 'verkauf' ist die Gegenzeile desselben
        Vorgangs (sonst stünde jedes Bier doppelt im Gitter), und Zahlungen,
        Ein-/Verkäufe und Beiträge sind kein Tresenverbrauch.

        termin_id sticht das Zeitfenster: „was lief beim Spiel" ist eine andere
        Frage als „was lief zwischen 14 und 18 Uhr".
        """
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT b.mitglied_id, b.artikel_id,
                       m.vorname || ' ' || m.nachname AS mitglied_name,
                       COALESCE(SUM(b.menge), 0) AS anzahl,
                       COALESCE(SUM(-b.betrag), 0) AS betrag
                FROM clubdeckel_buchung b
                JOIN mitglied m ON m.id = b.mitglied_id
                WHERE b.deckel_id = %(did)s AND b.deleted_at IS NULL
                  AND b.typ = 'konsum'
                  AND (%(tid)s::int IS NULL OR b.termin_id = %(tid)s)
                  AND (%(tid)s::int IS NOT NULL
                       OR ((%(von)s::timestamptz IS NULL
                            OR b.created_at >= %(von)s::timestamptz)
                       AND (%(bis)s::timestamptz IS NULL
                            OR b.created_at < %(bis)s::timestamptz)))
                GROUP BY b.mitglied_id, b.artikel_id, m.vorname, m.nachname
                """,
                {"did": deckel_id, "von": von, "bis": bis, "tid": termin_id},
            )
            rows = cur.fetchall()
        zellen: dict[str, dict] = {}
        je_artikel: dict[int, dict] = {}
        je_mitglied: dict[int, dict] = {}
        gesamt = Decimal('0')
        for r in rows:
            anzahl, betrag = int(r['anzahl']), r['betrag']
            gesamt += betrag
            mid, aid = r['mitglied_id'], r['artikel_id']
            m = je_mitglied.setdefault(mid, {
                "mitglied_id": mid, "mitglied_name": r['mitglied_name'],
                "anzahl": 0, "betrag": Decimal('0')})
            m['anzahl'] += anzahl
            m['betrag'] += betrag
            if aid is None:
                # Artikel hart gelöscht (Prune) – zählt in die Mitglieds- und
                # Gesamtsumme, hat aber keine Spalte mehr.
                continue
            zellen[f"{mid}:{aid}"] = {"anzahl": anzahl, "betrag": betrag}
            a = je_artikel.setdefault(aid, {
                "artikel_id": aid, "anzahl": 0, "betrag": Decimal('0')})
            a['anzahl'] += anzahl
            a['betrag'] += betrag
        return {
            "zellen": zellen,
            "je_artikel": je_artikel,
            "je_mitglied": sorted(je_mitglied.values(),
                                  key=lambda x: x['mitglied_name'].lower()),
            "gesamt": gesamt,
        }

    # ---------------------------------------------------------------- buchen
    def create_konsum(self, deckel_id: int, mitglied_id: int, artikel_id: int,
                      artikel_name: str, menge: int, preis: Decimal,
                      verkaeufer_mitglied_id: Optional[int],
                      created_by: str,
                      termin_id: Optional[int] = None,
                      wert_datum: Optional[str] = None) -> ClubdeckelBuchung:
        """Kauf eines Artikels durch ein Mitglied. Verkauft ein MITGLIED
        (Gruppen-Verkäufer), wird die 'verkauf'-Gegenzeile mitgebucht.
        termin_id landet auf BEIDEN Zeilen des Paares (#167) — sonst hinge die
        Gegenzeile an keinem Termin und die Termin-Auswertung wäre unvollständig.
        wert_datum (ISO) setzt bei Bedarf den Buchungszeitpunkt: Beim Umstellen
        auf einen neuen Sortiments-Stand behält die Ersatzbuchung die Uhrzeit der
        ursprünglichen, sonst rutschte der Strich in der Tagesansicht nach vorn."""
        betrag = preis * menge
        paar_ref = uuid.uuid4().hex if verkaeufer_mitglied_id else None
        with self.cursor() as cur:
            # Käufer-Zeile: Bezeichnung + Verkäufer ('Team', sonst Mitglied) einfrieren.
            cur.execute(
                "INSERT INTO clubdeckel_buchung "
                "(deckel_id, mitglied_id, artikel_id, typ, menge, betrag, paar_ref, "
                " artikel_name, gegen_name, termin_id, created_at, created_by, updated_by) "
                "VALUES (%s,%s,%s,'konsum',%s,%s,%s,%s,"
                " COALESCE((SELECT vorname||' '||nachname FROM mitglied WHERE id=%s),"
                "          'Team'), %s,"
                " COALESCE(%s::timestamptz, CURRENT_TIMESTAMP), %s,%s) RETURNING id",
                (deckel_id, mitglied_id, artikel_id, menge, -betrag, paar_ref,
                 artikel_name, verkaeufer_mitglied_id, termin_id, wert_datum,
                 created_by, created_by),
            )
            new_id = cur.fetchone()['id']
            if verkaeufer_mitglied_id:
                # Verkäufer-Gegenzeile: Gegenkonto = der Käufer.
                cur.execute(
                    "INSERT INTO clubdeckel_buchung "
                    "(deckel_id, mitglied_id, artikel_id, typ, menge, betrag, "
                    " paar_ref, artikel_name, gegen_name, termin_id, "
                    " created_at, created_by, updated_by) "
                    "VALUES (%s,%s,%s,'verkauf',%s,%s,%s,%s,"
                    " (SELECT vorname||' '||nachname FROM mitglied WHERE id=%s),"
                    " %s, COALESCE(%s::timestamptz, CURRENT_TIMESTAMP), %s,%s)",
                    (deckel_id, verkaeufer_mitglied_id, artikel_id, menge, betrag,
                     paar_ref, artikel_name, mitglied_id, termin_id, wert_datum,
                     created_by, created_by),
                )
        return self.get(new_id)

    def konsum_je_artikel(self, deckel_id: int, termin_id: int,
                          artikel_ids: list[int]) -> list[dict]:
        """Aktive Konsum-Buchungen eines Termins zu bestimmten Artikeln — die
        Grundlage fürs Umstellen auf einen neuen Sortiments-Stand (#167).

        Nur die 'konsum'-Zeilen: Die 'verkauf'-Gegenzeilen hängen über paar_ref
        daran und werden vom Storno ohnehin mitgenommen.
        """
        if not artikel_ids:
            return []
        with self.cursor() as cur:
            cur.execute(
                "SELECT id, mitglied_id, artikel_id, menge, created_at "
                "FROM clubdeckel_buchung "
                "WHERE deckel_id = %s AND termin_id = %s AND typ = 'konsum' "
                "  AND deleted_at IS NULL AND artikel_id = ANY(%s) "
                "ORDER BY created_at, id",
                (deckel_id, termin_id, list(artikel_ids)),
            )
            return [dict(r) for r in cur.fetchall()]

    def zaehle_konsum_fuer_termin(self, deckel_id: int, termin_id: int) -> dict:
        """Wie viel wurde bei diesem Termin schon gebucht? Der Katalog fragt das,
        bevor er einen Stand ändert — sonst wüsste niemand, dass es überhaupt
        etwas umzustellen gibt."""
        with self.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS anzahl, COALESCE(SUM(-betrag), 0) AS betrag "
                "FROM clubdeckel_buchung "
                "WHERE deckel_id = %s AND termin_id = %s AND typ = 'konsum' "
                "  AND deleted_at IS NULL",
                (deckel_id, termin_id),
            )
            return dict(cur.fetchone())

    def create_einkauf(self, deckel_id: int, mitglied_id: int, betrag: Decimal,
                       notiz: Optional[str], created_by: str) -> ClubdeckelBuchung:
        """Team kauft vom Mitglied (betrag > 0 = Guthaben des Mitglieds)."""
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO clubdeckel_buchung "
                "(deckel_id, mitglied_id, typ, betrag, notiz, gegen_name, "
                " created_by, updated_by) "
                "VALUES (%s,%s,'einkauf',%s,%s,'Team',%s,%s) RETURNING id",
                (deckel_id, mitglied_id, betrag, notiz, created_by, created_by),
            )
            new_id = cur.fetchone()['id']
        return self.get(new_id)

    def create_an_verkauf(self, deckel_id: int, mitglied_id: int,
                          gegen_mitglied_id: Optional[int], verkauft: bool,
                          betrag: Decimal, notiz: Optional[str], created_by: str,
                          wert_datum: Optional[str] = None):
        """An-/Verkauf des Mitglieds gegen ein Gegenkonto (Team oder Mitglied).

        - verkauft=False: Mitglied kauft (Belastung −betrag).
        - verkauft=True:  Mitglied verkauft (Gutschrift +betrag).
        Gegenkonto Team (gegen_mitglied_id=None): Einzelzeile ('kauf'/'einkauf'),
        das Team ist die Gegensumme. Gegenkonto Mitglied: Nullsummen-Paar mit
        gemeinsamer paar_ref ('kauf' beim Käufer, 'verkauf' beim Verkäufer).
        wert_datum (ISO) setzt bei Bedarf das Buchungsdatum (sonst jetzt).
        """
        m_betrag = betrag if verkauft else -betrag
        with self.cursor() as cur:
            if gegen_mitglied_id is None:
                typ = 'einkauf' if verkauft else 'kauf'
                cur.execute(
                    "INSERT INTO clubdeckel_buchung "
                    "(deckel_id, mitglied_id, typ, betrag, notiz, gegen_name, "
                    " created_at, created_by, updated_by) "
                    "VALUES (%s,%s,%s,%s,%s,'Team',"
                    " COALESCE(%s::timestamptz, CURRENT_TIMESTAMP), %s,%s) RETURNING id",
                    (deckel_id, mitglied_id, typ, m_betrag, notiz, wert_datum,
                     created_by, created_by),
                )
                return cur.fetchone()['id']
            ref = uuid.uuid4().hex
            m_typ = 'verkauf' if verkauft else 'kauf'
            g_typ = 'kauf' if verkauft else 'verkauf'
            # Gegenkonto je Zeile = die jeweils andere Seite (Snapshot des Namens).
            for mid, b, typ, gegen in ((mitglied_id, m_betrag, m_typ, gegen_mitglied_id),
                                       (gegen_mitglied_id, -m_betrag, g_typ, mitglied_id)):
                cur.execute(
                    "INSERT INTO clubdeckel_buchung "
                    "(deckel_id, mitglied_id, typ, betrag, paar_ref, notiz, gegen_name, "
                    " created_at, created_by, updated_by) "
                    "VALUES (%s,%s,%s,%s,%s,%s,"
                    " (SELECT vorname||' '||nachname FROM mitglied WHERE id=%s),"
                    " COALESCE(%s::timestamptz, CURRENT_TIMESTAMP), %s,%s)",
                    (deckel_id, mid, typ, b, ref, notiz, gegen, wert_datum,
                     created_by, created_by),
                )
            return ref

    def create_zahlung(self, deckel_id: int, von_mitglied_id: int,
                       an_mitglied_id: int, betrag: Decimal,
                       notiz: Optional[str], created_by: str,
                       wert_datum: Optional[str] = None) -> str:
        """Zahlung von A an B (betrag > 0): +betrag beim Zahler A (Schuld sinkt),
        −betrag beim Empfänger B (hält das Geld). Gemeinsame paar_ref.
        wert_datum (ISO) setzt bei Bedarf das Buchungsdatum (sonst jetzt)."""
        ref = uuid.uuid4().hex
        with self.cursor() as cur:
            # Zahler-Zeile: Gegenkonto = Empfänger; Empfänger-Zeile: = Zahler.
            for mid, b, gegen in ((von_mitglied_id, betrag, an_mitglied_id),
                                  (an_mitglied_id, -betrag, von_mitglied_id)):
                cur.execute(
                    "INSERT INTO clubdeckel_buchung "
                    "(deckel_id, mitglied_id, typ, betrag, paar_ref, notiz, gegen_name, "
                    " created_at, created_by, updated_by) "
                    "VALUES (%s,%s,'zahlung',%s,%s,%s,"
                    " (SELECT vorname||' '||nachname FROM mitglied WHERE id=%s),"
                    " COALESCE(%s::timestamptz, CURRENT_TIMESTAMP), %s,%s)",
                    (deckel_id, mid, b, ref, notiz, gegen, wert_datum,
                     created_by, created_by),
                )
        return ref

    # --------------------------------------------------------------- Beitrag
    def buche_faellige_beitraege(self, deckel_id: int, mannschaft_id: int,
                                 beitrag: Decimal, ab_monat: str,
                                 bis_monat: Optional[str] = None) -> int:
        """Bucht offene Monatsbeiträge nach (Lazy-Lauf beim Zugriff, Muster
        „rollierend materialisieren" wie Terminserien). Beitragspflichtig für
        Monat M ist, wer am Monatsersten aktiv im Kader steht und nicht befreit
        ist; ein Monat mit vorhandener Beitragszeile (auch storniert) wird
        übersprungen. Gibt die Zahl der neu gebuchten Zeilen zurück."""
        bis = bis_monat or date.today().strftime('%Y-%m')
        gebucht = 0
        with self.cursor() as cur:
            for monat in _monate(ab_monat, bis):
                erster = f"{monat}-01"
                cur.execute(
                    """
                    INSERT INTO clubdeckel_buchung
                        (deckel_id, mitglied_id, typ, betrag, beitrag_monat, notiz,
                         gegen_name, created_by, updated_by)
                    SELECT DISTINCT %(did)s, mm.mitglied_id, 'beitrag', %(betrag)s,
                           %(monat)s, %(notiz)s, 'Team', 'beitrag_auto', 'beitrag_auto'
                    FROM mitglied_mannschaft mm
                    JOIN mitglied m ON m.id = mm.mitglied_id AND m.deleted_at IS NULL
                    WHERE mm.mannschaft_id = %(man)s AND mm.deleted_at IS NULL
                      AND mm.von <= %(erster)s
                      AND (mm.bis IS NULL OR mm.bis >= %(erster)s)
                      AND NOT EXISTS (
                          SELECT 1 FROM clubdeckel_beitrag_befreiung bf
                          WHERE bf.deckel_id = %(did)s AND bf.mitglied_id = mm.mitglied_id
                            AND bf.deleted_at IS NULL)
                      AND NOT EXISTS (
                          SELECT 1 FROM clubdeckel_buchung alt
                          WHERE alt.deckel_id = %(did)s AND alt.mitglied_id = mm.mitglied_id
                            AND alt.typ = 'beitrag' AND alt.beitrag_monat = %(monat)s)
                    """,
                    {"did": deckel_id, "man": mannschaft_id, "betrag": -beitrag,
                     "monat": monat, "erster": erster,
                     "notiz": f"Mannschaftsbeitrag {monat}"},
                )
                gebucht += cur.rowcount
        return gebucht

    # ----------------------------------------------------------------- event
    def buche_event(self, deckel_id: int, mannschaft_id: int, event_id: int,
                    name: str, betrag: Decimal, fuer_mitglied_id: Optional[int],
                    created_by: str, stichtag: Optional[str] = None) -> int:
        """Bucht eine Sammlung auf den Kader (#181) — je Teilnehmer eine Zeile
        typ='event' über −betrag gegen das Team.

        Teilnehmer ist, wer am Stichtag (Vorgabe: heute) aktiv im Kader steht,
        NICHT das Mitglied ist, für das gesammelt wird, und keinen generellen
        Opt-out hat. Wer schon eine aktive Zeile zu diesem Event hat, wird
        übersprungen — ein zweiter Klick auf „Buchen" holt also nur die Nachzügler
        (z. B. einen frisch entfernten Opt-out) nach, statt doppelt zu belasten.

        Der Event-Name wandert als Snapshot in die Notiz: Die History soll auch
        dann noch lesbar sein, wenn das Event längst umbenannt oder geprunt ist.
        Gibt die Zahl der neu gebuchten Zeilen zurück.
        """
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO clubdeckel_buchung
                    (deckel_id, mitglied_id, typ, betrag, event_id, notiz,
                     gegen_name, created_by, updated_by)
                SELECT DISTINCT %(did)s, mm.mitglied_id, 'event', %(betrag)s,
                       %(eid)s, %(notiz)s, 'Team', %(actor)s, %(actor)s
                FROM mitglied_mannschaft mm
                JOIN mitglied m ON m.id = mm.mitglied_id AND m.deleted_at IS NULL
                WHERE mm.mannschaft_id = %(man)s AND mm.deleted_at IS NULL
                  AND mm.von <= %(tag)s
                  AND (mm.bis IS NULL OR mm.bis >= %(tag)s)
                  AND mm.mitglied_id IS DISTINCT FROM %(fuer)s::int
                  AND NOT EXISTS (
                      SELECT 1 FROM clubdeckel_event_opt_out o
                      WHERE o.deckel_id = %(did)s AND o.mitglied_id = mm.mitglied_id
                        AND o.deleted_at IS NULL)
                  AND NOT EXISTS (
                      SELECT 1 FROM clubdeckel_buchung alt
                      WHERE alt.deckel_id = %(did)s AND alt.mitglied_id = mm.mitglied_id
                        AND alt.typ = 'event' AND alt.event_id = %(eid)s
                        AND alt.deleted_at IS NULL)
                """,
                {"did": deckel_id, "man": mannschaft_id, "eid": event_id,
                 "betrag": -betrag, "notiz": name, "actor": created_by,
                 "fuer": fuer_mitglied_id,
                 "tag": stichtag or date.today().isoformat()},
            )
            return cur.rowcount

    def storno_event(self, deckel_id: int, event_id: int, deleted_by: str) -> int:
        """Nimmt eine ganze Sammlung zurück — alle aktiven Zeilen des Events auf
        einmal. Einzeln ginge auch (storno()), wäre bei zwölf Mitgliedern aber
        zwölf Klicks. Gibt die Zahl der stornierten Zeilen zurück."""
        with self.cursor() as cur:
            cur.execute(
                "UPDATE clubdeckel_buchung "
                "SET deleted_at=CURRENT_TIMESTAMP, deleted_by=%s, version=version+1 "
                "WHERE deckel_id=%s AND event_id=%s AND typ='event' "
                "  AND deleted_at IS NULL",
                (deleted_by, deckel_id, event_id),
            )
            return cur.rowcount

    # ---------------------------------------------------------------- storno
    def storno(self, buchung_id: int, deleted_by: str) -> bool:
        """Soft-Delete einer Buchung; bei Paaren (paar_ref) immer beide Zeilen,
        damit die Nullsumme erhalten bleibt."""
        with self.cursor() as cur:
            cur.execute(
                "SELECT deckel_id, paar_ref FROM clubdeckel_buchung "
                "WHERE id = %s AND deleted_at IS NULL",
                (buchung_id,),
            )
            row = cur.fetchone()
            if row is None:
                return False
            if row['paar_ref']:
                cur.execute(
                    "UPDATE clubdeckel_buchung "
                    "SET deleted_at=CURRENT_TIMESTAMP, deleted_by=%s, version=version+1 "
                    "WHERE deckel_id=%s AND paar_ref=%s AND deleted_at IS NULL",
                    (deleted_by, row['deckel_id'], row['paar_ref']),
                )
            else:
                cur.execute(
                    "UPDATE clubdeckel_buchung "
                    "SET deleted_at=CURRENT_TIMESTAMP, deleted_by=%s, version=version+1 "
                    "WHERE id=%s AND deleted_at IS NULL",
                    (deleted_by, buchung_id),
                )
            return cur.rowcount > 0

    def restore(self, buchung_id: int, restored_by: str) -> bool:
        """Storno zurücknehmen (#127): un-delete einer soft-gelöschten Buchung;
        bei Paaren (paar_ref) immer beide Zeilen, damit die Nullsumme erhalten
        bleibt. Gegenstück zu storno(). version+1 → Audit-History-Eintrag."""
        with self.cursor() as cur:
            cur.execute(
                "SELECT deckel_id, paar_ref FROM clubdeckel_buchung "
                "WHERE id = %s AND deleted_at IS NOT NULL",
                (buchung_id,),
            )
            row = cur.fetchone()
            if row is None:
                return False
            if row['paar_ref']:
                cur.execute(
                    "UPDATE clubdeckel_buchung "
                    "SET deleted_at=NULL, deleted_by=NULL, updated_at=CURRENT_TIMESTAMP, "
                    "    updated_by=%s, version=version+1 "
                    "WHERE deckel_id=%s AND paar_ref=%s AND deleted_at IS NOT NULL",
                    (restored_by, row['deckel_id'], row['paar_ref']),
                )
            else:
                cur.execute(
                    "UPDATE clubdeckel_buchung "
                    "SET deleted_at=NULL, deleted_by=NULL, updated_at=CURRENT_TIMESTAMP, "
                    "    updated_by=%s, version=version+1 "
                    "WHERE id=%s AND deleted_at IS NOT NULL",
                    (restored_by, buchung_id),
                )
            return cur.rowcount > 0

    # ---------------------------------------------------------------- salden
    def salden(self, deckel_id: int) -> list[dict]:
        """Deckelstand je Mitglied (nur Mitglieder mit aktiven Buchungen),
        höchstes Guthaben zuerst (#127). Team-Saldo = −Summe (rechnet die API)."""
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT b.mitglied_id,
                       m.vorname || ' ' || m.nachname AS mitglied_name,
                       SUM(b.betrag) AS saldo,
                       COUNT(*) AS buchungen
                FROM clubdeckel_buchung b
                JOIN mitglied m ON m.id = b.mitglied_id
                WHERE b.deckel_id = %s AND b.deleted_at IS NULL
                GROUP BY b.mitglied_id, m.vorname, m.nachname
                ORDER BY saldo DESC, lower(m.nachname)
                """,
                (deckel_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def saldo_for_mitglied(self, deckel_id: int, mitglied_id: int) -> Decimal:
        with self.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(SUM(betrag), 0) AS saldo FROM clubdeckel_buchung "
                "WHERE deckel_id = %s AND mitglied_id = %s AND deleted_at IS NULL",
                (deckel_id, mitglied_id),
            )
            return cur.fetchone()['saldo']

    # ------------------------------------------------- Strichliste am Termin
    def konsum_fuer_termin(self, deckel_id: int, mitglied_id: int,
                           termin_id: Optional[int]) -> dict:
        """Eigener Konsum BEI DIESEM TERMIN — für die Strichliste je Artikel
        (Menge) und die Deckel-Kachel am Tresen (verbrauchte Summe, positiv).

        Löst das frühere 24-Stunden-Fenster ab (#167): Der Deckel eines Abends
        ist das, was beim Training oder Spiel zusammenkam, nicht was zufällig in
        die letzten 24 Stunden fiel — ein Zeitfenster schnitt lange Abende
        auseinander und zog den Vortag mit hinein. Ohne Termin gibt es folglich
        auch keine Strichliste.

        Liefert {'summe': Decimal, 'anzahl': {artikel_id: int}}.
        """
        if termin_id is None:
            return {'summe': Decimal('0'), 'anzahl': {}}
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT artikel_id,
                       COALESCE(SUM(menge), 0) AS anzahl,
                       COALESCE(SUM(-betrag), 0) AS summe
                FROM clubdeckel_buchung
                WHERE deckel_id = %s AND mitglied_id = %s AND typ = 'konsum'
                  AND deleted_at IS NULL AND termin_id = %s
                GROUP BY artikel_id
                """,
                (deckel_id, mitglied_id, termin_id),
            )
            rows = cur.fetchall()
        anzahl: dict[int, int] = {}
        summe = Decimal('0')
        for r in rows:
            if r['artikel_id'] is not None:
                anzahl[r['artikel_id']] = int(r['anzahl'])
            summe += r['summe']
        return {'summe': summe, 'anzahl': anzahl}

    def letzte_konsum_id(self, deckel_id: int, mitglied_id: int, artikel_id: int,
                         von: Optional[str] = None, bis: Optional[str] = None,
                         termin_id: Optional[int] = None) -> Optional[int]:
        """id der jüngsten aktiven Konsum-Buchung dieses Mitglieds für diesen
        Artikel (für „letzten Strich zurücknehmen").

        von/bis/termin_id grenzen auf den gerade angezeigten Ausschnitt ein
        (#167): Das „−" in einer Matrix-Zelle muss genau den Strich treffen, den
        die Zelle zählt — sonst nähme man beim Nachbuchen für ein altes Spiel
        versehentlich den Strich von heute Abend zurück."""
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM clubdeckel_buchung
                WHERE deckel_id = %(did)s AND mitglied_id = %(mid)s
                  AND artikel_id = %(aid)s
                  AND typ = 'konsum' AND deleted_at IS NULL
                  AND (%(tid)s::int IS NULL OR termin_id = %(tid)s)
                  AND (%(tid)s::int IS NOT NULL
                       OR ((%(von)s::timestamptz IS NULL
                            OR created_at >= %(von)s::timestamptz)
                       AND (%(bis)s::timestamptz IS NULL
                            OR created_at < %(bis)s::timestamptz)))
                ORDER BY created_at DESC, id DESC LIMIT 1
                """,
                {"did": deckel_id, "mid": mitglied_id, "aid": artikel_id,
                 "von": von, "bis": bis, "tid": termin_id},
            )
            row = cur.fetchone()
            return row['id'] if row else None
