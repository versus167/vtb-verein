"""
Datenmodelle für die Übungsleiter-Stundenerfassung.

- ULAbrechnung: Header einer Abrechnung (1 je ÜL + Abteilung + freier Zeitraum),
  gesteuert über einen Status-Workflow entwurf → eingereicht → bestaetigt/abgelehnt.
- ULStunde:     Einzeltermin (Datum + geleistete Stunden) zu einer Abrechnung.
- ULSatz:       konfigurierbarer Vergütungssatz (€/h), aufgelöst nach
                ÜL-individuell → Abteilung+Lizenz → vereinsweit+Lizenz.

Der aufgelöste Satz wird beim Einreichen in ULAbrechnung.verguetung_pro_stunde
eingefroren (Snapshot), damit spätere Satzänderungen bestätigte Abrechnungen
nicht verändern.
"""
from dataclasses import dataclass
from typing import Optional


# Status-Workflow der Abrechnung
STATUS_ENTWURF = 'entwurf'
STATUS_EINGEREICHT = 'eingereicht'
STATUS_BESTAETIGT = 'bestaetigt'
STATUS_ABGELEHNT = 'abgelehnt'

# Lizenz-Klassifikation (steuert Satz-Auflösung + Beleg)
LIZENZ_MIT = 'mit_lizenz'
LIZENZ_OHNE = 'ohne_lizenz'
LIZENZ_KLASSIFIKATIONEN = (LIZENZ_MIT, LIZENZ_OHNE)


@dataclass
class ULAbrechnung:
    """Header einer Übungsleiter-Abrechnung."""
    id: Optional[int] = None
    mitglied_id: int = 0
    abteilung_id: int = 0
    zeitraum_von: str = ""                         # ISO-Datum (inkl.)
    zeitraum_bis: str = ""                         # ISO-Datum (inkl.) = Sperr-Wasserzeichen
    status: str = STATUS_ENTWURF                   # entwurf | eingereicht | bestaetigt | abgelehnt
    lizenz_klassifikation: str = LIZENZ_OHNE       # mit_lizenz | ohne_lizenz
    foerder_klassifikation: Optional[str] = None   # z.B. LSBS, Spofoe_3_3 (nur Beleg)
    verguetung_pro_stunde: Optional[float] = None  # Snapshot beim Einreichen
    # Lizenz-Snapshot beim Einreichen (Beleg friert mit ein – sonst rückwirkend änderbar)
    trainerlizenz_nr: Optional[str] = None
    qualifikation: Optional[str] = None
    eingereicht_am: Optional[str] = None
    eingereicht_von: Optional[str] = None
    bestaetigt_am: Optional[str] = None
    bestaetigt_von: Optional[str] = None
    abgelehnt_grund: Optional[str] = None
    exportiert_in_export_id: Optional[int] = None          # Forderung in Fibu-Lauf exportiert
    storno_exportiert_in_export_id: Optional[int] = None   # Gegenbuchung exportiert
    # per JOIN befüllt (Anzeige / Beleg)
    mitglied_vorname: Optional[str] = None
    mitglied_nachname: Optional[str] = None
    mitgliedsnummer: Optional[int] = None
    mitglied_iban: Optional[str] = None
    mitglied_kontoinhaber: Optional[str] = None
    abteilung_name: Optional[str] = None
    abteilung_kuerzel: Optional[str] = None
    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None


@dataclass
class ULStunde:
    """Einzeltermin einer Abrechnung (Datum + geleistete Stunden)."""
    id: Optional[int] = None
    abrechnung_id: int = 0
    datum: str = ""                                # ISO-Datum
    stunden: float = 0.0
    wochentag: Optional[int] = None                # 1=Mo … 7=So (für Beleg-Gruppierung)
    angebot: Optional[str] = None
    bemerkung: Optional[str] = None
    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None


@dataclass
class ULSatz:
    """Konfigurierbarer Vergütungssatz (€/h).

    mitglied_id gesetzt  → individuelle Vereinbarung (gewinnt vor Abteilung).
    abteilung_id gesetzt → gilt für diese Abteilung; NULL = vereinsweiter Default.
    """
    id: Optional[int] = None
    mitglied_id: Optional[int] = None
    abteilung_id: Optional[int] = None
    lizenz_klassifikation: str = LIZENZ_OHNE
    satz: float = 0.0
    gueltig_ab: Optional[str] = None
    # per JOIN befüllt (Anzeige)
    mitglied_vorname: Optional[str] = None
    mitglied_nachname: Optional[str] = None
    abteilung_name: Optional[str] = None
    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None
