"""
Ticket API – Tickets, Bereiche, Kategorien, Anhänge.

Berechtigungsmodell:
  - Admins: voller Zugriff auf alles
  - Normale User:
      - Lesen:      darf_lesen auf den Bereich des Tickets  (oder eigene Tickets)
      - Schreiben:  darf_bearbeiten auf den Bereich
      - Abschließen: darf_schliessen auf den Bereich
      - Bereiche/Kategorien verwalten: Permission tickets.bereiche_verwalten
      - Fremde Kommentare löschen: Permission tickets.delete
"""

from dataclasses import asdict
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel
from typing import Optional

from backend.core.deps import CurrentUser, DB
from app.models.permission import Permission
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
    faellig_am: Optional[str] = None


class TicketUpdate(TicketWrite):
    expected_version: int
    notify_as_new: bool = False


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


class BereichBerechtigungWrite(BaseModel):
    darf_lesen: bool = False
    darf_bearbeiten: bool = False
    darf_schliessen: bool = False


class KategorieWrite(BaseModel):
    name: str
    icon: Optional[str] = None


class KategorieUpdate(KategorieWrite):
    expected_version: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_bereiche_verwalten(user) -> None:
    # Bereiche UND Kategorien verwalten (seit Stufe D, vorher hart Admin-only).
    if not user.has_permission(Permission.TICKETS_BEREICHE_VERWALTEN):
        raise HTTPException(status_code=403, detail="Keine Berechtigung zur Bereichsverwaltung.")


def _can_read(ticket: Ticket, user, db) -> bool:
    return True


def _can_write(ticket: Ticket, user, db) -> bool:
    if user.role == "admin":
        return True
    if ticket.gemeldet_von == user.id or ticket.zugewiesen_an == user.id:
        return True
    if ticket.bereich_id is None:
        return False
    return db.ticket_bereich_berechtigungen.user_darf_bearbeiten(ticket.bereich_id, user.id)


def _can_change_status(ticket: Ticket, user, db) -> bool:
    if user.role == "admin":
        return True
    if ticket.bereich_id is None:
        return False
    return db.ticket_bereich_berechtigungen.user_darf_bearbeiten(ticket.bereich_id, user.id)


def _can_close(ticket: Ticket, user, db) -> bool:
    if user.role == "admin":
        return True
    if ticket.bereich_id is None:
        return False
    return db.ticket_bereich_berechtigungen.user_darf_schliessen(ticket.bereich_id, user.id)


def _can_verwalten(ticket: Ticket, user, db) -> bool:
    """Verwalter eines Bereichs: Admin oder darf_bearbeiten. Darf Tickets verbergen
    (smart löschen), gelöschte einsehen und wiederherstellen."""
    if user.role == "admin":
        return True
    if ticket.bereich_id is None:
        return False
    return db.ticket_bereich_berechtigungen.user_darf_bearbeiten(ticket.bereich_id, user.id)


def _enrich(ticket_dict: dict, db) -> dict:
    """Fügt gemeldet_von_username und bereich_name hinzu.

    Nutzt bewusst schlanke Lookups (get_username / get_bereich statt get_user_by_id /
    get_bereiche), damit ein einzelnes Ticket nicht den kompletten Effektiv-Rechte-
    Fanout des Melders und alle Bereiche lädt (siehe Ticket-Performance).
    """
    gemeldet_von = ticket_dict.get('gemeldet_von')
    username = db.get_username(gemeldet_von) if gemeldet_von else None
    ticket_dict['gemeldet_von_username'] = username or f'#{gemeldet_von}'
    bereich_id = ticket_dict.get('bereich_id')
    if bereich_id:
        b = db.tickets.get_bereich(bereich_id)
        ticket_dict['bereich_name'] = b.name if b else None
    else:
        ticket_dict['bereich_name'] = None
    return ticket_dict


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
    _require_bereiche_verwalten(user)
    bereich = TicketBereich(name=data.name, beschreibung=data.beschreibung)
    return asdict(db.tickets.create_bereich(bereich, created_by=user.username))


