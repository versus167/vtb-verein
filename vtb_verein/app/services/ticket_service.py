'''
TicketService - Business-Logik für das Ticket-System

Phase 4.1 - Ticket-System Repository & Service
Phase 4.2 - berechtigung_repo hinzugefügt
'''

from datetime import datetime
from typing import Optional
from app.models.ticket import (
    Ticket, TicketKommentar, TicketAnhang, TicketBereich, TicketKategorie,
    TicketStatus, TicketTeilnehmer
)
from app.db.ticket_repository import TicketRepository
from app.db.ticket_kommentar_repository import TicketKommentarRepository
from app.db.ticket_anhang_repository import TicketAnhangRepository
from app.db.ticket_bereich_repository import TicketBereichRepository
from app.db.ticket_kategorie_repository import TicketKategorieRepository
from app.db.ticket_teilnehmer_repository import TicketTeilnehmerRepository
from app.db.ticket_bereich_berechtigung_repository import TicketBereichBerechtigungRepository


class TicketNichtGefundenError(Exception):
    pass


class UngueltigerStatusWechselError(Exception):
    pass


# Erlaubte Statusübergänge
STATUS_UEBERGAENGE: dict[str, list[str]] = {
    TicketStatus.OFFEN:       [TicketStatus.IN_PRUEFUNG, TicketStatus.ABGELEHNT],
    TicketStatus.IN_PRUEFUNG: [TicketStatus.EINGEPLANT, TicketStatus.RUECKFRAGE, TicketStatus.ABGELEHNT],
    TicketStatus.EINGEPLANT:  [TicketStatus.IN_PRUEFUNG, TicketStatus.ERLEDIGT],
    TicketStatus.RUECKFRAGE:  [TicketStatus.IN_PRUEFUNG, TicketStatus.ABGELEHNT],
    TicketStatus.ERLEDIGT:    [],
    TicketStatus.ABGELEHNT:   [],
}


