"""Datenmodell für Spielstätten (Schema v80, Ticket #95).

Stammdaten der Plätze und Hallen. Grundlage für den DFBnet-Spielplan-Import
(Zuordnung über `dfbnet_nr`) und den späteren Platzbelegungsplan.

`platzhalter` markiert die beiden Sonderzeilen, die kein realer Ort sind, sondern
Antworten auf das Pflichtfeld am Termin: 'auswaerts' („Kein Vereinsgelände") und
'unbekannt' („Nicht erfasst", nur Altbestand). Sie sind nicht bearbeitbar und
nicht löschbar.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class Spielstaette:
    id: Optional[int] = None
    name: str = ""
    dfbnet_nr: Optional[str] = None      # DFBnet-Spielstätten-Nr., nur für den Import
    strasse: Optional[str] = None
    plz: Optional[str] = None
    ort: Optional[str] = None
    # Eigenes Gelände? Nur solche Plätze zählen in den Belegungsplan.
    ist_eigen: bool = False
    # Kapazität aus dem DFBnet-Feld „Max. parallele Spiele". Überschneidungen
    # werden nie blockiert, sondern gegen diese Zahl angezeigt.
    parallel_moeglich: int = 1
    platzhalter: Optional[str] = None    # 'auswaerts' | 'unbekannt' | None
    # Belag (Rasen, Kunstrasen, Halle …) – interessiert die Spieler wegen der
    # Schuhwahl. Freitext: Der DFBnet-Export bringt eigene Bezeichnungen mit,
    # und Hallenböden lassen sich nicht sinnvoll vorab aufzählen.
    untergrund: Optional[str] = None
    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None
