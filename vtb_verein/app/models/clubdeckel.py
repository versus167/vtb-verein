"""Datenmodelle für die Teamkasse/Clubdeckel (#98, Schema v75).

- Clubdeckel:        mannschaftsinterne Strichliste, genau eine je Mannschaft.
                     Stammdaten: Monatsbeitrag (Pauschale), Zahlungsempfänger
                     (Mitglied) und dessen Zahlwege (IBAN/WERO/PayPal).
- ClubdeckelGruppe:  Artikel-Gruppe („Getränke"/„Essen") mit VERKÄUFER — Team
                     (verkaeufer_mitglied_id NULL) oder ein Mitglied.
- ClubdeckelArtikel: Katalog-Eintrag mit Preis; Pflege durch Warte.
- ClubdeckelBuchung: Ledger-Zeile. Saldo je Mitglied = SUM(betrag) über aktive
                     Zeilen, Team-Saldo = −Σ Mitgliedssalden. Typen:
                     konsum (Kauf, negativ; bei Mitglieds-Verkäufer mit
                     'verkauf'-Gegenzeile als Nullsummen-Paar via paar_ref),
                     einkauf (Team kauft vom Mitglied, positiv),
                     zahlung (Mitglied→Mitglied, Nullsummen-Paar via paar_ref),
                     beitrag (Monatspauschale, negativ, beitrag_monat 'YYYY-MM'),
                     event (einmalige Umlage, negativ, event_id).
- ClubdeckelEvent:   einmalige Sammlung auf den ganzen Kader (#181).

Wart-ACL (clubdeckel_berechtigung), Beitragsbefreiungen und die generellen
Sammlungs-Opt-outs haben bewusst kein eigenes Modell — sie werden nur als Listen
mit Namen angezeigt (dict im Repo).
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass
class Clubdeckel:
    id: int
    mannschaft_id: int
    name: str
    aktiv: int
    beitrag: Optional[Decimal]
    beitrag_ab: Optional[str]              # 'YYYY-MM', ab wann der Beitrag läuft
    zahlungsempfaenger_mitglied_id: Optional[int]
    zahlweg_iban: Optional[str]
    zahlweg_wero: Optional[str]
    zahlweg_paypal: Optional[str]
    version: int
    created_at: str
    created_by: str
    updated_at: str
    updated_by: str
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None
    # Nur für die Anzeige (per JOIN aufgelöst), keine Tabellenspalten:
    mannschaft_name: Optional[str] = None
    zahlungsempfaenger_name: Optional[str] = None


@dataclass
class ClubdeckelGruppe:
    """Ein STAND des Sortiments (#167, v100).

    Eine Gruppe ist nicht dauerhaft, sondern gilt ab einem Spieltag. Ändert der
    Wart Preis, Bezeichnung oder Verkäufer, entsteht eine neue Generation samt
    Artikelkopien; ältere Termine behalten ihre. `stamm_id` bündelt die
    Generationen (die erste zeigt auf sich selbst), `gilt_ab_termin_id` sagt, ab
    wann eine gilt — NULL heißt „von Anfang an".
    """
    id: int
    deckel_id: int
    name: str
    verkaeufer_mitglied_id: Optional[int]  # None = das Team verkauft
    aktiv: int
    sortierung: int
    stamm_id: Optional[int]
    gilt_ab_termin_id: Optional[int]
    version: int
    created_at: str
    created_by: str
    updated_at: str
    updated_by: str
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None
    # Nur für die Anzeige:
    verkaeufer_name: Optional[str] = None
    gilt_ab_label: Optional[str] = None


@dataclass
class ClubdeckelArtikel:
    id: int
    deckel_id: int
    gruppe_id: Optional[int]
    name: str
    preis: Decimal
    aktiv: int
    sortierung: int
    # 1 = nicht am Tresen, nur der Wart bucht ihn (#167, z. B. „Wäsche")
    nur_wart: int
    version: int
    created_at: str
    created_by: str
    updated_at: str
    updated_by: str
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None


@dataclass
class ClubdeckelBuchung:
    id: int
    deckel_id: int
    mitglied_id: int
    artikel_id: Optional[int]
    # 'konsum' | 'verkauf' | 'kauf' | 'einkauf' | 'zahlung' | 'beitrag' | 'event'
    typ: str
    menge: Optional[int]
    betrag: Decimal               # vorzeichenbehaftet
    paar_ref: Optional[str]       # verknüpft Nullsummen-Paare (zahlung, Mitglieds-Verkauf)
    beitrag_monat: Optional[str]  # 'YYYY-MM', nur typ='beitrag'
    notiz: Optional[str]
    artikel_name: Optional[str]   # Snapshot der Bezeichnung zum Buchungszeitpunkt
    gegen_name: Optional[str]     # Snapshot des Gegenkontos ('Team' | Mitgliedsname)
    termin_id: Optional[int]      # Termin, bei dem gebucht wurde (#167); None = keiner
    event_id: Optional[int]       # Sammlung, aus der die Zeile stammt (#181)
    version: int
    created_at: str
    created_by: str
    updated_at: str
    updated_by: str
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None
    # Nur für die Anzeige (per JOIN aufgelöst), keine Tabellenspalten:
    mitglied_name: Optional[str] = None
    termin_label: Optional[str] = None   # z. B. „Spiel 16.08. 15:00"


@dataclass
class ClubdeckelEvent:
    """Eine einmalige Sammlung auf den ganzen Kader (#181, v114).

    „60. Geburtstag Klaus: 5 € von allen" — im Gegensatz zum Monatsbeitrag ohne
    Wiederholung und immer von Hand ausgelöst. `fuer_mitglied_id` ist der, für
    den gesammelt wird; er zahlt sein eigenes Geschenk nicht mit. Wer generell
    nicht mitmacht, steht in clubdeckel_event_opt_out (am Deckel, nicht am
    Event). Gebucht wird gegen den Club: je Teilnehmer eine Buchung typ='event'
    über −betrag.
    """
    id: int
    deckel_id: int
    name: str
    betrag: Decimal
    fuer_mitglied_id: Optional[int]
    version: int
    created_at: str
    created_by: str
    updated_at: str
    updated_by: str
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None
    # Nur für die Anzeige (per JOIN/Aggregat aufgelöst), keine Tabellenspalten:
    fuer_name: Optional[str] = None
    gebucht_anzahl: int = 0            # aktive Buchungen dieser Sammlung
    gebucht_summe: Decimal = Decimal('0')   # eingesammelt (positiv)
    gebucht_am: Optional[str] = None   # wann zuletzt gebucht wurde
