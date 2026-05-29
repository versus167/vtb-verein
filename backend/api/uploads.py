"""
Datei-Download-Endpunkt für Anhänge.

Authentifizierung: Bearer-JWT erforderlich.
Autorisierung: jeder eingeloggte User darf herunterladen (analog NiceGUI-Layer).
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.core.config import settings
from backend.core.deps import CurrentUser

router = APIRouter(tags=["uploads"])

_MIME_TYPEN: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
}

_BILD_SUFFIXE: frozenset[str] = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp"})


@router.get("/uploads/{stored_name}")
def download_anhang(stored_name: str, _user: CurrentUser):
    # Path-Traversal-Schutz
    if any(c in stored_name for c in ("/", "\\", "..")):
        raise HTTPException(status_code=400, detail="Ungültiger Dateiname.")

    pfad = Path(settings.UPLOAD_PATH) / stored_name
    if not pfad.is_file():
        raise HTTPException(status_code=404, detail="Datei nicht gefunden.")

    suffix = pfad.suffix.lower()
    media_type = _MIME_TYPEN.get(suffix, "application/octet-stream")

    if suffix in _BILD_SUFFIXE:
        disposition = "inline"
    else:
        disposition = f'attachment; filename="{stored_name}"'

    return FileResponse(
        path=str(pfad),
        media_type=media_type,
        headers={"Content-Disposition": disposition},
    )
