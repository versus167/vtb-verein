"""Passwort-Tresor (#85).

Zugriffsmodell (analog Kassen): der Lese-/Schreibzugriff auf einen Tresor ergibt sich aus
tresor_freigabe (Freigabe an User/Abteilung/Funktion), NICHT aus globalen Rechten. Nur das
Verwalten – Tresore anlegen/ändern/löschen, Freigaben pflegen, alle Tresore sehen – hängt am
globalen Recht `tresor.verwalten`; Admins dürfen ohnehin alles.

Secrets werden nur verschlüsselt gespeichert (core.vault_crypto). Fehlt der Schlüssel
(VTB_VAULT_KEY), sind die schreibenden Pfade und das Enthüllen mit 503 gesperrt; reine
Metadaten (Liste/Titel) bleiben lesbar. Jedes Enthüllen wird in tresor_zugriff_log auditiert.
"""
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from app.models.permission import Permission
from ..core.deps import CurrentUser, DB
from ..core import vault_crypto

router = APIRouter(prefix="/tresor", tags=["tresor"])


# --------------------------------------------------------------------------- I/O
class TresorCreate(BaseModel):
    name: str
    beschreibung: Optional[str] = None


class TresorUpdate(BaseModel):
    name: str
    beschreibung: Optional[str] = None
    expected_version: int


class EintragCreate(BaseModel):
    titel: str
    benutzername: Optional[str] = None
    url: Optional[str] = None
    passwort: str = ""
    notiz: str = ""


class EintragUpdate(BaseModel):
    titel: str
    benutzername: Optional[str] = None
    url: Optional[str] = None
    # passwort/notiz nur setzen, wenn passwort_aendern=True (sonst bleibt der Ciphertext).
    passwort_aendern: bool = False
    passwort: str = ""
    notiz: str = ""
    expected_version: int


class FreigabeWrite(BaseModel):
    principal_typ: str   # 'user' | 'abteilung' | 'funktion'
    principal_id: int
    zugriff: str = 'read'  # 'read' | 'write'


# ----------------------------------------------------------------- Authorisierung
def _darf_verwalten(user) -> bool:
    return user.role == 'admin' or user.has_permission(Permission.TRESOR_VERWALTEN)


def _zugriff(db: DB, user, tresor_id: int) -> Optional[str]:
    """Effektive Stufe auf einen Tresor: 'write' | 'read' | None. Verwalten/Admin => 'write'."""
    if _darf_verwalten(user):
        return 'write'
    return db.tresore.get_access_for_user(user.id, tresor_id)


def _require_verwalten(user) -> None:
    if not _darf_verwalten(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Keine Berechtigung zur Tresor-Verwaltung")


def _require_read(db: DB, user, tresor_id: int) -> str:
    z = _zugriff(db, user, tresor_id)
    if z is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Kein Zugriff auf diesen Tresor")
    return z


def _require_write(db: DB, user, tresor_id: int) -> None:
    if _zugriff(db, user, tresor_id) != 'write':
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Kein Schreibzugriff auf diesen Tresor")


def _require_vault() -> None:
    if not vault_crypto.is_configured():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Tresor ist nicht konfiguriert (VTB_VAULT_KEY fehlt).",
        )


def _principal_exists(db: DB, typ: str, pid: int) -> bool:
    if typ == 'user':
        return db.users.get_by_id(pid) is not None
    if typ == 'funktion':
        return db.funktionen.get(pid) is not None
    if typ == 'abteilung':
        try:
            return db.get_abteilung(pid) is not None
        except KeyError:
            return False
    return False


def _client_ip(request: Request) -> Optional[str]:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


# ----------------------------------------------------------------------- Status
@router.get("/status")
def status_info(user: CurrentUser):
    """Ob der Tresor serverseitig einsatzbereit ist und ob der User verwalten darf."""
    return {"konfiguriert": vault_crypto.is_configured(), "darf_verwalten": _darf_verwalten(user)}


