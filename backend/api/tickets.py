"""
Ticket API – Tickets, Bereiche, Kategorien, Anhänge.

Berechtigungsmodell:
  - Admins: voller Zugriff auf alles
  - Normale User:
      - Lesen:      darf_lesen auf den Bereich des Tickets  (oder eigene Tickets)
      - Schreiben:  darf_bearbeiten auf den Bereich
      - Abschließen: darf_schliessen auf den Bereich
      - Bereiche/Kategorien verwalten: nur Admin
"""

from dataclasses import asdict
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel
from typing import Optional

from backend.core.deps import CurrentUser, DB
from app.models.ticket import (
    Ticket, TicketBereich, TicketKategorie, TicketKommentar,
    TicketStatus, TicketPrioritaet,
)
from app.services.ticket_service import TicketNichtGefundenError, UngueltigerStatusWechselError
from app.services.anhang_service import DateitypNichtErlaubtError, DateiZuGrossError

router = APIRouter(prefix="/tickets", tags=["tickets"])


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------

class TicketWrite(BaseModel):
    titel: str
    beschreibung: str = ''
    prioritaet: str = TicketPrioritaet.NORMAL
    bereich_id: Optional[int] = None
    kategorie_id: Optional[int] = None
    zugewiesen_an: Optional[int] = None
    faellig_am: Optional[str] = None


class TicketUpdate(TicketWrite):
    expected_version: int


class StatusChange(BaseModel):
    status: str
    expected_version: int


class KommentarWrite(BaseModel):
    inhalt: str
    sichtbarkeit: str = 'oeffentlich'


class BereichWrite(BaseModel):
    name: str
    beschreibung: Optional[str] = None


class BereichUpdate(BereichWrite):
    expected_version: int


class KategorieWrite(BaseModel):
    name: str
    icon: Optional[str] = None


class KategorieUpdate(KategorieWrite):
    expected_version: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_admin(user) -> None:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Nur Administratoren dürfen diese Aktion ausführen.")


def _can_read(ticket: Ticket, user, db) -> bool:
    if user.role == "admin":
        return True
    if ticket.gemeldet_von == user.id or ticket.zugewiesen_an == user.id:
        return True
    if ticket.bereich_id is None:
        return True
    return db.ticket_bereich_berechtigungen.user_darf_lesen(ticket.bereich_id, user.id)


def _can_write(ticket: Ticket, user, db) -> bool:
    if user.role == "admin":
        return True
    if ticket.bereich_id is None:
        return ticket.gemeldet_von == user.id
    return db.ticket_bereich_berechtigungen.user_darf_bearbeiten(ticket.bereich_id, user.id)


def _can_close(ticket: Ticket, user, db) -> bool:
    if user.role == "admin":
        return True
    if ticket.bereich_id is None:
        return False
    return db.ticket_bereich_berechtigungen.user_darf_schliessen(ticket.bereich_id, user.id)


def _get_ticket_or_404(ticket_id: int, db) -> Ticket:
    try:
        return db.tickets.get_ticket(ticket_id)
    except TicketNichtGefundenError:
        raise HTTPException(status_code=404, detail=f"Ticket #{ticket_id} nicht gefunden.")


# ---------------------------------------------------------------------------
# Bereiche
# ---------------------------------------------------------------------------

@router.get("/bereiche")
def list_bereiche(user: CurrentUser, db: DB):
    return [asdict(b) for b in db.tickets.get_bereiche()]


@router.post("/bereiche", status_code=201)
def create_bereich(data: BereichWrite, user: CurrentUser, db: DB):
    _require_admin(user)
    bereich = TicketBereich(name=data.name, beschreibung=data.beschreibung)
    return asdict(db.tickets.create_bereich(bereich, created_by=user.username))


@router.put("/bereiche/{bereich_id}")
def update_bereich(bereich_id: int, data: BereichUpdate, user: CurrentUser, db: DB):
    _require_admin(user)
    bereiche = db.tickets.get_bereiche()
    bereich = next((b for b in bereiche if b.id == bereich_id), None)
    if not bereich:
        raise HTTPException(status_code=404, detail=f"Bereich {bereich_id} nicht gefunden.")
    bereich.name = data.name
    bereich.beschreibung = data.beschreibung
    bereich.version = data.expected_version
    ok = db.tickets.update_bereich(bereich, updated_by=user.username)
    if not ok:
        raise HTTPException(status_code=409, detail="Versionskonflikt – bitte Seite neu laden.")
    bereiche = db.tickets.get_bereiche()
    return asdict(next(b for b in bereiche if b.id == bereich_id))


@router.delete("/bereiche/{bereich_id}", status_code=204)
def delete_bereich(bereich_id: int, user: CurrentUser, db: DB):
    _require_admin(user)
    db.tickets.mark_bereich_deleted(bereich_id, deleted_by=user.username)


# ---------------------------------------------------------------------------
# Kategorien
# ---------------------------------------------------------------------------

@router.get("/kategorien")
def list_kategorien(user: CurrentUser, db: DB):
    return [asdict(k) for k in db.tickets.get_kategorien()]


