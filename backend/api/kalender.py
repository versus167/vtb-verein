"""Kalender-Abo: „Meine Termine" als ICS-Feed abonnieren (#153).

Zwei Sorten Endpunkte:

* `/kalender/abo` — angemeldet, verwaltet das eigene Abo (erzeugen, ansehen,
  widerrufen).
* `/kalender/{token}.ics` — **unauthentifiziert**. Kalender-Clients (iOS,
  Google, Thunderbird) können weder Cookie noch Magic-Link; der Token in der
  URL ist die einzige Form von Anmeldung, die sie beherrschen. Er ist damit das
  Geheimnis — in der DB liegt nur sein Hash, und er wird aus dem Access-Log
  herausgefiltert (s. `AccessLogTokenFilter`).

Der Feed ruft `db.termine.list_for_user` auf, dieselbe Abfrage wie „Meine
Termine" in der App. Damit gilt exakt dieselbe Sichtbarkeit (aktiver Kader am
Stichtag plus Gast-Termine) — keine zweite Rechtelogik, die auseinanderlaufen
kann.
"""
import logging
import re
from datetime import date, timedelta
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request, Response

from app.models.permission import Permission
from app.services.ics_service import baue_kalender
from ..core.config import settings
from ..core.deps import CurrentUser, DB
from .auth import _client_ip

router = APIRouter(prefix="/kalender", tags=["kalender"])

# Festes Fenster statt „alles": Ein Kalender-Abo soll den Blick auf die Saison
# geben, nicht das komplette Vereinsarchiv in fremde Kalender spülen.
FENSTER_RUECKBLICK_TAGE = 90
FENSTER_VORAUS_TAGE = 365

_TOKEN_IM_PFAD = re.compile(r"(/api/kalender/)[^/]+(\.ics)")


