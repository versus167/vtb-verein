"""
Datenmodelle für das Einreichen und Freigeben von Rechnungen.

- RechnungKategorie: kurze Auswahlliste (Stammdaten) mit dem Aufwandskonto für die Fibu.
- Rechnung:          Header mit Status-Workflow entwurf → eingereicht → freigegeben/abgelehnt.
- RechnungAnhang:    Beleg-Datei (Blatt ohne version/History, Datei via AnhangService).
- RechnungExport:    Header eines Export-Laufs (Delta: nur noch nicht exportierte Rechnungen).

Der Einreicher pflegt nur Beleg + Kategorie; Betrag/Rechnungsdatum/Empfänger sind optional
und können von der Geschäftsstelle nachgetragen werden ("den Rest macht die Fibu").
"""
from dataclasses import dataclass
from typing import Optional


# Status-Workflow der Rechnung
STATUS_ENTWURF = 'entwurf'
STATUS_EINGEREICHT = 'eingereicht'
STATUS_FREIGEGEBEN = 'freigegeben'
STATUS_ABGELEHNT = 'abgelehnt'

STATUS_ALLE = (STATUS_ENTWURF, STATUS_EINGEREICHT, STATUS_FREIGEGEBEN, STATUS_ABGELEHNT)

# Empfängertyp (optional, für die spätere Kreditor-Buchung)
EMPFAENGER_MITGLIED = 'mitglied'
EMPFAENGER_EXTERN = 'extern'
EMPFAENGER_TYPEN = (EMPFAENGER_MITGLIED, EMPFAENGER_EXTERN)


@dataclass
class RechnungKategorie:
    """Auswahlliste für die Zuordnung einer Rechnung (vereinsweite Stammdaten)."""
    id: Optional[int] = None
    name: str = ""
    beschreibung: Optional[str] = None
    sachkonto: Optional[str] = None        # Aufwandskonto (Andockpunkt für den FBASC-Export)
    kostenstelle: Optional[int] = None
    kostentraeger: Optional[int] = None
    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None


@dataclass
class Rechnung:
    """Header einer eingereichten Rechnung."""
    id: Optional[int] = None
    abteilung_id: Optional[int] = None      # None = Vereinsrechnung (Geschäftsstelle gibt frei)
    kategorie_id: int = 0
    ersteller_user_id: int = 0
    beschreibung: Optional[str] = None
    status: str = STATUS_ENTWURF
    # Optionale Angaben – Pflicht ist nur Beleg + Kategorie.
    betrag_cent: Optional[int] = None
    rechnungsdatum: Optional[str] = None    # ISO-Datum
    rechnungsnummer: Optional[str] = None   # Nummer des Ausstellers
    empfaenger_typ: Optional[str] = None    # 'mitglied' | 'extern'
    empfaenger_mitglied_id: Optional[int] = None
    empfaenger_name: Optional[str] = None
    empfaenger_iban: Optional[str] = None
    # Workflow-Stempel
    eingereicht_am: Optional[str] = None
    eingereicht_von: Optional[str] = None
    freigegeben_am: Optional[str] = None
    freigegeben_von: Optional[str] = None
    abgelehnt_grund: Optional[str] = None
    exportiert_in_export_id: Optional[int] = None
    # per JOIN befüllt (Anzeige)
    kategorie_name: Optional[str] = None
    kategorie_sachkonto: Optional[str] = None
    abteilung_name: Optional[str] = None
    abteilung_kostenstelle: Optional[int] = None
    ersteller_name: Optional[str] = None
    empfaenger_mitglied_name: Optional[str] = None
    anhang_count: int = 0
    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None

    @property
    def ist_exportiert(self) -> bool:
        return self.exportiert_in_export_id is not None

    @property
    def betrag_euro(self) -> Optional[float]:
        return None if self.betrag_cent is None else self.betrag_cent / 100


@dataclass
class RechnungAnhang:
    """Beleg zu einer Rechnung. Blatt ohne version/History – die Datei liegt im Upload-Pfad."""
    id: Optional[int] = None
    rechnung_id: int = 0
    original_name: str = ""
    stored_name: str = ""
    mime_type: str = ""
    dateigroesse: int = 0
    hochgeladen_von: Optional[str] = None
    hochgeladen_am: Optional[str] = None
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None


@dataclass
class RechnungExport:
    """Header eines Rechnungs-Export-Laufs (Zip mit Belegen + Übersicht)."""
    id: Optional[int] = None
    exportiert_am: Optional[str] = None
    exportiert_von: Optional[str] = None
    dateiname: str = ""
    format: str = "zip"
    anzahl_rechnungen: int = 0
    summe_cent: Optional[int] = None
    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None
