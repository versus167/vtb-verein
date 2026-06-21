"""
Datenmodelle für den Fibu-Export (Format hmd FBASC) der Sollstellungen.

- FibuExport:        Header eines Export-Laufs (unveränderlich, rekonstruierbar).
- FibuEinstellungen: globale Konten-Konfiguration (Single-Row).
- FibuExportPosition: format-neutrale Buchungszeile (Forderung oder Gegenbuchung),
  aus der der FBASC-Formatter die fbasc.hia-Zeile baut.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class FibuExport:
    """Header eines Fibu-Export-Laufs."""
    id: Optional[int] = None
    exportiert_am: Optional[str] = None
    exportiert_von: Optional[str] = None
    dateiname: str = ""
    format: str = "fbasc"
    anzahl_positionen: int = 0
    summe_cent: int = 0
    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None


@dataclass
class FibuEinstellungen:
    """Globale Konfiguration für den Fibu-Export (genau eine Zeile, id=1)."""
    id: int = 1
    debitor_konto_basis: Optional[int] = None      # Debitor-Konto = Basis + mitgliedsnummer
    default_gegenkonto: Optional[str] = None        # Fallback-Erlöskonto
    default_steuerschluessel: Optional[str] = None  # Fallback-Steuerschlüssel (i.d.R. leer)
    verein_kostenstelle: int = 12                   # Kostenstelle für Vereinsbeiträge (ohne Abteilung)
    default_kostentraeger: int = 1                  # Kostenträger-Default
    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None


@dataclass
class FibuExportPosition:
    """Eine Buchungszeile für den FBASC-Export – Forderung (Soll) oder Gegenbuchung (Haben).

    Die Datumsfelder sind ISO (YYYY-MM-DD); der Formatter wandelt sie nach TT.MM.JJJJ.
    Beträge sind immer positiv – das Vorzeichen steckt im S/H-Kennzeichen.
    """
    # Herkunft / Anzeige
    quelle_typ: str = ""               # 'beitrag' | 'gebuehr'
    quelle_id: int = 0
    art: str = "forderung"             # 'forderung' | 'gegenbuchung'
    mitglied_id: int = 0
    mitglied_name: str = ""            # "Nachname, Vorname" (Anzeige)
    bezeichnung: str = ""              # Regel-/Gebührname + Zeitraum (Anzeige)
    # FBASC-Buchungsfelder
    konto: Optional[int] = None        # Feld 00 Debitor/Personenkonto
    gegenkonto: Optional[str] = None   # Feld 01 Erlöskonto (Sachkonto)
    betrag: float = 0.0                # Feld 02 (immer positiv)
    soll_haben: str = "S"              # Feld 03 'S' | 'H'
    belegnummer: str = ""              # Feld 04
    steuerschluessel: Optional[str] = None  # Feld 06 (i.d.R. leer = Automatikkonto)
    kostenstelle: Optional[int] = None     # Feld 07
    kostentraeger: Optional[int] = None    # Feld 08
    belegdatum: Optional[str] = None       # Feld 10 (ISO)
    faelligkeitsdatum: Optional[str] = None  # Feld 11 (ISO)
    buchungstext: str = ""             # Feld 12
    lastschrifteinzug: Optional[int] = None  # Feld 36 (1 = Lastschrift)
    # Debitor-Stammdaten
    suchname: str = ""                 # Feld 20 (Adresscode)
    nachname: str = ""                 # Feld 22
    vorname: Optional[str] = None      # Feld 43
    strasse: Optional[str] = None      # Feld 24
    plz: Optional[str] = None          # Feld 25
    ort: Optional[str] = None          # Feld 26
    land: Optional[str] = None         # Feld 27
    iban: Optional[str] = None         # Feld 40
    bic: Optional[str] = None          # Feld 41
    mandatsref: Optional[str] = None   # Feld 47
    mandatsdatum: Optional[str] = None  # Feld 48 (ISO)
