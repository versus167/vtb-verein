'''
Kasse und Kassenbuchung Models.

@author: AI Assistant
'''

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Kasse:
    """Repräsentiert eine Barkasse des Vereins oder einer Abteilung."""
    name: str
    anfangsbestand_cent: int = 0
    beschreibung: Optional[str] = None
    abteilung_id: Optional[int] = None

    id: Optional[int] = None
    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None

    @property
    def anfangsbestand_euro(self) -> float:
        return self.anfangsbestand_cent / 100


@dataclass
class Kassenbuchung:
    """Eine einzelne Ein- oder Ausgabe in einer Kasse."""
    kasse_id: int
    buchungsdatum: str          # ISO-Format: YYYY-MM-DD
    buchungstext: str
    kategorie: str
    einnahme_cent: int = 0      # immer >= 0; 0 = keine Einnahme
    ausgabe_cent: int = 0       # immer >= 0; 0 = keine Ausgabe

    belegnummer: Optional[str] = None   # z.B. "2026-001", read-only nach Erstellen
    notiz: Optional[str] = None
    exportiert_in_export_id: Optional[int] = None  # None = noch nicht exportiert

    id: Optional[int] = None
    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None

    @property
    def ist_exportiert(self) -> bool:
        return self.exportiert_in_export_id is not None

    @property
    def ist_storniert(self) -> bool:
        return self.deleted_at is not None

    @property
    def einnahme_euro(self) -> float:
        return self.einnahme_cent / 100

    @property
    def ausgabe_euro(self) -> float:
        return self.ausgabe_cent / 100


@dataclass
class KassenbuchExport:
    """Repräsentiert einen abgeschlossenen CSV-Export eines Zeitraums."""
    kasse_id: int
    zeitraum_von: str           # ISO-Format: YYYY-MM-DD
    zeitraum_bis: str           # ISO-Format: YYYY-MM-DD
    dateiname: str
    anzahl_buchungen: int

    id: Optional[int] = None
    exportiert_am: Optional[str] = None
    exportiert_von: Optional[str] = None
    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None
