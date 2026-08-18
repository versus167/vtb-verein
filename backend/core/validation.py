"""HTTP-Adapter für die Eingabevalidierung – wandelt ValueError des
framework-agnostischen Kerns in eine FastAPI-HTTPException (422) mit
String-`detail`, passend zur Fehleranzeige-Konvention im Frontend.
"""
from typing import Optional

from fastapi import HTTPException

from app.services.iban import validate_iban
from app.services.mailadresse import validate_mailadresse
from app.services.mitgliedschaft import pruefe_von_in_mitgliedschaft


def iban_or_422(value: Optional[str]) -> Optional[str]:
    """Validiert + normalisiert eine IBAN; gibt die kanonische Form (oder None)
    zurück und wirft bei ungültiger Eingabe HTTP 422."""
    try:
        return validate_iban(value)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


def mailadresse_or_422(value: Optional[str], *, pflicht: bool = False) -> Optional[str]:
    """Prüft den Aufbau einer E-Mail-Adresse und gibt sie getrimmt zurück.

    Leer/None ergibt None (Konten ohne Zugang haben keine Adresse) – es sei denn,
    `pflicht` ist gesetzt. Ungültiger Aufbau → HTTP 422. Geprüft wird nur die Form:
    ob dahinter ein Postfach steht, zeigt erst der Versand.
    """
    try:
        return validate_mailadresse(value, pflicht=pflicht)
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
