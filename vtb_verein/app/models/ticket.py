'''
Ticket-System Datenmodelle

@author: volker
'''

from dataclasses import dataclass, field
from typing import Optional


class TicketStatus:
    OFFEN = 'offen'
    IN_PRUEFUNG = 'in_pruefung'
    EINGEPLANT = 'eingeplant'
    RUECKFRAGE = 'rueckfrage'
    ERLEDIGT = 'erledigt'
    ABGELEHNT = 'abgelehnt'

    ALL = [OFFEN, IN_PRUEFUNG, EINGEPLANT, RUECKFRAGE, ERLEDIGT, ABGELEHNT]

    LABELS = {
        OFFEN: 'Offen',
        IN_PRUEFUNG: 'In Prüfung',
        EINGEPLANT: 'Eingeplant',
        RUECKFRAGE: 'Rückfrage',
        ERLEDIGT: 'Erledigt',
        ABGELEHNT: 'Abgelehnt',
    }

    ABGESCHLOSSEN = {ERLEDIGT, ABGELEHNT}


class TicketPrioritaet:
    NIEDRIG = 'niedrig'
    NORMAL = 'normal'
    HOCH = 'hoch'
    SICHERHEIT = 'sicherheit'

    ALL = [NIEDRIG, NORMAL, HOCH, SICHERHEIT]

    LABELS = {
        NIEDRIG: 'Niedrig',
        NORMAL: 'Normal',
        HOCH: 'Hoch',
        SICHERHEIT: '🔴 Sicherheit',
    }


@dataclass
class TicketBereich:
    id: Optional[int] = field(default=None)
    name: str = field(default='')
    beschreibung: Optional[str] = field(default=None)
    version: int = field(default=1)
    created_at: Optional[str] = field(default=None)
    deleted_at: Optional[str] = field(default=None)
    deleted_by: Optional[str] = field(default=None)


@dataclass
class TicketKategorie:
    id: Optional[int] = field(default=None)
    name: str = field(default='')
    icon: Optional[str] = field(default=None)
    version: int = field(default=1)
    deleted_at: Optional[str] = field(default=None)
    deleted_by: Optional[str] = field(default=None)


@dataclass
class Ticket:
    id: Optional[int] = field(default=None)
    titel: str = field(default='')
    beschreibung: str = field(default='')
    status: str = field(default=TicketStatus.OFFEN)
    prioritaet: str = field(default=TicketPrioritaet.NORMAL)
    # Intern (#178): sichtbar nur für Melder, Zugewiesenen, am Bereich
    # Berechtigte und Admins. Offen (False) ist der Normalfall.
    intern: bool = field(default=False)
    bereich_id: Optional[int] = field(default=None)
    kategorie_id: Optional[int] = field(default=None)
    gemeldet_von: Optional[int] = field(default=None)
    zugewiesen_an: Optional[int] = field(default=None)
    faellig_am: Optional[str] = field(default=None)
    geschlossen_am: Optional[str] = field(default=None)
    geschlossen_von: Optional[int] = field(default=None)
    version: int = field(default=1)
    created_at: Optional[str] = field(default=None)
    updated_at: Optional[str] = field(default=None)
    deleted_at: Optional[str] = field(default=None)
    deleted_by: Optional[str] = field(default=None)
    kommentar_count: Optional[int] = field(default=None)
    anhang_count: Optional[int] = field(default=None)
    # Nur von `list_stillstehend` gefüllt (#179-Nachgang): seit wann am Ticket nichts mehr
    # geschieht – der spätere von „letzte Änderung/Kommentar/Anhang" und „erster
    # Blick eines Verantwortlichen". Erneutes Ansehen verschiebt ihn nicht.
    stillstand_seit: Optional[str] = field(default=None)


@dataclass
class TicketKommentar:
    id: Optional[int] = field(default=None)
    ticket_id: Optional[int] = field(default=None)
    autor_id: Optional[int] = field(default=None)
    inhalt: str = field(default='')
    sichtbarkeit: str = field(default='oeffentlich')
    version: int = field(default=1)
    created_at: Optional[str] = field(default=None)
    deleted_at: Optional[str] = field(default=None)
    deleted_by: Optional[str] = field(default=None)


@dataclass
class TicketAnhang:
    id: Optional[int] = field(default=None)
    ticket_id: Optional[int] = field(default=None)
    kommentar_id: Optional[int] = field(default=None)
    original_name: str = field(default='')
    stored_name: str = field(default='')
    mime_type: str = field(default='')
    dateigroesse: int = field(default=0)
    hochgeladen_von: Optional[int] = field(default=None)
    hochgeladen_am: Optional[str] = field(default=None)
    deleted_at: Optional[str] = field(default=None)
    deleted_by: Optional[str] = field(default=None)


@dataclass
class TicketTeilnehmer:
    ticket_id: Optional[int] = field(default=None)
    user_id: Optional[int] = field(default=None)
    hinzugefuegt_von: Optional[int] = field(default=None)
    hinzugefuegt_am: Optional[str] = field(default=None)


@dataclass
class TicketErinnerungEinstellungen:
    """Fristen der Ticket-Erinnerungen (Single-Row, id=1) – #179-Nachgang.

    Zwei Erinnerungsarten, die verschiedene Fragen stellen:

    * **unbeachtet** – noch NIEMAND aus dem zuständigen Kreis hat das Ticket
      geöffnet (#179). Gezählt ab Erstellung.
    * **stillstand** – jemand hat es gesehen, seither ist aber nichts mehr
      passiert: kein Kommentar, keine Statusänderung, kein Anhang. Gezählt ab
      der letzten Aktivität.

    Je Priorität eine Frist in Tagen, dazu der Abstand der Wiederholungen und ein
    Schalter je Art. **Frist 0 schaltet die einzelne Priorität ab** – niedrige
    Tickets dürfen in Ruhe liegen, sicherheitsrelevante nicht.
    """
    id: int = 1

    unbeachtet_aktiv: bool = True
    unbeachtet_tage_sicherheit: int = 1
    unbeachtet_tage_hoch: int = 1
    unbeachtet_tage_normal: int = 3
    unbeachtet_tage_niedrig: int = 7
    unbeachtet_wiederholung_tage: int = 7

    stillstand_aktiv: bool = True
    stillstand_tage_sicherheit: int = 3
    stillstand_tage_hoch: int = 7
    stillstand_tage_normal: int = 28
    stillstand_tage_niedrig: int = 28
    stillstand_wiederholung_tage: int = 14

    version: int = 1
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None

    def _tage(self, art: str, prioritaet: str) -> int:
        """Frist für diese Priorität; unbekannte Prioritäten erben die von „Normal"."""
        return getattr(self, f"{art}_tage_{prioritaet}",
                       getattr(self, f"{art}_tage_normal"))

    def unbeachtet_tage(self, prioritaet: str) -> int:
        return self._tage("unbeachtet", prioritaet)

    def stillstand_tage(self, prioritaet: str) -> int:
        return self._tage("stillstand", prioritaet)