# ----------------------------------------------------------------------- Tresore
@router.get("")
def list_tresore(user: CurrentUser, db: DB):
    """Für Verwalter alle Tresore, sonst nur die per Freigabe zugänglichen."""
    if _darf_verwalten(user):
        return db.tresore.list_all()
    return db.tresore.list_for_user(user.id)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_tresor(data: TresorCreate, user: CurrentUser, db: DB):
    _require_verwalten(user)
    if not data.name.strip():
        raise HTTPException(422, "Name darf nicht leer sein")
    t = db.tresore.create(data.name.strip(), (data.beschreibung or '').strip() or None, user.username)
    return asdict(t)


@router.put("/{tresor_id}")
def update_tresor(tresor_id: int, data: TresorUpdate, user: CurrentUser, db: DB):
    _require_verwalten(user)
    if not data.name.strip():
        raise HTTPException(422, "Name darf nicht leer sein")
    if db.tresore.get(tresor_id) is None:
        raise HTTPException(404, "Tresor nicht gefunden")
    ok = db.tresore.update(tresor_id, data.name.strip(),
                           (data.beschreibung or '').strip() or None,
                           user.username, data.expected_version)
    if not ok:
        raise HTTPException(409, "Versionskonflikt – bitte Seite neu laden")
    return asdict(db.tresore.get(tresor_id))


