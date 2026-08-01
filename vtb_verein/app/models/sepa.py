"""
Datenmodelle für den SEPA-Lastschrifteinzug (pain.008, Ticket #114).

- SepaLauf:     Header einer erzeugten pain.008-Datei (ein Einzugslauf).
- SepaPosition: eine Einzelbuchung des Laufs – bewusst als SNAPSHOT der Einzugsdaten
  (Betrag, IBAN, Mandat, Name), damit ein Re-Download dieselbe Datei liefert, auch
  wenn das Mitglied später eine andere Bankverbindung pflegt.
- SepaKandidat: format-neutraler Vorschau-Eintrag – ein offener Posten, der einziehbar
  ist (``ausschluss is None``) oder eben nicht (``ausschluss`` nennt den Grund).
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SepaPosition:
    """Eine Lastschrift innerhalb eines Laufs (Snapshot, siehe Modul-Docstring)."""
    id: Optional[int] = None
    sepa_lauf_id: Optional[int] = None
    quelle_typ: str = ""               # 'beitrag' | 'gebuehr'
    quelle_id: int = 0
    mitglied_id: int = 0
    betrag_cent: int = 0
    end_to_end_id: str = ""
    mandatsref: str = ""
    mandatsdatum: str = ""             # ISO (Datum der Mandatsunterschrift)
    iban: str = ""
    bic: Optional[str] = None
    kontoinhaber: str = ""             # Debtor-Name in der Datei
    verwendungszweck: Optional[str] = None
    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None


@dataclass
class SepaLauf:
    """Header eines Einzugslaufs (eine pain.008-Datei)."""
    id: Optional[int] = None
    dateiname: str = ""
    message_id: str = ""
    ausfuehrungsdatum: str = ""        # ISO – ReqdColltnDt
    sequenztyp: str = "RCUR"
    glaeubiger_id: str = ""            # Snapshot der Gläubiger-ID (CI)
    glaeubiger_name: str = ""
    glaeubiger_iban: str = ""
    glaeubiger_bic: Optional[str] = None
    anzahl_positionen: int = 0         # Posten – Lastschriften sind es weniger (Bündelung)
    anzahl_lastschriften: int = 0      # nicht gespeichert: gezählt über die EndToEndIds
    summe_cent: int = 0
    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None
    positionen: list[SepaPosition] = field(default_factory=list)


@dataclass
class SepaKandidat:
    """Ein offener Posten in der Einzugs-Vorschau.

    ``ausschluss`` ist None, wenn der Posten in die Datei kann; sonst steht dort der
    Grund (fehlende IBAN, kein Mandat, …) und der Posten wird nur angezeigt.
    """
    quelle_typ: str = ""
    quelle_id: int = 0
    mitglied_id: int = 0
    mitglied_name: str = ""            # "Nachname, Vorname" (Anzeige)
    mitgliedsnummer: Optional[int] = None
    bezeichnung: str = ""              # Regel-/Gebührname + Zeitraum
    betrag_cent: int = 0
    faelligkeitsdatum: Optional[str] = None
    iban: Optional[str] = None
    bic: Optional[str] = None
    kontoinhaber: str = ""
    mandatsref: Optional[str] = None
    mandatsdatum: Optional[str] = None
    ausschluss: Optional[str] = None
