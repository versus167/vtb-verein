'''
Ticket-System Datenmodelle

Phase 4.1 - Ticket-System Repository & Service

@author: volker
@created: AI Assistant
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
    description: Optional[str] = field(default=None)
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
    title: str = field(default='')
    description: str = field(default='')
    status: str = field(default=TicketStatus.OFFEN)
    priority: str = field(default=TicketPrioritaet.NORMAL)
    area_id: Optional[int] = field(default=None)
    category_id: Optional[int] = field(default=None)
    reported_by: Optional[int] = field(default=None)
    assigned_to: Optional[int] = field(default=None)
    due_date: Optional[str] = field(default=None)
    closed_at: Optional[str] = field(default=None)
    closed_by: Optional[int] = field(default=None)
    version: int = field(default=1)
    created_at: Optional[str] = field(default=None)
    deleted_at: Optional[str] = field(default=None)
    deleted_by: Optional[str] = field(default=None)


@dataclass
class TicketKommentar:
    id: Optional[int] = field(default=None)
    ticket_id: Optional[int] = field(default=None)
    author_id: Optional[int] = field(default=None)
    body: str = field(default='')
    visibility: str = field(default='public')
    version: int = field(default=1)
    created_at: Optional[str] = field(default=None)
    deleted_at: Optional[str] = field(default=None)
    deleted_by: Optional[str] = field(default=None)


@dataclass
class TicketAnhang:
    id: Optional[int] = field(default=None)
    ticket_id: Optional[int] = field(default=None)
    comment_id: Optional[int] = field(default=None)
    original_name: str = field(default='')
    stored_name: str = field(default='')
    mime_type: str = field(default='')
    file_size: int = field(default=0)
    uploaded_by: Optional[int] = field(default=None)
    uploaded_at: Optional[str] = field(default=None)
    deleted_at: Optional[str] = field(default=None)
    deleted_by: Optional[str] = field(default=None)


@dataclass
class TicketTeilnehmer:
    ticket_id: Optional[int] = field(default=None)
    member_id: Optional[int] = field(default=None)
    added_by: Optional[int] = field(default=None)
    added_at: Optional[str] = field(default=None)