@router.post("/kategorien", status_code=201)
def create_kategorie(data: KategorieWrite, user: CurrentUser, db: DB):
    _require_admin(user)
    kategorie = TicketKategorie(name=data.name, icon=data.icon)
    return asdict(db.tickets.create_kategorie(kategorie, created_by=user.username))


@router.put("/kategorien/{kategorie_id}")
def update_kategorie(kategorie_id: int, data: KategorieUpdate, user: CurrentUser, db: DB):
    _require_admin(user)
    kategorien = db.tickets.get_kategorien()
    kat = next((k for k in kategorien if k.id == kategorie_id), None)
    if not kat:
        raise HTTPException(status_code=404, detail=f"Kategorie {kategorie_id} nicht gefunden.")
    kat.name = data.name
    kat.icon = data.icon
    kat.version = data.expected_version
    ok = db.tickets.update_kategorie(kat, updated_by=user.username)
    if not ok:
        raise HTTPException(status_code=409, detail="Versionskonflikt – bitte Seite neu laden.")
    kategorien = db.tickets.get_kategorien()
    return asdict(next(k for k in kategorien if k.id == kategorie_id))


@router.delete("/kategorien/{kategorie_id}", status_code=204)
def delete_kategorie(kategorie_id: int, user: CurrentUser, db: DB):
    _require_admin(user)
    db.tickets.mark_kategorie_deleted(kategorie_id, deleted_by=user.username)


# ---------------------------------------------------------------------------
# Tickets
# ---------------------------------------------------------------------------

@router.get("/")
def list_tickets(
    user: CurrentUser,
    db: DB,
    bereich_id: Optional[int] = None,
    status: Optional[str] = None,
    zugewiesen_an: Optional[int] = None,
    gemeldet_von: Optional[int] = None,
):
    tickets = db.tickets.list_tickets_with_counts()

    # Bereichs-Filter
    if bereich_id is not None:
        tickets = [t for t in tickets if t.bereich_id == bereich_id]
    if status:
        tickets = [t for t in tickets if t.status == status]
    if zugewiesen_an is not None:
        tickets = [t for t in tickets if t.zugewiesen_an == zugewiesen_an]
    if gemeldet_von is not None:
        tickets = [t for t in tickets if t.gemeldet_von == gemeldet_von]

    # Sichtbarkeit: nur Tickets, auf die der User Lesezugriff hat
    if user.role != "admin":
        lesbare_ids = set(db.ticket_bereich_berechtigungen.get_lesbare_bereich_ids(user.id))
        tickets = [
            t for t in tickets
            if t.gemeldet_von == user.id
            or t.zugewiesen_an == user.id
            or t.bereich_id is None
            or t.bereich_id in lesbare_ids
        ]

    return [asdict(t) for t in tickets]


@router.post("/", status_code=201)
def create_ticket(data: TicketWrite, user: CurrentUser, db: DB):
    ticket = Ticket(
        titel=data.titel,
        beschreibung=data.beschreibung,
        prioritaet=data.prioritaet,
        bereich_id=data.bereich_id,
        kategorie_id=data.kategorie_id,
        gemeldet_von=user.id,
        zugewiesen_an=data.zugewiesen_an,
        faellig_am=data.faellig_am,
    )
    return asdict(db.tickets.create_ticket(ticket, created_by=user.username))


@router.get("/{ticket_id}")
def get_ticket(ticket_id: int, user: CurrentUser, db: DB):
    ticket = _get_ticket_or_404(ticket_id, db)
    if not _can_read(ticket, user, db):
        raise HTTPException(status_code=403, detail="Kein Lesezugriff auf dieses Ticket.")
    return asdict(ticket)


@router.put("/{ticket_id}")
def update_ticket(ticket_id: int, data: TicketUpdate, user: CurrentUser, db: DB):
    ticket = _get_ticket_or_404(ticket_id, db)
    if not _can_write(ticket, user, db):
        raise HTTPException(status_code=403, detail="Kein Schreibzugriff auf dieses Ticket.")
    ticket.titel = data.titel
    ticket.beschreibung = data.beschreibung
    ticket.prioritaet = data.prioritaet
    ticket.bereich_id = data.bereich_id
    ticket.kategorie_id = data.kategorie_id
    ticket.zugewiesen_an = data.zugewiesen_an
    ticket.faellig_am = data.faellig_am
    ticket.version = data.expected_version
    ok = db.tickets.update_ticket(ticket, updated_by=user.username)
    if not ok:
        raise HTTPException(status_code=409, detail="Versionskonflikt – bitte Seite neu laden.")
    return asdict(_get_ticket_or_404(ticket_id, db))


