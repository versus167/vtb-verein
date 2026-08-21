"""
Datenmodelle für die Übungsleiter-Stundenerfassung.

- ULAbrechnung: Header einer Abrechnung (1 je ÜL + Abteilung + freier Zeitraum),
  gesteuert über einen Status-Workflow entwurf → eingereicht → bestaetigt/abgelehnt.
- ULStunde:     Einzeltermin (Datum + geleistete Stunden) zu einer Abrechnung.
- ULSatz:       konfigurierbare Vergütungsvereinbarung, aufgelöst nach
                ÜL-individuell → Abteilung+Lizenz → vereinsweit+Lizenz.

Nicht jeder ÜL wird nach Stunden bezahlt (#84): Die `verguetungsart` der Vereinbarung
entscheidet, wie aus den erfassten Stunden ein Betrag wird — oder ob überhaupt einer
entsteht. Die Erfassung selbst ist für alle Arten identisch; der Stundennachweis bleibt
also auch dort vollständig, wo die Auszahlung außerhalb der App läuft.

Satzwert *und* Art werden beim Einreichen in ULAbrechnung eingefroren (Snapshot),
damit spätere Änderungen an der Vereinbarung bestätigte Abrechnungen nicht verändern.
"""
from dataclasses import dataclass
from typing import Optional


# Status-Workflow der Abrechnung
STATUS_ENTWURF = 'entwurf'
STATUS_EINGEREICHT = 'eingereicht'
STATUS_BESTAETIGT = 'bestaetigt'
STATUS_ABGELEHNT = 'abgelehnt'

# Lizenz-Klassifikation (steuert Satz-Auflösung + Beleg).
# Am ULSatz darf sie None sein = „gilt für beide"; an der Abrechnung ist sie immer gesetzt.
LIZENZ_MIT = 'mit_lizenz'
LIZENZ_OHNE = 'ohne_lizenz'
LIZENZ_KLASSIFIKATIONEN = (LIZENZ_MIT, LIZENZ_OHNE)

# Vergütungsart der Vereinbarung – bestimmt die Betragsformel (#84).
#   stundensatz     Betrag = erfasste Stunden × Satz (€/h)          [Default, Altbestand]
#   monatspauschale Betrag = Satz (€/Monat) × noch nicht vergütete Monate im Zeitraum
#   ohne_verguetung kein Betrag; reine Aufzeichnung, kein Fibu-Export
VERGUETUNG_STUNDENSATZ = 'stundensatz'
VERGUETUNG_MONATSPAUSCHALE = 'monatspauschale'
VERGUETUNG_OHNE = 'ohne_verguetung'
VERGUETUNGSARTEN = (VERGUETUNG_STUNDENSATZ, VERGUETUNG_MONATSPAUSCHALE, VERGUETUNG_OHNE)

# Arten, aus denen eine Auszahlung (und damit ein Fibu-Export) entsteht.
VERGUETUNGSARTEN_MIT_BETRAG = (VERGUETUNG_STUNDENSATZ, VERGUETUNG_MONATSPAUSCHALE)


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
    verguetungsart: str = VERGUETUNG_STUNDENSATZ   # Snapshot beim Einreichen
    # Snapshot beim Einreichen; Einheit hängt an verguetungsart (€/h bzw. €/Monat).
    verguetung_pro_stunde: Optional[float] = None
    # Bei 'monatspauschale': Anzahl tatsächlich vergüteter Monate, beim Einreichen
    # eingefroren. Weniger als die Monate im Zeitraum, wenn ein Monat schon in einer
    # früheren Abrechnung vergütet wurde – jeder Kalendermonat zählt nur einmal.
    verguetung_monate: Optional[int] = None
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
    """Konfigurierbare Vergütungsvereinbarung.

    mitglied_id gesetzt  → individuelle Vereinbarung (gewinnt vor Abteilung).
    abteilung_id gesetzt → gilt für diese Abteilung; NULL = vereinsweiter Default.
    lizenz_klassifikation NULL → gilt für beide Lizenzlagen; ein exakter Treffer
    gewinnt. Ohne dieses „beide" fiele eine individuelle Vereinbarung still auf den
    vereinsweiten Satz zurück, sobald die Trainerlizenz ausläuft.
    """
    id: Optional[int] = None
    mitglied_id: Optional[int] = None
    abteilung_id: Optional[int] = None
    lizenz_klassifikation: Optional[str] = None
    verguetungsart: str = VERGUETUNG_STUNDENSATZ
    satz: float = 0.0                              # €/h bzw. €/Monat, je nach Art
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
