from dataclasses import asdict

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.models.permission import Permission
from app.services.spg_import_service import run_import
from app.services.dfbnet_import_service import dry_run as dfbnet_dry_run
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


@router.post("/dfbnet/vorschau")
async def dfbnet_vorschau(
    user: CurrentUser,
    db: DB,
    file: UploadFile = File(...),
):
    """DFBnet-Vereinsspielplan einlesen und melden, was ein Lauf tun würde.

    Diese Stufe schreibt NICHTS – sie ordnet nur zu (Etappe 2). Zugriff wie beim
    übergreifenden Terminverwalten; Admins ohnehin.
    """
    if not user.has_permission(Permission.TERMINE_VERWALTEN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Keine Berechtigung, Spielpläne zu importieren")
    daten = await file.read()
    if not daten:
        raise HTTPException(status_code=422, detail="Leere Datei")
    try:
        bericht = dfbnet_dry_run(db, daten)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Spielplan nicht lesbar: {e}")
    ergebnis = asdict(bericht)
    ergebnis['zusammenfassung'] = bericht.zusammenfassung
    return ergebnis
