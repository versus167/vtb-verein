"""Sammellauf für die Monatsbeiträge aller aktiven Teamtresore (#98).

Der Mannschaftsbeitrag ist pro Mitglied an/aus (Opt-out über eine Befreiung).
Für jedes aktive Kader-Mitglied ohne Befreiung wird am Monatsersten der fällige
Beitrag gebucht. Diese Funktion bündelt den Lauf über ALLE aktiven Teamtresore
und wird vom Sidecar (tools/clubdeckel_beitrag_lauf.py) periodisch aufgerufen.

Dieselbe idempotente Nachbuchung greift lazily beim Öffnen eines Teamtresors
(backend/api/clubdeckel.py::_beitragslauf); der Sammellauf sorgt nur dafür, dass
die Buchungen auch ohne Zugriff kurz nach dem 1. entstehen. Ein Monat wird nie
doppelt gebucht (buche_faellige_beitraege prüft vorhandene Beitragszeilen).
"""
from __future__ import annotations


def run_beitragslauf(db) -> dict[int, int]:
    """Bucht für jeden aktiven Teamtresor mit Monatsbeitrag die fälligen Monate.

    Gibt ein Dict ``{deckel_id: neu_gebuchte_zeilen}`` über alle geprüften Deckel
    zurück (auch mit 0), damit der Aufrufer sauber protokollieren kann.
    """
    ergebnis: dict[int, int] = {}
    for d in db.clubdeckel.list_aktive_mit_beitrag():
        ergebnis[d.id] = db.clubdeckel_buchungen.buche_faellige_beitraege(
            d.id, d.mannschaft_id, d.beitrag, d.beitrag_ab)
    return ergebnis
