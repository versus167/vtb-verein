from dataclasses import asdict

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.models.permission import Permission
from app.services.spg_import_service import run_import
from app.services import termin_notification_service as terminmeldung
from app.services.dfbnet_import_service import (
    dry_run as dfbnet_dry_run,
    uebernehmen as dfbnet_uebernehmen,
)
from ..core.deps import CurrentUser, DB

router = APIRouter(prefix="/import", tags=["import"])


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


@router.post("/dfbnet")
async def import_dfbnet(
    user: CurrentUser,
    db: DB,
    file: UploadFile = File(...),
    commit: bool = Form(False),
    benachrichtigen: bool = Form(False),
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

    try:
        if not commit:
            bericht = dfbnet_dry_run(db, daten)
            ergebnis = asdict(bericht)
            ergebnis['zusammenfassung'] = bericht.zusammenfassung
            return {'commit': False, **ergebnis}
        lauf = dfbnet_uebernehmen(db, daten, actor=user.username,
                                  benachrichtigen=benachrichtigen, notify=_melden)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Spielplan nicht lesbar: {e}")

    antwort = asdict(lauf)
    antwort['zusammenfassung'] = lauf.bericht.zusammenfassung
    return {'commit': True, **antwort}
