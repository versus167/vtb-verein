"""Datenmodell für Termin-Zusagen (RSVP, #95 Spielbetrieb Etappe 2, Schema v69).

Je Termin höchstens eine aktive Antwort pro Kader-Mitglied
('zu' | 'vielleicht' | 'ab'). Der Zugriff wird – wie bei den Terminen selbst –
NICHT über globale Rechte geregelt, sondern über die Kader-Zugehörigkeit
(mitglied_mannschaft): aktive Kader-Mitglieder setzen ihre eigene Antwort,
betreuer/uebungsleiter dürfen die Antwort anderer Kader-Mitglieder setzen.
Zurücknehmen = Soft-Delete (deleted_at); erneutes Setzen re-aktiviert per Upsert.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class TerminZusage:
    id: int
    termin_id: int
    mitglied_id: int
    antwort: str                      # 'zu' | 'vielleicht' | 'ab'
    kommentar: Optional[str]
    version: int
    created_at: str
    created_by: str
    updated_at: str
    updated_by: str
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None