class TicketService:

    def __init__(
        self,
        ticket_repo: TicketRepository,
        kommentar_repo: TicketKommentarRepository,
        anhang_repo: TicketAnhangRepository,
        bereich_repo: TicketBereichRepository,
        kategorie_repo: TicketKategorieRepository,
        teilnehmer_repo: TicketTeilnehmerRepository,
        berechtigung_repo: TicketBereichBerechtigungRepository,
    ):
        self._ticket_repo = ticket_repo
        self._kommentar_repo = kommentar_repo
        self._anhang_repo = anhang_repo
        self._bereich_repo = bereich_repo
        self._kategorie_repo = kategorie_repo
        self._teilnehmer_repo = teilnehmer_repo
        self._berechtigung_repo = berechtigung_repo

    # -----------------------------------
    # Tickets
    # -----------------------------------

    def get_ticket(self, id: int) -> Ticket:
        ticket = self._ticket_repo.get(id)
        if not ticket:
            raise TicketNichtGefundenError(f"Ticket #{id} nicht gefunden.")
        return ticket

    def list_tickets(
        self,
        status: Optional[str] = None,
        assigned_to: Optional[int] = None,
        reporter: Optional[int] = None,
    ) -> list[Ticket]:
        if status:
            tickets = self._ticket_repo.list_by_status(status)
        elif assigned_to:
            tickets = self._ticket_repo.list_by_assigned(assigned_to)
        elif reporter:
            tickets = self._ticket_repo.list_by_reporter(reporter)
        else:
            tickets = self._ticket_repo.list_all()
        return tickets

    def create_ticket(self, ticket: Ticket, created_by: str) -> Ticket:
        return self._ticket_repo.create(ticket, created_by)

    def update_ticket(self, ticket: Ticket, updated_by: str) -> bool:
        return self._ticket_repo.update(ticket, updated_by)

    def change_status(self, ticket_id: int, new_status: str, changed_by: str, version: int) -> bool:
        """Statuswechsel mit Übergangsprüfung. Setzt closed_at/closed_by bei 'erledigt'."""
        ticket = self.get_ticket(ticket_id)
        erlaubt = STATUS_UEBERGAENGE.get(ticket.status, [])
        if new_status not in erlaubt:
            raise UngueltigerStatusWechselError(
                f"Statuswechsel von '{ticket.status}' nach '{new_status}' nicht erlaubt."
            )
        ticket.status = new_status
        ticket.version = version
        if new_status == TicketStatus.ERLEDIGT:
            ticket.closed_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        return self._ticket_repo.update(ticket, changed_by)

    def mark_ticket_deleted(self, ticket_id: int, deleted_by: str) -> bool:
        return self._ticket_repo.mark_deleted(ticket_id, deleted_by)

    def get_ticket_history(self, ticket_id: int) -> list[dict]:
        return self._ticket_repo.get_history(ticket_id)

    # -----------------------------------
    # Kommentare
    # -----------------------------------

    def add_kommentar(self, kommentar: TicketKommentar, created_by: str) -> TicketKommentar:
        return self._kommentar_repo.create(kommentar, created_by)

    def update_kommentar(self, kommentar: TicketKommentar, updated_by: str) -> bool:
        return self._kommentar_repo.update(kommentar, updated_by)

    def mark_kommentar_deleted(self, id: int, deleted_by: str) -> bool:
        return self._kommentar_repo.mark_deleted(id, deleted_by)

    def get_kommentare(self, ticket_id: int, include_internal: bool = False) -> list[TicketKommentar]:
        return self._kommentar_repo.list_by_ticket(ticket_id, include_internal)

    def get_kommentar_history(self, kommentar_id: int) -> list[dict]:
        return self._kommentar_repo.get_history(kommentar_id)

    # -----------------------------------
    # Anhänge
    # -----------------------------------

    def add_anhang(self, anhang: TicketAnhang) -> TicketAnhang:
        return self._anhang_repo.create(anhang)

    def mark_anhang_deleted(self, id: int, deleted_by: str) -> bool:
        return self._anhang_repo.mark_deleted(id, deleted_by)

    def get_anhaenge(self, ticket_id: int) -> list[TicketAnhang]:
        return self._anhang_repo.list_by_ticket(ticket_id)

    def get_anhaenge_by_comment(self, comment_id: int) -> list[TicketAnhang]:
        return self._anhang_repo.list_by_comment(comment_id)

    # -----------------------------------
    # Teilnehmer
    # -----------------------------------

    def get_teilnehmer(self, ticket_id: int) -> list[TicketTeilnehmer]:
        return self._teilnehmer_repo.list_by_ticket(ticket_id)

    def add_teilnehmer(self, ticket_id: int, member_id: int, added_by: int) -> bool:
        return self._teilnehmer_repo.add(ticket_id, member_id, added_by)

    def remove_teilnehmer(self, ticket_id: int, member_id: int) -> bool:
        return self._teilnehmer_repo.remove(ticket_id, member_id)

    # -----------------------------------
    # Bereiche & Kategorien
    # -----------------------------------

    def get_bereiche(self) -> list[TicketBereich]:
        return self._bereich_repo.list_all()

    def create_bereich(self, bereich: TicketBereich, created_by: str) -> TicketBereich:
        return self._bereich_repo.create(bereich, created_by)

    def update_bereich(self, bereich: TicketBereich, updated_by: str) -> bool:
        return self._bereich_repo.update(bereich, updated_by)

    def mark_bereich_deleted(self, id: int, deleted_by: str) -> bool:
        return self._bereich_repo.mark_deleted(id, deleted_by)

    def get_kategorien(self) -> list[TicketKategorie]:
        return self._kategorie_repo.list_all()

    def create_kategorie(self, kategorie: TicketKategorie, created_by: str) -> TicketKategorie:
        return self._kategorie_repo.create(kategorie, created_by)

    def update_kategorie(self, kategorie: TicketKategorie, updated_by: str) -> bool:
        return self._kategorie_repo.update(kategorie, updated_by)

    def mark_kategorie_deleted(self, id: int, deleted_by: str) -> bool:
        return self._kategorie_repo.mark_deleted(id, deleted_by)

    # -----------------------------------
    # Bereichsberechtigungen
    # -----------------------------------

    def get_berechtigungen_fuer_bereich(self, bereich_id: int) -> list[dict]:
        return self._berechtigung_repo.list_by_bereich(bereich_id)

    def get_berechtigungen_fuer_user(self, user_id: int) -> list[dict]:
        return self._berechtigung_repo.list_by_user(user_id)
