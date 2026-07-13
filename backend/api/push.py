"""
Web-Push-Endpunkte (Ticket #96).

Jeder Nutzer verwaltet ausschließlich die Push-Subscriptions seiner eigenen
Geräte – es gibt kein globales Recht dafür. Der Versand selbst läuft über den
NotificationService (bevorzugter Kanal 'push'); hier nur VAPID-Key ausliefern
sowie Geräte an-/abmelden.
"""
from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..core.deps import CurrentUser, DB

router = APIRouter(prefix="/push", tags=["push"])


class PushKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscription(BaseModel):
    endpoint: str
    keys: PushKeys


class PushUnsubscribe(BaseModel):
    endpoint: str


@router.get("/vapid-key")
def get_vapid_key(user: CurrentUser, db: DB):
    """Öffentlicher VAPID-Key + ob der Nutzer auf einem Gerät bereits abonniert hat."""
    return {
        "publicKey": db.push.public_key(),
        "configured": db.push.is_configured(),
        "subscribed": db.push.has_active(user.id),
    }


@router.post("/subscribe")
def subscribe(data: PushSubscription, request: Request, user: CurrentUser, db: DB):
    """Registriert das aktuelle Gerät für Web-Push."""
    db.push.subscribe(
        user_id=user.id,
        endpoint=data.endpoint,
        p256dh=data.keys.p256dh,
        auth=data.keys.auth,
        user_agent=request.headers.get("user-agent"),
    )
    return {"ok": True}


@router.post("/unsubscribe")
def unsubscribe(data: PushUnsubscribe, user: CurrentUser, db: DB):
    """Meldet das Gerät (per endpoint) wieder ab (Soft-Revoke)."""
    db.push.unsubscribe(data.endpoint, revoked_by=user.username)
    return {"ok": True}