class AccessLogTokenFilter(logging.Filter):
    """Feed-Token aus dem uvicorn-Access-Log entfernen.

    Der Token steht in der URL und wäre damit im Klartext in jeder Logzeile —
    und in jedem Log, das jemand weiterreicht. Wer das Log liest, könnte fremde
    Termine abonnieren. Der Pfad wird deshalb vor der Ausgabe maskiert; der
    Statuscode bleibt sichtbar, damit man Fehlversuche weiterhin sieht.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            maskiert = _TOKEN_IM_PFAD.sub(r"\1***\2", args[2])
            if maskiert != args[2]:
                record.args = args[:2] + (maskiert,) + args[3:]
        return True


def _log_kalender(db: DB, request: Request, event_type: str, actor, *, detail: str) -> None:
    """Abo-Ereignis ins Zugriffsprotokoll – best-effort, nie den Request brechen.

    Protokolliert werden nur Erzeugen und Widerrufen, nicht die Abrufe: Ein Link
    ist eine dauerhafte, anmeldungsfreie Leseberechtigung, seine Vergabe gehört
    ins Protokoll. Die Abrufe selbst sind Routine (Kalender fragen alle paar
    Stunden nach) und stünden nur als Rauschen darin — wann zuletzt abgerufen
    wurde, steht ohnehin am Abo.

    Wie bei den Zugängen (_log_zugang in personen.py) wird der *Handelnde*
    protokolliert; wen es betrifft, steht im Detail.
    """
    try:
        db.access_log_repository.log(
            event_type, category="kalender",
            user_id=actor.id, username=actor.username,
            ip=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            detail=detail,
        )
    except Exception:
        pass


def _feed_url(token: str) -> str:
    return f"{settings.BASE_URL.rstrip('/')}/api/kalender/{token}.ics"


def _webcal_url(token: str) -> str:
    """webcal://-Variante: Öffnet auf iOS/macOS direkt den Abo-Dialog, statt die
    Datei einmalig herunterzuladen (ein einmaliger Import aktualisiert sich nie)."""
    return re.sub(r"^https?://", "webcal://", _feed_url(token))


@router.get("/abo")
def abo_status(user: CurrentUser, db: DB):
    """Zustand des eigenen Abos. Die URL steht bewusst NICHT drin: In der DB
    liegt nur der Hash des Tokens, der Klartext ist nicht rekonstruierbar."""
    abo = db.kalender_abos.get_for_user(user.id)
    if not abo:
        return {"vorhanden": False}
    return {
        "vorhanden": True,
        "erstellt_am": abo["created_at"],
        "letzter_abruf": abo["letzter_abruf_at"],
        "abrufe": abo["abrufe"],
    }


@router.post("/abo")
def abo_erzeugen(request: Request, user: CurrentUser, db: DB):
    """Abo (neu) erzeugen und die URL zurückgeben — das einzige Mal, dass es sie
    im Klartext gibt. Ein bestehendes Abo wird dabei widerrufen: Der alte Link
    ist sofort tot."""
    ersetzt = db.kalender_abos.get_for_user(user.id) is not None
    token = db.kalender_abos.create_for_user(user.id, user.username)
    _log_kalender(db, request, "kalender_abo_erzeugt", user,
                  detail="Adresse neu erzeugt (alte widerrufen)" if ersetzt
                         else "Kalender-Abo erzeugt")
    return {"url": _feed_url(token), "webcal_url": _webcal_url(token)}


@router.delete("/abo")
def abo_widerrufen(request: Request, user: CurrentUser, db: DB):
    """Abo widerrufen. Der Link funktioniert danach nicht mehr; abonnierte
    Kalender laufen leer bzw. melden einen Fehler."""
    widerrufen = db.kalender_abos.revoke_for_user(user.id, user.username)
    if widerrufen:
        _log_kalender(db, request, "kalender_abo_widerrufen", user,
                      detail="Eigenes Kalender-Abo widerrufen")
    return {"widerrufen": widerrufen}


# ------------------------------------------------------------------- Aufsicht
@router.get("/abos")
def abos_uebersicht(user: CurrentUser, db: DB):
    """Wer hat einen Feed-Link, seit wann und wird er benutzt.

    Am Recht fürs Zugriffsprotokoll aufgehängt: Es ist dieselbe Frage — wer
    kommt an welche Daten. Die Adressen selbst stehen hier nicht (in der DB
    liegt nur ihr Hash), es geht um Bestand und Benutzung.
    """
    if not user.has_permission(Permission.SYSTEM_PROTOKOLL):
        raise HTTPException(status_code=403, detail="Keine Berechtigung")
    return db.kalender_abos.list_all()


@router.delete("/abos/{ziel_user_id}")
def abo_fremd_widerrufen(ziel_user_id: int, request: Request, user: CurrentUser, db: DB):
    """Fremdes Abo widerrufen — der Notausschalter, wenn ein Link in falsche
    Hände geraten ist und der Betroffene nicht selbst handeln kann."""
    if not user.has_permission(Permission.SYSTEM_PROTOKOLL):
        raise HTTPException(status_code=403, detail="Keine Berechtigung")
    ziel = db.get_user_by_id(ziel_user_id)
    if ziel is None:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")
    if not db.kalender_abos.revoke_for_user(ziel_user_id, user.username):
        raise HTTPException(status_code=404, detail="Kein aktives Abo")
    _log_kalender(db, request, "kalender_abo_widerrufen", user,
                  detail=f"Kalender-Abo von {ziel.username} widerrufen")
    return {"widerrufen": True}


def _eigene_antwort_ergaenzen(db: DB, user_id: int, termine: list[dict]) -> None:
    """`meine_antwort` je Termin nachtragen (zu | vielleicht | ab | None).

    Ohne sie sähe ein Training, für das man abgesagt hat, im Kalender aus wie
    jedes andere. Bewusst nicht über `_enrich_zusagen` aus dem Termine-Router:
    Das lädt zusätzlich Zähler, Kader-Zugehörigkeit und Spielplan-Abweichungen —
    alles Dinge, die im ICS nicht vorkommen, aber bei jedem Kalender-Poll
    abgefragt würden. Hier reichen zwei Abfragen.
    """
    if not termine:
        return
    mitglied = db.get_mitglied_by_user_id(user_id)
    if mitglied is None:
        return
    antworten = db.termin_zusagen.answer_for(mitglied.id, [t['id'] for t in termine])
    for t in termine:
        t['meine_antwort'] = antworten.get(t['id'])


@router.get("/{token}.ics")
def feed(token: str, db: DB):
    """Der Feed selbst — ohne Anmeldung, der Token ist der Ausweis."""
    user_id = db.kalender_abos.resolve_token(token)
    if user_id is None:
        # Bewusst wortkarg: Ob ein Token existiert, ist selbst eine Auskunft.
        raise HTTPException(status_code=404, detail="Kalender nicht gefunden")

    heute = date.today()
    termine = db.termine.list_for_user(
        user_id,
        von=(heute - timedelta(days=FENSTER_RUECKBLICK_TAGE)).isoformat(),
        bis=(heute + timedelta(days=FENSTER_VORAUS_TAGE)).isoformat(),
    )
    _eigene_antwort_ergaenzen(db, user_id, termine)
    basis = settings.BASE_URL.rstrip("/")
    ics = baue_kalender(
        termine,
        # Aus der konfigurierten BASE_URL, nicht aus dem Request: Die UIDs müssen
        # über die Zeit stabil bleiben, sonst dupliziert ein Abruf über einen
        # anderen Hostnamen jeden Termin.
        host=urlparse(basis).hostname or "vereinsverwaltung",
        basis_url=basis,
        kalender_name=f"Meine Termine ({settings.VEREIN_KURZ})",
    )
    return Response(
        content=ics,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": 'inline; filename="termine.ics"',
            # Persönliche Daten hinter einem Bearer-artigen Token: nichts davon
            # gehört in einen gemeinsamen Cache.
            "Cache-Control": "private, no-store",
        },
    )
