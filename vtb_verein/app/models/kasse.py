'''
Kasse und Kassenbuchung Models.

@author: AI Assistant
'''

from dataclasses import dataclass, field
from typing import Optional


# Stückelung des Euro in Cent, absteigend (Scheine, dann Münzen).
# Für die Zählprotokoll-Erfassung und die serverseitige Ist-Berechnung.
EURO_STUECKELUNG_CENT: tuple[int, ...] = (
    50000, 20000, 10000, 5000, 2000, 1000, 500,   # Scheine: 500 € … 5 €
    200, 100, 50, 20, 10, 5, 2, 1,                 # Münzen:  2 € … 1 ct
)


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
    kategorie: str = ''
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
    anhang_count: Optional[int] = None

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
class KassenbuchungAnhang:
    """Foto oder PDF-Beleg, der einer Kassenbuchung zugeordnet ist."""
    id: Optional[int] = None
    buchung_id: Optional[int] = None
    original_name: str = ''
    stored_name: str = ''
    mime_type: str = ''
    dateigroesse: int = 0
    hochgeladen_von: Optional[int] = None
    hochgeladen_am: Optional[str] = None
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None


@dataclass
class KassenKategorie:
    """Verwaltete Kategorie für Kassenbuchungen.

    kasse_id == None  → allgemeine Kategorie, bei jeder Kasse wählbar.
    kasse_id gesetzt  → nur bei der zugeordneten Kasse wählbar.

    Die Buchung speichert die Kategorie weiterhin als Text (denormalisiert);
    diese Stammdaten steuern nur die Auswahl bei der Erfassung.
    """
    name: str
    kasse_id: Optional[int] = None      # None = allgemein (gilt für alle Kassen)
    loest_zaehlung_aus: bool = False    # True → Buchung mit dieser Kategorie fordert eine Kassenzählung an

    id: Optional[int] = None
    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None

    @property
    def ist_allgemein(self) -> bool:
        return self.kasse_id is None


@dataclass
class KassenZaehlung:
    """Ein Zählprotokoll (Kassensturz) einer Barkasse.

    Hält die gezählte Stückelung sowie den Soll-/Ist-Abgleich. Jede Zählung erzeugt
    eine zugehörige „Zähl-Buchung" (`buchung_id`), an der das Protokoll-PDF hängt und
    über die Uhrzeit/Ersteller dokumentiert sind. `soll_cent` wird beim Zählen
    eingefroren (spätere Buchungen ändern den Buchbestand, das Protokoll bleibt fix).

    stueckelung: {wert_cent (als int): anzahl}, z.B. {5000: 2, 200: 13}.
    """
    kasse_id: int
    ist_cent: int
    soll_cent: int
    differenz_cent: int
    stueckelung: dict = field(default_factory=dict)
    buchung_id: Optional[int] = None             # Zähl-Buchung (Träger des PDFs)
    ausloesende_buchung_id: Optional[int] = None  # Kontext bei Kategorie-Trigger
    notiz: Optional[str] = None

    id: Optional[int] = None
    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None

    @property
    def ist_euro(self) -> float:
        return self.ist_cent / 100

    @property
    def soll_euro(self) -> float:
        return self.soll_cent / 100

    @property
    def differenz_euro(self) -> float:
        return self.differenz_cent / 100

    @property
    def stimmt_ueberein(self) -> bool:
        return self.differenz_cent == 0


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
