"""HTTP-Adapter für die Eingabevalidierung – wandelt ValueError des
framework-agnostischen Kerns in eine FastAPI-HTTPException (422) mit
String-`detail`, passend zur Fehleranzeige-Konvention im Frontend.
"""
from typing import Optional

from fastapi import HTTPException

from app.services.iban import validate_iban


def iban_or_422(value: Optional[str]) -> Optional[str]:
    """Validiert + normalisiert eine IBAN; gibt die kanonische Form (oder None)
    zurück und wirft bei ungültiger Eingabe HTTP 422."""
    try:
        return validate_iban(value)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
