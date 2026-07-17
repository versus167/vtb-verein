"""
Mitglied-Model
"""
from dataclasses import dataclass
from typing import Optional

@dataclass
class Mitglied:
    """Repräsentiert ein Vereinsmitglied"""
    # Identifikation
    id: Optional[int] = None
    mitgliedsnummer: Optional[int] = None
    
    # Persönliche Daten
    vorname: str = ""
    nachname: str = ""
    geburtsdatum: Optional[str] = None
    
    # Kontaktdaten
    strasse: Optional[str] = None
    plz: Optional[str] = None
    ort: Optional[str] = None
    land: Optional[str] = None
    email: Optional[str] = None
    telefon: Optional[str] = None
    
    # Vereinsdaten
    eintrittsdatum: Optional[str] = None
    austrittsdatum: Optional[str] = None
    status: str = "aktiv"
    # Personenart: 'mitglied' (Vereinsmitglied) | 'gastspieler' (Gastspielgenehmigung,
    # kein Vereinsmitglied: keine Mitgliedsnummer/Beiträge, zählt nicht in die Statistik,
    # darf aber Abteilungen/Mannschaften zugeordnet und zu Terminen eingeladen werden)
    art: str = "mitglied"
    
    # Zahlungsdaten
    zahlungsart: str = ""
    iban: Optional[str] = None
    bic: Optional[str] = None
    kontoinhaber: Optional[str] = None
    abgerechnet_bis: Optional[str] = None

    # Zusatzfelder (u.a. aus dem SPG-Verein-Import)
    geschlecht: Optional[str] = None          # 'm' | 'w' | 'd'
    bemerkungen: Optional[str] = None
    sepa_mandatsref: Optional[str] = None
    sepa_mandatsdatum: Optional[str] = None

    # Übungsleiter-Stammdaten (für den Stundennachweis-Beleg)
    trainerlizenz_nr: Optional[str] = None
    qualifikation: Optional[str] = None
    trainerlizenz_gueltig_bis: Optional[str] = None   # ISO-Datum; Ende des Lizenzfensters
    trainerlizenz_gueltig_von: Optional[str] = None   # ISO-Datum; Beginn des Lizenzfensters
    # Kopplung (Backend/Dialog erzwungen): nr + gueltig_von + gueltig_bis nur gemeinsam.
    # Lizenz-Klassifikation der Abrechnung leitet sich aus dem Fenster [von, bis] ab.

    # Verknüpfung mit User-Account (optional)
    user_id: Optional[int] = None

    # Metadaten (vom System verwaltet)
    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None
