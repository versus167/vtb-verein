"""HTTP-Adapter für die Eingabevalidierung – wandelt ValueError des
framework-agnostischen Kerns in eine FastAPI-HTTPException (422) mit
String-`detail`, passend zur Fehleranzeige-Konvention im Frontend.
"""
from typing import Optional

from fastapi import HTTPException

from app.services.iban import validate_iban
from app.services.mitgliedschaft import pruefe_von_in_mitgliedschaft


def iban_or_422(value: Optional[str]) -> Optional[str]:
    """Validiert + normalisiert eine IBAN; gibt die kanonische Form (oder None)
    zurück und wirft bei ungültiger Eingabe HTTP 422."""
    try:
        return validate_iban(value)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


def zuordnungsbeginn_or_400(db, mitglied_id: int, von: Optional[str]) -> None:
    """Fetcht das Mitglied und prüft, dass der Beginn einer Zuordnung
    (Abteilung/Funktion/Mannschaft) in der Vereinsmitgliedschaft liegt.
    HTTP 404, wenn das Mitglied fehlt; HTTP 400 bei Verletzung der Fachregel."""
    try:
        mitglied = db.get_mitglied(mitglied_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Mitglied nicht gefunden")
    try:
        pruefe_von_in_mitgliedschaft(mitglied.eintrittsdatum, mitglied.austrittsdatum, von)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
