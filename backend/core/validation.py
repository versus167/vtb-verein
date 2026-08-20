"""HTTP-Adapter für die Eingabevalidierung – wandelt ValueError des
framework-agnostischen Kerns in eine FastAPI-HTTPException (422) mit
String-`detail`, passend zur Fehleranzeige-Konvention im Frontend.
"""
from typing import Optional

from fastapi import HTTPException

from app.services.iban import validate_iban
from app.services.mailadresse import validate_mailadresse
from app.services.mitgliedschaft import (
    pruefe_von_in_mitgliedschaft, pruefe_wechselstichtag, zuordnung_beendet,
)


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


def wechselstichtag_or_422(von, bis, ab: str) -> str:
    """Prüft den Stichtag eines Wechsels gegen die bisherige Zuordnung und gibt
    ihn normalisiert (YYYY-MM-DD) zurück. HTTP 422 bei Verletzung.

    Nicht enthalten: dass an einer bereits abgelaufenen Zuordnung nichts mehr zu
    schneiden ist – das ist kein Eingabefehler, sondern ein Zustand, und der
    Endpunkt beantwortet ihn mit 409 (s. `nicht_beendet_or_409`).
    """
    try:
        pruefe_wechselstichtag(von, bis, ab)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return ab.strip()[:10]


def nicht_beendet_or_409(bis) -> None:
    """Ein Wechsel schneidet eine *laufende* Zuordnung. Ist sie längst abgelaufen,
    gibt es nichts zu schneiden – dann ist eine neue Zuordnung gemeint."""
    if zuordnung_beendet(bis):
        raise HTTPException(
            status_code=409,
            detail=(f"Die Zuordnung ist bereits am {bis} beendet – ein Wechsel "
                    "schneidet nur eine laufende. Bitte eine neue Zuordnung anlegen."),
        )