@router.delete("/{tresor_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tresor(tresor_id: int, user: CurrentUser, db: DB):
    _require_verwalten(user)
    if db.tresore.get(tresor_id) is None:
        raise HTTPException(404, "Tresor nicht gefunden")
    # Einträge und Freigaben mit soft-deleten (Soft-Delete-Prinzip; Prune räumt später auf).
    for e in db.tresor_eintraege.list_for_tresor(tresor_id):
        db.tresor_eintraege.mark_deleted(e.id, user.username)
    db.tresor_freigaben.revoke_alle_freigaben_fuer_tresor(tresor_id, user.username)
    db.tresore.mark_deleted(tresor_id, user.username)


# ------------------------------------------------------------------- Einträge
@router.get("/{tresor_id}/eintraege")
def list_eintraege(tresor_id: int, user: CurrentUser, db: DB):
    if db.tresore.get(tresor_id) is None:
        raise HTTPException(404, "Tresor nicht gefunden")
    zugriff = _require_read(db, user, tresor_id)
    return {
        "darf_schreiben": zugriff == 'write',
        "konfiguriert": vault_crypto.is_configured(),
        "eintraege": [asdict(e) for e in db.tresor_eintraege.list_for_tresor(tresor_id)],
    }


@router.post("/{tresor_id}/eintraege", status_code=status.HTTP_201_CREATED)
def create_eintrag(tresor_id: int, data: EintragCreate, user: CurrentUser, db: DB):
    if db.tresore.get(tresor_id) is None:
        raise HTTPException(404, "Tresor nicht gefunden")
    _require_write(db, user, tresor_id)
    _require_vault()
    if not data.titel.strip():
        raise HTTPException(422, "Titel darf nicht leer sein")
    ct = vault_crypto.encrypt_secret(data.passwort, data.notiz)
    e = db.tresor_eintraege.create(
        tresor_id, data.titel.strip(),
        (data.benutzername or '').strip() or None,
        (data.url or '').strip() or None, ct, user.username,
    )
    return asdict(e)


@router.put("/eintraege/{eintrag_id}")
def update_eintrag(eintrag_id: int, data: EintragUpdate, user: CurrentUser, db: DB):
    e = db.tresor_eintraege.get(eintrag_id)
    if e is None:
        raise HTTPException(404, "Eintrag nicht gefunden")
    _require_write(db, user, e.tresor_id)
    if not data.titel.strip():
        raise HTTPException(422, "Titel darf nicht leer sein")
    ct = None
    if data.passwort_aendern:
        _require_vault()
        ct = vault_crypto.encrypt_secret(data.passwort, data.notiz)
    ok = db.tresor_eintraege.update(
        eintrag_id, data.titel.strip(),
        (data.benutzername or '').strip() or None,
        (data.url or '').strip() or None, ct, user.username, data.expected_version,
    )
    if not ok:
        raise HTTPException(409, "Versionskonflikt – bitte Seite neu laden")
    return asdict(db.tresor_eintraege.get(eintrag_id))


@router.delete("/eintraege/{eintrag_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_eintrag(eintrag_id: int, user: CurrentUser, db: DB):
    e = db.tresor_eintraege.get(eintrag_id)
    if e is None:
        raise HTTPException(404, "Eintrag nicht gefunden")
    _require_write(db, user, e.tresor_id)
    db.tresor_eintraege.mark_deleted(eintrag_id, user.username)


@router.get("/eintraege/{eintrag_id}/reveal")
def reveal_eintrag(eintrag_id: int, request: Request, user: CurrentUser, db: DB):
    """Entschlüsselt Passwort + geheime Notiz eines Eintrags – Lesezugriff nötig, wird auditiert."""
    e = db.tresor_eintraege.get(eintrag_id)
    if e is None:
        raise HTTPException(404, "Eintrag nicht gefunden")
    _require_read(db, user, e.tresor_id)
    _require_vault()
    ct = db.tresor_eintraege.get_ciphertext(eintrag_id)
    if ct is None:
        raise HTTPException(404, "Eintrag nicht gefunden")
    try:
        secret = vault_crypto.decrypt_secret(ct)
    except vault_crypto.VaultDecryptError:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Passwort ließ sich nicht entschlüsseln (Schlüssel geändert?).",
        )
    db.tresor_zugriff_log.log(
        tresor_id=e.tresor_id, eintrag_id=e.id, eintrag_titel=e.titel,
        user_id=user.id, username=user.username, aktion='reveal', ip=_client_ip(request),
    )
    return {
        "id": e.id, "titel": e.titel, "benutzername": e.benutzername, "url": e.url,
        "passwort": secret["passwort"], "notiz": secret["notiz"],
    }


# ------------------------------------------------------------- Änderungsverlauf
class VerlaufRestore(BaseModel):
    expected_version: int


@router.get("/eintraege/{eintrag_id}/verlauf")
def eintrag_verlauf(eintrag_id: int, user: CurrentUser, db: DB):
    """Versions-Verlauf eines Eintrags: wer hat wann geändert. Schreibzugriff nötig – das
    Passwort steht hier NICHT drin (dafür /verlauf/{version}/reveal). Jede Zeile ist der
    Zustand einer Version aus tresor_eintrag_history (Audit-Trigger je version-Bump)."""
    e = db.tresor_eintraege.get(eintrag_id)
    if e is None:
        raise HTTPException(404, "Eintrag nicht gefunden")
    _require_write(db, user, e.tresor_id)
    verlauf = db.tresor_eintraege.list_history(eintrag_id)
    for v in verlauf:
        v["aktuell"] = v["version"] == e.version
    return {"aktuelle_version": e.version, "verlauf": verlauf}


@router.get("/eintraege/{eintrag_id}/verlauf/{version}/reveal")
def reveal_verlauf(eintrag_id: int, version: int, request: Request, user: CurrentUser, db: DB):
    """Enthüllt Passwort + Notiz einer FRÜHEREN Version – Schreibzugriff nötig, wird auditiert."""
    e = db.tresor_eintraege.get(eintrag_id)
    if e is None:
        raise HTTPException(404, "Eintrag nicht gefunden")
    _require_write(db, user, e.tresor_id)
    _require_vault()
    ct = db.tresor_eintraege.get_history_ciphertext(eintrag_id, version)
    if ct is None:
        raise HTTPException(404, "Version nicht gefunden")
    try:
        secret = vault_crypto.decrypt_secret(ct)
    except vault_crypto.VaultDecryptError:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Passwort ließ sich nicht entschlüsseln (Schlüssel geändert?).",
        )
    db.tresor_zugriff_log.log(
        tresor_id=e.tresor_id, eintrag_id=e.id, eintrag_titel=e.titel,
        user_id=user.id, username=user.username, aktion='reveal_verlauf', ip=_client_ip(request),
    )
    return {"version": version, "passwort": secret["passwort"], "notiz": secret["notiz"]}


