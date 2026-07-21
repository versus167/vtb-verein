"""Ledger des Teamtresors (#98): clubdeckel_buchung.

Eine Zeile pro Vorgang und Mitglied; Saldo je Mitglied = SUM(betrag) über aktive
Zeilen, Team-Saldo = −Σ Mitgliedssalden. Konventionen:

- konsum:   betrag = -(menge * artikel.preis) — Preis-Snapshot. Verkauft die
            Artikel-GRUPPE über ein Mitglied (verkaeufer_mitglied_id), entsteht
            zusätzlich die Gegenzeile typ 'verkauf' (+betrag) beim Verkäufer,
            verknüpft über paar_ref (Nullsumme, Team unberührt).
- einkauf:  Team kauft vom Mitglied (z. B. Kasten Bier geliefert) → +betrag.
- zahlung:  Mitglied zahlt an Mitglied (bar/PayPal/…) → PAAR: +betrag beim
            Zahler (Schuld sinkt), −betrag beim Empfänger, gemeinsame paar_ref.
- beitrag:  Monatspauschale → −betrag, beitrag_monat 'YYYY-MM'. Automatisch
            nachgebucht über buche_faellige_beitraege; ein Monat gilt als
            erledigt, sobald IRGENDEINE Beitragszeile existiert (auch storniert
            — Storno heißt „erlassen", nicht „bitte nochmal").

Storno einer Paar-Zeile löscht immer das ganze Paar.
"""
import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from app.models.clubdeckel import ClubdeckelBuchung
from app.db.base_repository import BaseRepository

_COLS = ("id, deckel_id, mitglied_id, artikel_id, typ, menge, betrag, "
         "paar_ref, beitrag_monat, notiz, artikel_name, gegen_name, version, "
         "created_at, created_by, updated_at, updated_by, deleted_at, deleted_by")
_B_COLS = ", ".join("b." + c.strip() for c in _COLS.split(","))


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
                        mit_storniert: bool = False) -> list[ClubdeckelBuchung]:
        """Buchungen, neueste zuerst — optional nur die eines Mitglieds.
        mit_storniert=True nimmt auch soft-gelöschte Zeilen mit (deleted_at
        gesetzt); die History kann sie dann optional einblenden (#127)."""
        filt = "" if mit_storniert else " AND b.deleted_at IS NULL"
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_B_COLS},
                       m.vorname || ' ' || m.nachname AS mitglied_name
                FROM clubdeckel_buchung b
                JOIN mitglied m ON m.id = b.mitglied_id
                WHERE b.deckel_id = %(did)s{filt}
                  AND (%(mid)s::int IS NULL OR b.mitglied_id = %(mid)s)
                ORDER BY b.created_at DESC, b.id DESC
                LIMIT %(lim)s
                """,
                {"did": deckel_id, "mid": mitglied_id, "lim": limit},
            )
            return [_map(r) for r in cur.fetchall()]

    # ---------------------------------------------------------------- buchen
    def create_konsum(self, deckel_id: int, mitglied_id: int, artikel_id: int,
                      artikel_name: str, menge: int, preis: Decimal,
                      verkaeufer_mitglied_id: Optional[int],
                      created_by: str) -> ClubdeckelBuchung:
        """Kauf eines Artikels durch ein Mitglied. Verkauft ein MITGLIED
        (Gruppen-Verkäufer), wird die 'verkauf'-Gegenzeile mitgebucht."""
        betrag = preis * menge
        paar_ref = uuid.uuid4().hex if verkaeufer_mitglied_id else None
        with self.cursor() as cur:
            # Käufer-Zeile: Bezeichnung + Verkäufer ('Team', sonst Mitglied) einfrieren.
            cur.execute(
                "INSERT INTO clubdeckel_buchung "
                "(deckel_id, mitglied_id, artikel_id, typ, menge, betrag, paar_ref, "
                " artikel_name, gegen_name, created_by, updated_by) "
                "VALUES (%s,%s,%s,'konsum',%s,%s,%s,%s,"
                " COALESCE((SELECT vorname||' '||nachname FROM mitglied WHERE id=%s),"
                "          'Team'), %s,%s) RETURNING id",
                (deckel_id, mitglied_id, artikel_id, menge, -betrag, paar_ref,
                 artikel_name, verkaeufer_mitglied_id, created_by, created_by),
            )
            new_id = cur.fetchone()['id']
            if verkaeufer_mitglied_id:
                # Verkäufer-Gegenzeile: Gegenkonto = der Käufer.
                cur.execute(
                    "INSERT INTO clubdeckel_buchung "
                    "(deckel_id, mitglied_id, artikel_id, typ, menge, betrag, "
                    " paar_ref, artikel_name, gegen_name, created_by, updated_by) "
                    "VALUES (%s,%s,%s,'verkauf',%s,%s,%s,%s,"
                    " (SELECT vorname||' '||nachname FROM mitglied WHERE id=%s),"
                    " %s,%s)",
                    (deckel_id, verkaeufer_mitglied_id, artikel_id, menge, betrag,
                     paar_ref, artikel_name, mitglied_id, created_by, created_by),
                )
        return self.get(new_id)

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

    # ------------------------------------------------------ 24h-Strichliste
    def konsum_24h(self, deckel_id: int, mitglied_id: int) -> dict:
        """Eigene Konsum-Buchungen der letzten 24 Stunden — für die Strichliste
        je Artikel (Menge) und die „24h-Deckel"-Kachel (verbrauchte Summe,
        positiv). Liefert {'summe': Decimal, 'anzahl': {artikel_id: int}}."""
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT artikel_id,
                       COALESCE(SUM(menge), 0) AS anzahl,
                       COALESCE(SUM(-betrag), 0) AS summe
                FROM clubdeckel_buchung
                WHERE deckel_id = %s AND mitglied_id = %s AND typ = 'konsum'
                  AND deleted_at IS NULL
                  AND created_at >= now() - interval '24 hours'
                GROUP BY artikel_id
                """,
                (deckel_id, mitglied_id),
            )
            rows = cur.fetchall()
        anzahl: dict[int, int] = {}
        summe = Decimal('0')
        for r in rows:
            if r['artikel_id'] is not None:
                anzahl[r['artikel_id']] = int(r['anzahl'])
            summe += r['summe']
        return {'summe': summe, 'anzahl': anzahl}

    def letzte_konsum_id(self, deckel_id: int, mitglied_id: int,
                         artikel_id: int) -> Optional[int]:
        """id der jüngsten eigenen aktiven Konsum-Buchung dieses Artikels
        (für „letzten Strich zurücknehmen")."""
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM clubdeckel_buchung
                WHERE deckel_id = %s AND mitglied_id = %s AND artikel_id = %s
                  AND typ = 'konsum' AND deleted_at IS NULL
                ORDER BY created_at DESC, id DESC LIMIT 1
                """,
                (deckel_id, mitglied_id, artikel_id),
            )
            row = cur.fetchone()
            return row['id'] if row else None
