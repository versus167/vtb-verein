'''
TicketService - Business-Logik für das Ticket-System

Phase 4.1 - Ticket-System Repository & Service
Phase 4.2 - berechtigung_repo hinzugefügt
fix     - list_by_assigned → list_by_zugewiesen
        - list_by_reporter → list_by_gemeldet
        - closed_at → geschlossen_am
'''

import io
from datetime import datetime
from typing import TYPE_CHECKING, Optional
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
from app.db.user_repository import UserRepository

if TYPE_CHECKING:
    from app.services.anhang_service import AnhangService


class TicketNichtGefundenError(Exception):
    pass


class UngueltigerStatusWechselError(Exception):
    pass


# Erlaubte Statusübergänge
STATUS_UEBERGAENGE: dict[str, list[str]] = {
    TicketStatus.OFFEN:       [TicketStatus.IN_PRUEFUNG, TicketStatus.ERLEDIGT, TicketStatus.ABGELEHNT],
    TicketStatus.IN_PRUEFUNG: [TicketStatus.EINGEPLANT, TicketStatus.RUECKFRAGE, TicketStatus.ERLEDIGT, TicketStatus.ABGELEHNT],
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
        user_repo: UserRepository,
        anhang_service: "AnhangService | None" = None,
    ):
        self._ticket_repo = ticket_repo
        self._kommentar_repo = kommentar_repo
        self._anhang_repo = anhang_repo
        self._bereich_repo = bereich_repo
        self._kategorie_repo = kategorie_repo
        self._teilnehmer_repo = teilnehmer_repo
        self._berechtigung_repo = berechtigung_repo
        self._user_repo = user_repo
        self._anhang_service = anhang_service

    # -----------------------------------
    # Benachrichtigungen (intern)
    # -----------------------------------

    def _notify(self, user_ids: list[int], exclude_user_id: Optional[int], title: str, message: str) -> None:
        """Lädt User-Objekte und sendet Benachrichtigungen; überspringt den auslösenden User."""
        from app.services.notification_service import NotificationService
        seen: set[int] = set()
        for uid in user_ids:
            if uid is None or uid in seen or uid == exclude_user_id:
                continue
            seen.add(uid)
            user = self._user_repo.get_by_id(uid)
            if user and user.active:
                NotificationService.send_notification(user, title, message)

    def _bereich_user_ids(self, bereich_id: Optional[int]) -> list[int]:
        """User-IDs mit bearbeiten- oder schliessen-Recht im Bereich."""
        if not bereich_id:
            return []
        return self._berechtigung_repo.list_user_ids_bearbeiten_oder_schliessen(bereich_id)

    def _ticket_empfaenger(self, ticket: Ticket) -> list[int]:
        """Ersteller + Zugewiesener + Teilnehmer + Bereich-User (bearbeiten/schliessen)."""
        ids = []
        if ticket.gemeldet_von:
            ids.append(ticket.gemeldet_von)
        if ticket.zugewiesen_an:
            ids.append(ticket.zugewiesen_an)
        for t in self._teilnehmer_repo.list_by_ticket(ticket.id):
            ids.append(t.user_id)
        ids += self._bereich_user_ids(ticket.bereich_id)
        return ids

    def _actor_id(self, username: str) -> Optional[int]:
        """Konvertiert Username-String in User-ID für Ausschluss-Logik."""
        user = self._user_repo.get_by_username(username)
        return user.id if user else None

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
            tickets = self._ticket_repo.list_by_zugewiesen(assigned_to)
        elif reporter:
            tickets = self._ticket_repo.list_by_gemeldet(reporter)
        else:
            tickets = self._ticket_repo.list_all()
        return tickets

    def list_tickets_with_counts(self) -> list[Ticket]:
        return self._ticket_repo.list_all_with_counts()

    def create_ticket(self, ticket: Ticket, created_by: str) -> Ticket:
        created = self._ticket_repo.create(ticket, created_by)
        bereich_ids = self._bereich_user_ids(created.bereich_id)
        empfaenger = list({*bereich_ids, *([ created.zugewiesen_an] if created.zugewiesen_an else [])})
        self._notify(empfaenger, self._actor_id(created_by),
                     f"🎫 Neues Ticket #{created.id}",
                     f"{created.titel or ''}\n\nErstellt von: {created_by}")
        return created

    def update_ticket(self, ticket: Ticket, updated_by: str) -> bool:
        old = self._ticket_repo.get(ticket.id)
        result = self._ticket_repo.update(ticket, updated_by)
        if result and old and old.zugewiesen_an != ticket.zugewiesen_an and ticket.zugewiesen_an:
            self._notify([ticket.zugewiesen_an], self._actor_id(updated_by),
                         f"🎫 Ticket #{ticket.id} zugewiesen",
                         f"Dir wurde Ticket \"{ticket.titel}\" zugewiesen.\n\nZugewiesen von: {updated_by}")
        return result

    def change_status(self, ticket_id: int, new_status: str, changed_by: str, version: int) -> bool:
        """Statuswechsel mit Übergangsprüfung. Setzt geschlossen_am/geschlossen_von bei 'erledigt'."""
        ticket = self.get_ticket(ticket_id)
        erlaubt = STATUS_UEBERGAENGE.get(ticket.status, [])
        if new_status not in erlaubt:
            raise UngueltigerStatusWechselError(
                f"Statuswechsel von '{ticket.status}' nach '{new_status}' nicht erlaubt."
            )
        ticket.status = new_status
        ticket.version = version
        if new_status == TicketStatus.ERLEDIGT:
            ticket.geschlossen_am = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        result = self._ticket_repo.update(ticket, changed_by)
        if result:
            self._notify(self._ticket_empfaenger(ticket), self._actor_id(changed_by),
                         f"🎫 Ticket #{ticket_id} → {new_status}",
                         f"Status von \"{ticket.titel}\" wurde auf \"{new_status}\" geändert.\n\nGeändert von: {changed_by}")
        return result

    def mark_ticket_deleted(self, ticket_id: int, deleted_by: str) -> bool:
        return self._ticket_repo.mark_deleted(ticket_id, deleted_by)

    def get_ticket_history(self, ticket_id: int) -> list[dict]:
        return self._ticket_repo.get_history(ticket_id)

    # -----------------------------------
    # Kommentare
    # -----------------------------------

    def add_kommentar(self, kommentar: TicketKommentar, created_by: str) -> TicketKommentar:
        created = self._kommentar_repo.create(kommentar, created_by)
        ticket = self._ticket_repo.get(kommentar.ticket_id)
        if ticket:
            if kommentar.sichtbarkeit == 'intern':
                # Interner Kommentar: nur Zugewiesener + Teilnehmer
                empfaenger = [ticket.zugewiesen_an] if ticket.zugewiesen_an else []
                empfaenger += [t.user_id for t in self._teilnehmer_repo.list_by_ticket(ticket.id)]
            else:
                empfaenger = self._ticket_empfaenger(ticket)
            self._notify(empfaenger, self._actor_id(created_by),
                         f"🎫 Neuer Kommentar zu Ticket #{ticket.id}",
                         f"\"{ticket.titel}\"\n\nVon: {created_by}\n\n{kommentar.inhalt[:200]}")
        return created

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

    def add_anhang(
        self,
        ticket_id: int,
        kommentar_id: int | None,
        original_name: str,
        mime_type: str,
        inhalt: bytes | io.BytesIO,
        hochgeladen_von: int,
    ) -> TicketAnhang:
        """
        Legt Anhang an (DB-Record + Datei auf Disk).

        Ablauf:
          1. Validierung (MIME-Typ, Größe)
          2. DB-Record anlegen → stored_name ergibt sich aus der Auto-Increment-ID
          3. Datei unter stored_name schreiben
          Falls Schritt 3 fehlschlägt: DB-Record soft-löschen + IOError weiterwerfen.
        """
        from app.services.anhang_service import AnhangService
        if self._anhang_service is None:
            raise RuntimeError("AnhangService nicht konfiguriert.")

        data = inhalt.read() if isinstance(inhalt, io.BytesIO) else inhalt
        dateigroesse = len(data)

        self._anhang_service.validiere(mime_type, dateigroesse)

        anhang = TicketAnhang(
            ticket_id=ticket_id,
            kommentar_id=kommentar_id,
            original_name=original_name,
            mime_type=mime_type,
            dateigroesse=dateigroesse,
            hochgeladen_von=hochgeladen_von,
        )
        db_anhang = self._anhang_repo.create(anhang)

        try:
            self._anhang_service.schreibe(db_anhang.stored_name, data)
        except Exception as exc:
            self._anhang_repo.mark_deleted(db_anhang.id, deleted_by='SYSTEM_FEHLER')
            raise IOError(f"Datei konnte nicht gespeichert werden: {exc}") from exc

        return db_anhang

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
