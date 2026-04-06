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
    bereich_id: Optional[int] = field(default=None)
    kategorie_id: Optional[int] = field(default=None)
    gemeldet_von: Optional[int] = field(default=None)
    zugewiesen_an: Optional[int] = field(default=None)
    faellig_am: Optional[str] = field(default=None)
    geschlossen_am: Optional[str] = field(default=None)
    geschlossen_von: Optional[int] = field(default=None)
    version: int = field(default=1)
    created_at: Optional[str] = field(default=None)
    deleted_at: Optional[str] = field(default=None)
    deleted_by: Optional[str] = field(default=None)


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
