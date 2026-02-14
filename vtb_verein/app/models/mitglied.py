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
    
    # Zahlungsdaten
    zahlungsart: str = ""
    iban: Optional[str] = None
    bic: Optional[str] = None
    kontoinhaber: Optional[str] = None
    abgerechnet_bis: Optional[str] = None
    
    # Metadaten (vom System verwaltet)
    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None
