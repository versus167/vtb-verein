"""Offene Frage des Spielplan-Imports an den Betreuer (Schema v84, #95, Etappe 4).

Entsteht dort, wo der Drei-Wege-Abgleich nicht allein entscheiden darf: Ein Feld
weicht seit dem letzten Import sowohl im DFBnet als auch in der App vom
Schnappschuss ab — dann hat jemand im Team bewusst etwas anderes eingetragen, und
ein Import, der das überschreibt, macht Terminabsprachen kaputt.

Eine Zeile je Feld, nicht je Termin: Zeit übernehmen und Platzverlegung verwerfen
muss unabhängig möglich sein. `feld` trägt zusätzlich den Pseudo-Wert 'entfallen'
für Spiele, die im Export nicht mehr auftauchen.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class TerminAbweichung:
    id: int
    termin_id: int
    quelle: str                       # 'dfbnet'
    feld: str                         # 'beginn' | 'ort' | 'heim_auswaerts' | 'gegner' | 'entfallen'
    wert_app: Optional[str]           # Stand in der App zum Erkennungszeitpunkt
    wert_extern: Optional[str]        # Stand laut Quelle
    spielstaette_id: Optional[int]    # nur bei feld='ort': Platz hinter wert_extern
    erkannt_am: str
    status: str                       # 'offen' | 'uebernommen' | 'verworfen' | 'hinfaellig'
    entschieden_von: Optional[str]
    entschieden_am: Optional[str]
    version: int
    created_at: str
    created_by: str
    updated_at: str
    updated_by: str
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None
    # Nur für die Anzeige (per JOIN aufgelöst), keine Tabellenspalten:
    mannschaft_id: Optional[int] = None
    termin_beginn: Optional[str] = None
    spielstaette_name: Optional[str] = None
