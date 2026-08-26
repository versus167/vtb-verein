"""Datenmodell für Mannschafts-Termine (Spielbetrieb Etappe 1, #95, Schema v68).

Ein Termin (Training/Spiel/Sonstiges) gehört zu genau einer Mannschaft. Der Zugriff
wird NICHT über globale Rechte geregelt, sondern über die Kader-Zugehörigkeit
(mitglied_mannschaft): betreuer/uebungsleiter verwalten, alle aktiven
Kader-Mitglieder lesen. Nur das übergreifende Verwalten hängt an termine.verwalten.

Zeiten sind lokale Wandzeit als TEXT ('YYYY-MM-DDTHH:MM' bzw. 'HH:MM') — wie alle
Domänen-Daten; TIMESTAMPTZ bleibt den Audit-Zeitstempeln vorbehalten.
serie_id (Vorgriff auf Terminserien) und extern_ref (DFBnet-Spielkennung für den
späteren Spielplan-Import) sind vorbereitet, werden aber noch nicht per API gesetzt.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class Termin:
    id: int
    mannschaft_id: int
    serie_id: Optional[int]
    typ: str                          # 'training' | 'spiel' | 'sonstiges'
    beginn: str                       # 'YYYY-MM-DDTHH:MM' (lokale Wandzeit)
    ende: Optional[str]               # dito, optional
    ort: Optional[str]
    spielstaette_id: int              # Pflicht ab v80; Platzhalter s. spielstaette
    treffpunkt: Optional[str]
    treffpunkt_zeit: Optional[str]    # 'HH:MM'
    gegner: Optional[str]             # nur typ='spiel'
    heim_auswaerts: Optional[str]     # 'heim' | 'auswaerts', nur typ='spiel'
    extern_ref: Optional[str]         # DFBnet-Spielkennung (Etappe 3)
    # Zuletzt importierter Stand der Vergleichsfelder – Grundlage des
    # Drei-Wege-Abgleichs (nur der Import schreibt ihn).
    extern_stand: Optional[dict]
    status: str                       # 'geplant' | 'abgesagt'
    beschreibung: Optional[str]
    version: int
    created_at: str
    created_by: str
    updated_at: str
    updated_by: str
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None
    # Nur für die Anzeige (per JOIN aufgelöst), keine Tabellenspalte:
    mannschaft_name: Optional[str] = None
    spielstaette_name: Optional[str] = None
    # Anschrift der Spielstätte, getrennt vom Namen: Für die Übergabe an eine
    # Navi-App taugt nur die Adresse — Platzbezeichnungen wie „eins-Stadion –
    # An der Gellertstraße" oder „Sportpl. Ebersdorf Höhensonne" findet kein
    # Geocoder zuverlässig.
    spielstaette_strasse: Optional[str] = None
    spielstaette_plz: Optional[str] = None
    spielstaette_ort: Optional[str] = None
    # Belag (Rasen/Kunstrasen/…): steht am Termin, weil die Spieler danach ihre
    # Schuhe wählen – die Spielstätte selbst schaut dafür niemand nach.
    spielstaette_untergrund: Optional[str] = None


@dataclass
class TerminErinnerungEinstellungen:
    """Vorlauf der Termin-Erinnerungen (Single-Row, id=1) – #95-Nachgang, Schema v112.

    Vor einem Termin wird erinnert, wer noch keine Meldung abgegeben hat. Zwei
    Stufen mit je einem Vorlauf in Tagen; je Termin und Stufe geht die Erinnerung
    genau einmal raus.

    **Stufe 0 schaltet die einzelne Stufe ab** – wer nur einmal erinnern will,
    setzt die zweite auf 0; `aktiv=False` schaltet den ganzen Lauf ab. Welche der
    beiden Zahlen die größere ist, spielt keine Rolle: Der Lauf sortiert sie
    (s. termin_erinnerung_service.stufen).
    """
    id: int = 1

    aktiv: bool = True
    erste_stufe_tage: int = 3
    zweite_stufe_tage: int = 1

    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None
