"""Datenmodelle für den Teamtresor/Clubdeckel (#98, Schema v75).

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
                     beitrag (Monatspauschale, negativ, beitrag_monat 'YYYY-MM').

Wart-ACL (clubdeckel_berechtigung) und Beitragsbefreiungen haben bewusst kein
eigenes Modell — sie werden nur als Listen mit Namen angezeigt (dict im Repo).
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
    id: int
    deckel_id: int
    name: str
    verkaeufer_mitglied_id: Optional[int]  # None = das Team verkauft
    aktiv: int
    sortierung: int
    version: int
    created_at: str
    created_by: str
    updated_at: str
    updated_by: str
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None
    # Nur für die Anzeige:
    verkaeufer_name: Optional[str] = None


@dataclass
class ClubdeckelArtikel:
    id: int
    deckel_id: int
    gruppe_id: Optional[int]
    name: str
    preis: Decimal
    aktiv: int
    sortierung: int
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
    typ: str                      # 'konsum' | 'verkauf' | 'einkauf' | 'zahlung' | 'beitrag'
    menge: Optional[int]
    betrag: Decimal               # vorzeichenbehaftet
    paar_ref: Optional[str]       # verknüpft Nullsummen-Paare (zahlung, Mitglieds-Verkauf)
    beitrag_monat: Optional[str]  # 'YYYY-MM', nur typ='beitrag'
    notiz: Optional[str]
    artikel_name: Optional[str]   # Snapshot der Bezeichnung zum Buchungszeitpunkt
    gegen_name: Optional[str]     # Snapshot des Gegenkontos ('Team' | Mitgliedsname)
    version: int
    created_at: str
    created_by: str
    updated_at: str
    updated_by: str
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None
    # Nur für die Anzeige (per JOIN aufgelöst), keine Tabellenspalten:
    mitglied_name: Optional[str] = None
