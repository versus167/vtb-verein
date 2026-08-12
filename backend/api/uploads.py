"""Ausliefern von Anhang-Dateien — die gemeinsame Antwort für alle Anhang-Arten.

Hier liegt **kein Endpunkt** mehr. Der frühere `/api/uploads/{stored_name}` prüfte
nur die Anmeldung, nicht die Berechtigung am zugehörigen Ticket/Beleg — und die
Dateinamen sind fortlaufend (`att_000123.jpg`, `rech_000042.jpg`, `kabu_000007.jpg`).
Damit konnte jedes angemeldete Konto durch simples Hochzählen sämtliche Anhänge des
Vereins abziehen: Kassenbuch- und Erstattungsbelege genauso wie Ticket-Screenshots.

Heruntergeladen wird stattdessen über den jeweiligen Fach-Router
(`…/anhaenge/{anhang_id}/datei`). Der wendet dieselbe Leseprüfung an wie die
Anhang-Liste daneben — es gibt also keine zweite Rechtelogik, die auseinanderlaufen
kann. Diese Datei steuert nur noch die Datei-Antwort selbst bei.
"""

from fastapi import HTTPException, status
from fastapi.responses import FileResponse

from app.services.anhang_service import ERLAUBTE_MIME_TYPEN

# Nur Bilder gehen inline raus (Vorschau im Browser). Alles andere — auch PDF —
# als Download: Ein PDF im Browser-Kontext zu rendern bringt hier keinen Gewinn,
# die Vorschau im Frontend baut sich ihren Blob ohnehin selbst.
_INLINE_TYPEN: frozenset[str] = frozenset({
    "image/jpeg", "image/png", "image/gif", "image/webp",
})


def anhang_antwort(db, anhang) -> FileResponse:
    """Datei-Antwort für einen **bereits autorisierten** Anhang.

    Der Aufrufer hat die Berechtigung am Elternobjekt (Ticket, Rechnung, Buchung)
    geprüft und sichergestellt, dass der Anhang zu genau diesem Elternobjekt gehört
    und nicht gelöscht ist. Hier passiert nur noch das Ausliefern.

    Verlangt ein Anhang-Objekt mit ``stored_name``, ``original_name`` und
    ``mime_type`` — das trifft auf alle drei Anhang-Dataclasses zu.
    """
    basis = db.anhang_service.upload_path.resolve()
    pfad = (basis / anhang.stored_name).resolve()
    # Der stored_name wird serverseitig vergeben, seine Endung stammt aber aus dem
    # hochgeladenen Dateinamen. Die Zusicherung „bleibt im Upload-Ordner" gehört
    # deshalb hierher, nicht in das Vertrauen darauf, dass sie stimmt.
    try:
        pfad.relative_to(basis)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Datei nicht gefunden.")
    if not pfad.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Datei nicht gefunden.")

    # Der MIME-Typ kommt beim Hochladen vom Browser und steht so in der DB. Beim
    # Ausliefern zählt nur, was der Upload auch durchgelassen hätte — alles andere
    # geht als undeutbarer Download raus, statt im Browser gerendert zu werden.
    mime = anhang.mime_type if anhang.mime_type in ERLAUBTE_MIME_TYPEN else "application/octet-stream"

    return FileResponse(
        path=str(pfad),
        media_type=mime,
        # Starlette kodiert den Namen RFC-konform (filename*=utf-8''…) — wichtig,
        # weil original_name vom Hochladenden stammt und im Header landet.
        filename=anhang.original_name or anhang.stored_name,
        content_disposition_type="inline" if mime in _INLINE_TYPEN else "attachment",
    )
