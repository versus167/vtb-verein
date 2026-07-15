"""Datenmodell für Terminserien (#95, Schema v70).

Eine Serie ist die wöchentliche Vorlage je Mannschaft (nur training/sonstiges,
keine Spiel-Serien), aus der konkrete `termine`-Instanzen rollierend
materialisiert werden. `start_datum` ist der Anker und definiert den Wochentag
(nachträglich nicht änderbar — Wochentagwechsel = Serie löschen + neu anlegen);
`ende_datum` optional (offenes Ende). `materialisiert_bis` ist das Wasserzeichen
des Generators und wird nie rückwärts bewegt, damit gelöschte/abgesagte
Instanzen nie neu erzeugt werden.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class TerminSerie:
    id: int
    mannschaft_id: int
    typ: str                          # 'training' | 'sonstiges'
    beginn_zeit: str                  # 'HH:MM' (lokale Wandzeit)
    ende_zeit: Optional[str]          # dito, optional
    ort: Optional[str]
    treffpunkt: Optional[str]
    treffpunkt_zeit: Optional[str]    # 'HH:MM'
    beschreibung: Optional[str]
    start_datum: str                  # 'YYYY-MM-DD' (Anker = Wochentag)
    ende_datum: Optional[str]         # 'YYYY-MM-DD', None = offenes Ende
    materialisiert_bis: str           # 'YYYY-MM-DD' (Wasserzeichen)
    version: int
    created_at: str
    created_by: str
    updated_at: str
    updated_by: str
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None