@router.patch("/{ticket_id}/status")
def change_status(ticket_id: int, data: StatusChange, user: CurrentUser, db: DB):
    ticket = _get_ticket_or_404(ticket_id, db)
    if not _can_write(ticket, user, db):
        raise HTTPException(status_code=403, detail="Kein Schreibzugriff auf dieses Ticket.")
    if data.status in TicketStatus.ABGESCHLOSSEN and not _can_close(ticket, user, db):
        raise HTTPException(status_code=403, detail="Kein Recht zum Abschließen dieses Tickets.")
    try:
        ok = db.tickets.change_status(ticket_id, data.status, changed_by=user.username, version=data.expected_version)
    except UngueltigerStatusWechselError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not ok:
        raise HTTPException(status_code=409, detail="Versionskonflikt – bitte Seite neu laden.")
    return asdict(_get_ticket_or_404(ticket_id, db))


@router.delete("/{ticket_id}", status_code=204)
def delete_ticket(ticket_id: int, user: CurrentUser, db: DB):
    ticket = _get_ticket_or_404(ticket_id, db)
    if not _can_write(ticket, user, db):
        raise HTTPException(status_code=403, detail="Kein Schreibzugriff auf dieses Ticket.")
    db.tickets.mark_ticket_deleted(ticket_id, deleted_by=user.username)


# ---------------------------------------------------------------------------
# Anhänge
# ---------------------------------------------------------------------------

@router.get("/{ticket_id}/anhaenge")
def list_anhaenge(ticket_id: int, user: CurrentUser, db: DB):
    ticket = _get_ticket_or_404(ticket_id, db)
    if not _can_read(ticket, user, db):
        raise HTTPException(status_code=403, detail="Kein Lesezugriff auf dieses Ticket.")
    return [asdict(a) for a in db.tickets.get_anhaenge(ticket_id)]


@router.post("/{ticket_id}/anhaenge", status_code=201)
async def upload_anhang(
    ticket_id: int,
    user: CurrentUser,
    db: DB,
    file: UploadFile = File(...),
):
    ticket = _get_ticket_or_404(ticket_id, db)
    if not _can_write(ticket, user, db):
        raise HTTPException(status_code=403, detail="Kein Schreibzugriff auf dieses Ticket.")

    inhalt = await file.read()
    try:
        anhang = db.tickets.add_anhang(
            ticket_id=ticket_id,
            kommentar_id=None,
            original_name=file.filename or "upload",
            mime_type=file.content_type or "application/octet-stream",
            inhalt=inhalt,
            hochgeladen_von=user.id,
        )
    except DateitypNichtErlaubtError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except DateiZuGrossError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except IOError as exc:
        raise HTTPException(status_code=500, detail=f"Fehler beim Speichern: {exc}")
    return asdict(anhang)


@router.delete("/{ticket_id}/anhaenge/{anhang_id}", status_code=204)
def delete_anhang(ticket_id: int, anhang_id: int, user: CurrentUser, db: DB):
    ticket = _get_ticket_or_404(ticket_id, db)
    if not _can_write(ticket, user, db):
        raise HTTPException(status_code=403, detail="Kein Schreibzugriff auf dieses Ticket.")
    ok = db.tickets.mark_anhang_deleted(anhang_id, deleted_by=user.username)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Anhang {anhang_id} nicht gefunden.")


# ---------------------------------------------------------------------------
# Kommentare
# ---------------------------------------------------------------------------

def _enrich_kommentar(k: TicketKommentar, db) -> dict:
    d = asdict(k)
    author = db.get_user_by_id(k.autor_id) if k.autor_id else None
    d['autor_username'] = author.username if author else f'User {k.autor_id}'
    return d


@router.get("/{ticket_id}/kommentare")
def list_kommentare(ticket_id: int, user: CurrentUser, db: DB):
    ticket = _get_ticket_or_404(ticket_id, db)
    if not _can_read(ticket, user, db):
        raise HTTPException(status_code=403, detail="Kein Lesezugriff auf dieses Ticket.")
    include_internal = user.role == "admin" or _can_write(ticket, user, db)
    kommentare = db.tickets.get_kommentare(ticket_id, include_internal=include_internal)
    return [_enrich_kommentar(k, db) for k in kommentare]


@router.post("/{ticket_id}/kommentare", status_code=201)
def create_kommentar(ticket_id: int, data: KommentarWrite, user: CurrentUser, db: DB):
    ticket = _get_ticket_or_404(ticket_id, db)
    if not _can_read(ticket, user, db):
        raise HTTPException(status_code=403, detail="Kein Zugriff auf dieses Ticket.")
    kommentar = TicketKommentar(
        ticket_id=ticket_id,
        autor_id=user.id,
        inhalt=data.inhalt,
        sichtbarkeit=data.sichtbarkeit,
    )
    created = db.tickets.add_kommentar(kommentar, created_by=user.username)
    return _enrich_kommentar(created, db)


@router.delete("/{ticket_id}/kommentare/{kommentar_id}", status_code=204)
def delete_kommentar(ticket_id: int, kommentar_id: int, user: CurrentUser, db: DB):
    kommentar = db.tickets._kommentar_repo.get(kommentar_id)
    if not kommentar or kommentar.ticket_id != ticket_id:
        raise HTTPException(status_code=404, detail="Kommentar nicht gefunden.")
    if kommentar.autor_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Nur eigene Kommentare können gelöscht werden.")
    db.tickets.mark_kommentar_deleted(kommentar_id, deleted_by=user.username)