@router.post("/eintraege/{eintrag_id}/verlauf/{version}/wiederherstellen")
def restore_verlauf(eintrag_id: int, version: int, data: VerlaufRestore,
                    request: Request, user: CurrentUser, db: DB):
    """Stellt Passwort + Notiz einer früheren Version wieder her: deren Ciphertext wird als
    NEUE Version übernommen (nichts geht verloren, selbst wieder rücknehmbar). Titel/Benutzer/
    URL bleiben unverändert. Schreibzugriff nötig, wird auditiert."""
    e = db.tresor_eintraege.get(eintrag_id)
    if e is None:
        raise HTTPException(404, "Eintrag nicht gefunden")
    _require_write(db, user, e.tresor_id)
    _require_vault()
    if version == e.version:
        raise HTTPException(422, "Diese Version ist bereits der aktuelle Stand.")
    ct = db.tresor_eintraege.get_history_ciphertext(eintrag_id, version)
    if ct is None:
        raise HTTPException(404, "Version nicht gefunden")
    ok = db.tresor_eintraege.update(
        eintrag_id, e.titel, e.benutzername, e.url, ct, user.username, data.expected_version,
    )
    if not ok:
        raise HTTPException(409, "Versionskonflikt – bitte Seite neu laden")
    db.tresor_zugriff_log.log(
        tresor_id=e.tresor_id, eintrag_id=e.id, eintrag_titel=e.titel,
        user_id=user.id, username=user.username, aktion='wiederhergestellt', ip=_client_ip(request),
    )
    return asdict(db.tresor_eintraege.get(eintrag_id))


# ------------------------------------------------------------------- Freigaben
@router.get("/{tresor_id}/freigaben")
def list_freigaben(tresor_id: int, user: CurrentUser, db: DB):
    _require_verwalten(user)
    if db.tresore.get(tresor_id) is None:
        raise HTTPException(404, "Tresor nicht gefunden")
    return [asdict(f) for f in db.tresor_freigaben.list_for_tresor(tresor_id)]


@router.get("/principals")
def list_principals(user: CurrentUser, db: DB):
    """Auswahllisten für den Freigabe-Dialog (User/Abteilung/Funktion) – nur für Verwalter.
    Bewusst hier gebündelt, damit die Verwaltung nicht an personen.-/abteilungen.-Rechte koppelt."""
    _require_verwalten(user)
    users = [{"id": u.id, "name": u.username}
             for u in db.list_users() if getattr(u, 'active', True)]
    abteilungen = [{"id": a.id, "name": a.name} for a in db.list_abteilungen()]
    funktionen = [{"id": f.id, "name": f.name} for f in db.funktionen.list_all()]
    return {"users": users, "abteilungen": abteilungen, "funktionen": funktionen}


@router.put("/{tresor_id}/freigaben")
def set_freigabe(tresor_id: int, data: FreigabeWrite, user: CurrentUser, db: DB):
    _require_verwalten(user)
    if db.tresore.get(tresor_id) is None:
        raise HTTPException(404, "Tresor nicht gefunden")
    if data.principal_typ not in ('user', 'abteilung', 'funktion'):
        raise HTTPException(422, "principal_typ muss user, abteilung oder funktion sein")
    if data.zugriff not in ('read', 'write'):
        raise HTTPException(422, "zugriff muss read oder write sein")
    # Principal muss existieren
    if not _principal_exists(db, data.principal_typ, data.principal_id):
        raise HTTPException(404, f"{data.principal_typ} #{data.principal_id} nicht gefunden")
    f = db.tresor_freigaben.set_freigabe(
        tresor_id, data.principal_typ, data.principal_id, data.zugriff, user.username,
    )
    return asdict(f)


@router.delete("/{tresor_id}/freigaben/{principal_typ}/{principal_id}",
               status_code=status.HTTP_204_NO_CONTENT)
def revoke_freigabe(tresor_id: int, principal_typ: str, principal_id: int,
                    user: CurrentUser, db: DB):
    _require_verwalten(user)
    if not db.tresor_freigaben.revoke(tresor_id, principal_typ, principal_id, user.username):
        raise HTTPException(404, "Freigabe nicht gefunden")


# ------------------------------------------------------------------- Zugriffslog
@router.get("/{tresor_id}/zugriffe")
def list_zugriffe(tresor_id: int, user: CurrentUser, db: DB):
    """Wer hat wann welchen Eintrag dieses Tresors enthüllt? Nur für Verwalter."""
    _require_verwalten(user)
    if db.tresore.get(tresor_id) is None:
        raise HTTPException(404, "Tresor nicht gefunden")
    return [asdict(z) for z in db.tresor_zugriff_log.list_recent(limit=200, tresor_id=tresor_id)]
