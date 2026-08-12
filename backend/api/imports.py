import logging
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.models.permission import Permission
from app.services.spg_import_service import run_import
from app.services.linear_import_service import run_import as run_linear_import
from app.services import termin_notification_service as terminmeldung
from app.services.dfbnet_import_service import (
    dry_run as dfbnet_dry_run,
    uebernehmen as dfbnet_uebernehmen,
)
from ..core.deps import CurrentUser, DB

router = APIRouter(prefix="/import", tags=["import"])

logger = logging.getLogger(__name__)


@router.post("/spg")
async def import_spg(
    user: CurrentUser,
    db: DB,
    file: UploadFile = File(...),
    commit: bool = Form(False),
    update: bool = Form(False),
    allow_unmatched: bool = Form(False),
):
    """SPG-Verein CSV importieren (Admin). Ohne commit = Dry-Run (schreibt nichts)."""
    if not user.has_permission(Permission.SYSTEM_CONFIG):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Nur Administratoren dürfen importieren")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="Leere Datei")
    try:
        result = run_import(db.conn, data, commit=commit, update=update,
                            allow_unmatched=allow_unmatched)
    except UnicodeDecodeError:
        raise HTTPException(status_code=422, detail="Datei ist nicht im erwarteten Format (cp1252-CSV)")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Import fehlgeschlagen: {e}")
    return asdict(result)


@router.post("/linear")
async def import_linear(
    user: CurrentUser,
    db: DB,
    file: UploadFile = File(...),
    commit: bool = Form(False),
    update: bool = Form(False),
    allow_unmatched: bool = Form(False),
):
    """LINEAR-CSV importieren (Admin). Ohne commit = Dry-Run (schreibt nichts).

    Gleiche Flags wie beim SPG-Import; der Unterschied steckt allein im Parser
    (Kodierung, Datum mit Uhrzeit, Abteilungen als Kreuz-Spalten).
    """
    if not user.has_permission(Permission.SYSTEM_CONFIG):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Nur Administratoren dürfen importieren")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="Leere Datei")
    try:
        result = run_linear_import(db.conn, data, commit=commit, update=update,
                                   allow_unmatched=allow_unmatched)
    except UnicodeDecodeError:
        raise HTTPException(status_code=422,
                            detail="Datei ist in keiner erwarteten Kodierung lesbar "
                                   "(UTF-8 oder Windows-1252)")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Import fehlgeschlagen: {e}")
    return asdict(result)


@router.post("/dfbnet")
async def import_dfbnet(
    user: CurrentUser,
    db: DB,
    file: UploadFile = File(...),
    commit: bool = Form(False),
    benachrichtigen: bool = Form(False),
    # Änderungsdatum der hochgeladenen Datei (ISO). Der Upload selbst trägt keins –
    # multipart überträgt nur den Namen –, deshalb reicht der Browser es aus
    # `File.lastModified` mit. Fehlt es, bleibt der Stand ohne Dateidatum (#171).
    datei_datum: Optional[str] = Form(None),
):
    """DFBnet-Vereinsspielplan einlesen. Ohne `commit` = Vorschau (schreibt nichts).

    Zugriff wie beim übergreifenden Terminverwalten; Admins ohnehin. Die Vorschau
    nutzt dieselbe Zuordnung wie der Lauf — „Vorschau = Aktion".
    """
    if not user.has_permission(Permission.TERMINE_VERWALTEN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Keine Berechtigung, Spielpläne zu importieren")
    daten = await file.read()
    if not daten:
        raise HTTPException(status_code=422, detail="Leere Datei")

    def _melden(termin, aktion, vorher):
        """Kader informieren – Zu-/Absagen hängen an Zeit und Ort."""
        if aktion == 'neu':
            terminmeldung.notify_termin(db, termin, terminmeldung.AKTION_NEU, user.id)
        else:
            aenderungen = terminmeldung.diff_termin(vorher, termin)
            if aenderungen:
                terminmeldung.notify_termin(db, termin, terminmeldung.AKTION_GEAENDERT,
                                            user.id, aenderungen)

    def _entscheidung_melden(mannschaft_id, fragen):
        """Betreuer/ÜL über neue offene Fragen informieren.

        Hängt bewusst NICHT am `benachrichtigen`-Haken: Der steuert, ob der Kader
        über neue und verlegte Spiele informiert wird. Hier geht es um eine
        Handlung, die nur Betreuer/ÜL ausführen können – bliebe sie still, fiele
        ausgerechnet der Fall unter den Tisch, der als einziger jemanden braucht.
        """
        terminmeldung.notify_abweichungen(db, mannschaft_id, fragen, user.id)

    try:
        if not commit:
            bericht = dfbnet_dry_run(db, daten)
            ergebnis = asdict(bericht)
            ergebnis['zusammenfassung'] = bericht.zusammenfassung
            return {'commit': False, **ergebnis}
        lauf = dfbnet_uebernehmen(db, daten, actor=user.username,
                                  benachrichtigen=benachrichtigen, notify=_melden,
                                  notify_entscheidung=_entscheidung_melden)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Spielplan nicht lesbar: {e}")

    # Stand festhalten – erst NACH dem geglückten Lauf: Ein abgebrochener Import
    # darf den Kalender nicht als frisch ausweisen (#171).
    try:
        db.dfbnet_import_stand.set(
            dateiname=file.filename, datei_datum=(datei_datum or None),
            anzahl_spiele=len(lauf.bericht.befunde),
            by=user.username)
    except Exception:  # noqa: BLE001
        logger.warning("Import-Stand konnte nicht festgehalten werden.", exc_info=True)

    antwort = asdict(lauf)
    antwort['zusammenfassung'] = lauf.bericht.zusammenfassung
    return {'commit': True, **antwort}


@router.get("/dfbnet/stand")
def dfbnet_stand(user: CurrentUser, db: DB):
    """Von wann ist der Spielplan? Für die Kopfzeile des Terminkalenders (#171).

    Bewusst ohne eigenes Recht: Die Auskunft besteht aus einem Dateinamen und
    zwei Zeitpunkten – wer die Termine sehen darf, darf auch wissen, wie alt sie
    sind. Ohne bisherigen Import ist die Antwort leer."""
    return db.dfbnet_import_stand.get() or {}


@router.get("/dfbnet/verlauf")
def dfbnet_verlauf(user: CurrentUser, db: DB, limit: int = 20):
    """Die letzten Spielplan-Importe (wer, wann, welche Datei).

    Anders als der Stand nennt der Verlauf Namen und ist damit eine Auskunft über
    Personen – deshalb hinter demselben Recht wie das Importieren selbst."""
    if not user.has_permission(Permission.TERMINE_VERWALTEN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Keine Berechtigung, den Import-Verlauf zu sehen")
    return db.dfbnet_import_stand.verlauf(limit=max(1, min(limit, 100)))
