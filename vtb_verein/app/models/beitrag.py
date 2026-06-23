"""
Datenmodelle für Beitragsregeln und Sollstellungen.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Beitragsregel:
    """Regel für die automatische Beitragsberechnung."""
    id: Optional[int] = None
    name: str = ""
    abteilung_id: Optional[int] = None
    abteilung_name: Optional[str] = None         # per JOIN befüllt
    betrag_pro_monat: float = 0.0
    einzug_turnus: str = "quartal"               # quartal | monat | halbjahr | jahr
    gueltig_ab: str = ""
    gueltig_bis: Optional[str] = None
    bedingung_raw: Optional[str] = None
    bedingung_abteilung_status: Optional[str] = None  # kommagetrennt, None = alle
    bedingung_funktionen: list[str] = field(default_factory=list)  # nur Mitglieder mit (mind.) einer dieser Funktionen
    # Index-gleich zu bedingung_funktionen: je Einschluss ein optionaler Abteilungs-Bezug
    # (None = vereinsweit). Erlaubt mehrere, je eigen begrenzte Einschlüsse pro Regel.
    bedingung_abteilung_ids: list[Optional[int]] = field(default_factory=list)
    bedingung_funktion_abteilung_id: Optional[int] = None  # DEPRECATED (vor v42): ein gemeinsamer Bezug; ersetzt durch bedingung_abteilung_ids
    ausnahme_funktionen: list[str] = field(default_factory=list)   # Mitglieder mit (irgend)einer dieser Funktionen ausschließen
    # Index-gleich zu ausnahme_funktionen: je Ausnahme ein optionaler Abteilungs-Bezug
    # (None = vereinsweit). Erlaubt mehrere, je eigen begrenzte Ausnahmen pro Regel.
    ausnahme_abteilung_ids: list[Optional[int]] = field(default_factory=list)
    ausnahme_funktion_abteilung_id: Optional[int] = None   # DEPRECATED (vor v41): ein gemeinsamer Bezug; ersetzt durch ausnahme_abteilung_ids
    bedingung_alter_min: Optional[int] = None              # Mindestalter (Jahre), None = keine Untergrenze
    bedingung_alter_max: Optional[int] = None              # Höchstalter (Jahre), None = keine Obergrenze
    zahler_typ: str = "mitglied"                 # mitglied | abteilung
    gegenkonto: Optional[str] = None             # Fibu-Erlöskonto (FBASC Feld 01)
    steuerschluessel: Optional[str] = None       # Fibu-Steuerschlüssel (FBASC Feld 06), i.d.R. leer
    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None

    @property
    def betrag_pro_einzug(self) -> float:
        """Berechneter Einzugsbetrag je Turnus."""
        faktor = {'monat': 1, 'quartal': 3, 'halbjahr': 6, 'jahr': 12}
        return self.betrag_pro_monat * faktor.get(self.einzug_turnus, 1)

    @property
    def bedingung_status_liste(self) -> Optional[list[str]]:
        """Bedingung als Liste, None = alle Status."""
        if not self.bedingung_abteilung_status:
            return None
        return [s.strip() for s in self.bedingung_abteilung_status.split(',') if s.strip()]


@dataclass
class BeitragEinstellungen:
    """Globale Einstellungen der Beitragsabrechnung (Single-Row, id=1)."""
    id: int = 1
    # Anzahl Quartale VOR dem aktuellen, die eine Abrechnung mitnimmt (0 = nur
    # aktuelles Quartal). Sicherheitsnetz für verpasste Läufe; im Dauerbetrieb i.d.R. 1.
    quartale_rueckschau: int = 1
    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None


@dataclass
class BeitragSollstellung:
    """Konkrete Beitragsforderung für ein Mitglied."""
    id: Optional[int] = None
    mitglied_id: int = 0
    beitragsregel_id: int = 0
    zeitraum: str = ""                           # z.B. "2026-Q4", "2026-01"
    betrag_soll: float = 0.0
    faelligkeitsdatum: Optional[str] = None
    status: str = "offen"                        # offen | bezahlt | storniert
    bezahlt_am: Optional[str] = None
    kassenbuchung_id: Optional[int] = None
    exportiert_in_export_id: Optional[int] = None          # Forderung in Fibu-Lauf exportiert
    storno_exportiert_in_export_id: Optional[int] = None   # Gegenbuchung exportiert
    # Per JOIN befüllt
    mitglied_vorname: Optional[str] = None
    mitglied_nachname: Optional[str] = None
    mitglied_iban: Optional[str] = None
    mitglied_kontoinhaber: Optional[str] = None
    beitragsregel_name: Optional[str] = None
    zahler_typ: Optional[str] = None
    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None