@router.put("/bereiche/{bereich_id}")
def update_bereich(bereich_id: int, data: BereichUpdate, user: CurrentUser, db: DB):
    _require_bereiche_verwalten(user)
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
    _require_bereiche_verwalten(user)
    with db.tickets._ticket_repo.conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) FROM tickets
            WHERE bereich_id = %s AND deleted_at IS NULL
              AND status NOT IN ('erledigt', 'abgelehnt')
            """,
            (bereich_id,),
        )
        anzahl = cur.fetchone()["count"]
    if anzahl > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Bereich enthält noch {anzahl} offene{'s' if anzahl == 1 else ''} Ticket{'s' if anzahl != 1 else ''}. Bitte zuerst abschließen oder einem anderen Bereich zuweisen.",
        )
    db.tickets.mark_bereich_deleted(bereich_id, deleted_by=user.username)


@router.get("/bereiche/{bereich_id}/berechtigungen")
def list_bereich_berechtigungen(bereich_id: int, user: CurrentUser, db: DB):
    """User mit bestehender Berechtigung für diesen Bereich."""
    _require_bereiche_verwalten(user)
    eintraege = db.ticket_bereich_berechtigungen.list_berechtigungen_fuer_bereich(bereich_id)
    return [
        {
            "user_id":         e["user_id"],
            "username":        e["username"],
            "darf_lesen":      bool(e["darf_lesen"]),
            "darf_bearbeiten": bool(e["darf_bearbeiten"]),
            "darf_schliessen": bool(e["darf_schliessen"]),
        }
        for e in eintraege
        if e["darf_lesen"] or e["darf_bearbeiten"] or e["darf_schliessen"]
    ]


@router.get("/bereiche/{bereich_id}/berechtigungen/verfuegbare-user")
def list_verfuegbare_user(bereich_id: int, user: CurrentUser, db: DB):
    """Aktive Nicht-Admin-User ohne bestehende Berechtigung für diesen Bereich."""
    _require_bereiche_verwalten(user)
    from app.services.user_service import UserService
    bereits = {e["user_id"] for e in db.ticket_bereich_berechtigungen.list_berechtigungen_fuer_bereich(bereich_id)}
    return [
        {"id": u.id, "username": u.username}
        for u in UserService(db).list_all()
        if u.role != "admin" and u.active and u.id not in bereits
    ]


@router.put("/bereiche/{bereich_id}/berechtigungen/{user_id}", status_code=200)
def set_bereich_berechtigung(
    bereich_id: int, user_id: int, data: BereichBerechtigungWrite,
    user: CurrentUser, db: DB,
):
    _require_bereiche_verwalten(user)
    # Kaskade: schliessen → bearbeiten → lesen
    lesen     = data.darf_lesen or data.darf_bearbeiten or data.darf_schliessen
    bearbeiten= data.darf_bearbeiten or data.darf_schliessen
    schliessen= data.darf_schliessen
    db.ticket_bereich_berechtigungen.set_berechtigung(
        bereich_id=bereich_id,
        user_id=user_id,
        darf_lesen=lesen,
        darf_bearbeiten=bearbeiten,
        darf_schliessen=schliessen,
        by=user.username,
    )
    return {"darf_lesen": lesen, "darf_bearbeiten": bearbeiten, "darf_schliessen": schliessen}


@router.get("/meine-berechtigungen")
def meine_berechtigungen(user: CurrentUser, db: DB):
    """Eigene Bereich-Berechtigungen des eingeloggten Users."""
    if user.role == "admin":
        return {"ist_admin": True, "bereiche": {}}
    eintraege = db.ticket_bereich_berechtigungen.list_berechtigungen_fuer_user(user.id)
    return {
        "ist_admin": False,
        "bereiche": {
            str(e["bereich_id"]): {
                "darf_lesen":      bool(e["darf_lesen"]),
                "darf_bearbeiten": bool(e["darf_bearbeiten"]),
                "darf_schliessen": bool(e["darf_schliessen"]),
            }
            for e in eintraege
        },
    }


# ---------------------------------------------------------------------------
# Kategorien
# ---------------------------------------------------------------------------

@router.get("/kategorien")
def list_kategorien(user: CurrentUser, db: DB):
    return [asdict(k) for k in db.tickets.get_kategorien()]


@router.post("/kategorien", status_code=201)
def create_kategorie(data: KategorieWrite, user: CurrentUser, db: DB):
    _require_bereiche_verwalten(user)
    kategorie = TicketKategorie(name=data.name, icon=data.icon)
    return asdict(db.tickets.create_kategorie(kategorie, created_by=user.username))


@router.put("/kategorien/{kategorie_id}")
def update_kategorie(kategorie_id: int, data: KategorieUpdate, user: CurrentUser, db: DB):
    _require_bereiche_verwalten(user)
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
    _require_bereiche_verwalten(user)
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
    gemeldet_von: Optional[int] = None,
    nur_geloeschte: bool = False,
):
    if nur_geloeschte:
        # "Einblenden": gelöschte Tickets nur für Verwalter. Admin sieht alle,
        # sonst nur gelöschte aus Bereichen mit darf_bearbeiten.
        tickets = db.tickets.list_tickets_with_counts(nur_geloeschte=True)
        if user.role != "admin":
            verwaltbare = {
                e["bereich_id"]
                for e in db.ticket_bereich_berechtigungen.list_berechtigungen_fuer_user(user.id)
                if e["darf_bearbeiten"]
            }
            tickets = [t for t in tickets if t.bereich_id in verwaltbare]
    else:
        tickets = db.tickets.list_tickets_with_counts()

    # Bereichs-Filter
    if bereich_id is not None:
        tickets = [t for t in tickets if t.bereich_id == bereich_id]
    if status:
        tickets = [t for t in tickets if t.status == status]
    if gemeldet_von is not None:
        tickets = [t for t in tickets if t.gemeldet_von == gemeldet_von]


    from app.services.user_service import UserService
    user_lookup = {u.id: u.username for u in UserService(db).list_all()}
    bereiche_lookup = {b.id: b.name for b in db.tickets.get_bereiche()}

    result = []
    for t in tickets:
        d = asdict(t)
        d['gemeldet_von_username'] = user_lookup.get(t.gemeldet_von, f'#{t.gemeldet_von}')
        d['bereich_name'] = bereiche_lookup.get(t.bereich_id) if t.bereich_id else None
        result.append(d)
    return result


@router.post("/", status_code=201)
def create_ticket(data: TicketWrite, user: CurrentUser, db: DB, draft: bool = False):
    if not data.bereich_id:
        raise HTTPException(status_code=422, detail="Bereich ist ein Pflichtfeld.")
    ticket = Ticket(
        titel=data.titel,
        beschreibung=data.beschreibung,
        prioritaet=data.prioritaet,
        bereich_id=data.bereich_id,
        kategorie_id=data.kategorie_id,
        gemeldet_von=user.id,
        faellig_am=data.faellig_am,
    )
    created = db.tickets.create_ticket(ticket, created_by=user.username, notify=not draft)
    return _enrich(asdict(created), db)


@router.get("/{ticket_id}")
def get_ticket(ticket_id: int, user: CurrentUser, db: DB):
    ticket = _get_ticket_or_404(ticket_id, db)
    if not _can_read(ticket, user, db):
        raise HTTPException(status_code=403, detail="Kein Lesezugriff auf dieses Ticket.")
    return _enrich(asdict(ticket), db)


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
    ticket.faellig_am = data.faellig_am
    ticket.version = data.expected_version
    ok = db.tickets.update_ticket(ticket, updated_by=user.username, notify_as_new=data.notify_as_new)
    if not ok:
        raise HTTPException(status_code=409, detail="Versionskonflikt – bitte Seite neu laden.")
    return _enrich(asdict(_get_ticket_or_404(ticket_id, db)), db)


@router.patch("/{ticket_id}/status")
def change_status(ticket_id: int, data: StatusChange, user: CurrentUser, db: DB):
    ticket = _get_ticket_or_404(ticket_id, db)
    if not _can_change_status(ticket, user, db):
        raise HTTPException(status_code=403, detail="Kein Recht zum Ändern des Status.")
    if data.status in TicketStatus.ABGESCHLOSSEN and not _can_close(ticket, user, db):
        raise HTTPException(status_code=403, detail="Kein Recht zum Abschließen dieses Tickets.")
    try:
        ok = db.tickets.change_status(ticket, data.status, changed_by=user.username, version=data.expected_version)
    except UngueltigerStatusWechselError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not ok:
        raise HTTPException(status_code=409, detail="Versionskonflikt – bitte Seite neu laden.")
    return _enrich(asdict(_get_ticket_or_404(ticket_id, db)), db)


@router.delete("/{ticket_id}", status_code=204)
def delete_ticket(ticket_id: int, user: CurrentUser, db: DB):
    """Soft-Delete: Verwalter (Admin/Bereichs-Bearbeiter) verbergen beliebige Tickets,
    der Melder darf sein eigenes Ticket zurückziehen."""
    ticket = _get_ticket_or_404(ticket_id, db)
    if not _can_verwalten(ticket, user, db) and ticket.gemeldet_von != user.id:
        raise HTTPException(status_code=403, detail="Kein Recht, dieses Ticket zu verbergen.")
    db.tickets.mark_ticket_deleted(ticket_id, deleted_by=user.username)


@router.post("/{ticket_id}/restore")
def restore_ticket(ticket_id: int, user: CurrentUser, db: DB):
    """Hebt einen Soft-Delete wieder auf – nur Verwalter (Admin/Bereichs-Bearbeiter)."""
    ticket = _get_ticket_or_404(ticket_id, db)
    if not _can_verwalten(ticket, user, db):
        raise HTTPException(status_code=403, detail="Kein Recht, dieses Ticket wiederherzustellen.")
    ok = db.tickets.restore_ticket(ticket_id, restored_by=user.username)
    if not ok:
        raise HTTPException(status_code=409, detail="Ticket ist nicht gelöscht oder bereits wiederhergestellt.")
    return _enrich(asdict(_get_ticket_or_404(ticket_id, db)), db)


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
    # Schlanker Namens-Lookup (get_username statt get_user_by_id) – wird pro Kommentar
    # einer Liste aufgerufen, deshalb kein Effektiv-Rechte-Fanout je Autor.
    username = db.get_username(k.autor_id) if k.autor_id else None
    d['autor_username'] = username or f'User {k.autor_id}'
    return d


@router.get("/{ticket_id}/kommentare")
def list_kommentare(ticket_id: int, user: CurrentUser, db: DB):
    ticket = _get_ticket_or_404(ticket_id, db)
    if not _can_read(ticket, user, db):
        raise HTTPException(status_code=403, detail="Kein Lesezugriff auf dieses Ticket.")
    include_internal = user.role == "admin" or _can_change_status(ticket, user, db)
    kommentare = db.tickets.get_kommentare(ticket_id, include_internal=include_internal)
    return [_enrich_kommentar(k, db) for k in kommentare]


@router.post("/{ticket_id}/kommentare", status_code=201)
def create_kommentar(ticket_id: int, data: KommentarWrite, user: CurrentUser, db: DB):
    ticket = _get_ticket_or_404(ticket_id, db)
    if ticket.status in ('erledigt', 'abgelehnt'):
        raise HTTPException(status_code=403, detail="Kommentare zu abgeschlossenen Tickets sind nicht möglich.")
    if data.sichtbarkeit == 'intern' and not _can_change_status(ticket, user, db):
        raise HTTPException(status_code=403, detail="Interne Kommentare erfordern Bearbeitungsrecht für diesen Bereich.")
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
    if kommentar.autor_id != user.id and not user.has_permission(Permission.TICKETS_DELETE):
        raise HTTPException(status_code=403, detail="Nur eigene Kommentare können gelöscht werden.")
    db.tickets.mark_kommentar_deleted(kommentar_id, deleted_by=user.username)
