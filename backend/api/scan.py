"""Beleg-Scanner: Aufnahmen zu einem PDF zusammensetzen (Ticket #197).

Eigener Router statt eines Endpunkts unter ``/api/rechnungen``, weil der
Scanner kein Rechnungs-Werkzeug ist. Er baut aus Kamerabildern ein PDF und
gibt es zurück — was danach damit geschieht, entscheidet die aufrufende
Fläche. Gebraucht wird er inzwischen an drei davon: Rechnungsbelege,
Ticket-Anhänge und Kassenbuch-Belege.

Solange er unter ``/api/rechnungen/beleg-scan`` hing, verlangte er
``rechnungen.einreichen``. Wer ein Ticket schreiben darf, aber keine
Rechnungen einreicht, wäre dort auf ein 403 gelaufen — obwohl er den Beleg
gleich danach ganz regulär als Datei hätte hochladen dürfen.

Deshalb reicht hier die Anmeldung. Das gibt nichts preis: Der Endpunkt ist
zustandslos, liest nichts, legt nichts ab und gibt nur zurück, was der
Aufrufer selbst geschickt hat. Die eigentliche Rechteprüfung sitzt dort, wo
das PDF danach abgelegt wird — im Ticket-, Rechnungs- oder Kassenbuch-Upload,
jeder mit seiner eigenen Regel.
"""
from fastapi import APIRouter, File, HTTPException, Response, UploadFile

from backend.core.deps import CurrentUser, DB
from app.services.anhang_service import DateiZuGrossError
from app.services.scan_pdf_service import ScanFehlerError, zu_gross_meldung

from .uploads import lese_upload

router = APIRouter(prefix="/scan", tags=["scan"])


@router.post("/beleg-pdf")
async def beleg_pdf(user: CurrentUser, db: DB,
                    pages: list[UploadFile] = File(...)):
    """Gescannte Seiten zu einem Beleg-PDF zusammensetzen.

    Bewusst zustandslos: Der Endpunkt legt nichts ab, sondern gibt das fertige
    PDF zurück. Die Fläche hält es dann wie eine selbst gewählte Datei und lädt
    es beim Speichern über den normalen Anhang-Weg hoch. Das hat drei Gründe:

    * Beim Anlegen einer neuen Rechnung (oder eines neuen Tickets) gibt es noch
      keine ID, an der ein Anhang hängen könnte — der Scanner soll aber vor dem
      Speichern nutzbar sein, sonst müsste man den Entwurf vorab anlegen.
    * Es braucht keine Zwischenablage-Tabelle und damit keinen weiteren Eintrag
      im PRUNE_REGISTRY.
    * Das PDF geht als PDF durch ``AnhangService`` und wird dort **nicht**
      angefasst; nur Bilder laufen durch ``bild_zu_jpeg`` (1800 px / Q80).
      Die volle Scan-Auflösung bleibt so erhalten.

    Alle Seiten kommen in *einem* Request. Eine Schleife über Einzel-Uploads
    wäre nicht gleichwertig: Bei einem Abbruch bliebe ein halber Beleg zurück,
    und die Seitenreihenfolge hinge am Zufall der Antwortzeiten.
    """
    dienst = db.scan_pdf_service
    if len(pages) > dienst.max_seiten:
        raise HTTPException(
            status_code=422,
            detail=f"Mehr als {dienst.max_seiten} Seiten je Beleg sind nicht vorgesehen.")

    seiten: list[bytes] = []
    try:
        for datei in pages:
            seiten.append(await lese_upload(datei, dienst.max_seite_bytes))
    except DateiZuGrossError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Gegen die Anhang-Grenze prüfen, BEVOR gebaut wird. Das PDF wiegt praktisch
    # so viel wie die Summe der JPEGs (die wandern unverändert als DCTDecode
    # hinein), die Summe ist hier also schon eine belastbare Vorhersage.
    grenze = db.anhang_service.max_bytes
    meldung = zu_gross_meldung(sum(len(s) for s in seiten), grenze)
    if meldung:
        raise HTTPException(status_code=422, detail=meldung)

    try:
        pdf = dienst.baue(seiten)
    except ScanFehlerError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Nachkontrolle am fertigen PDF: Die Vorhersage oben ist gut, aber nicht
    # exakt (PDF-Gerüst, und ein PNG unter den Seiten kodiert ReportLab neu).
    # Was hier durchgeht, muss beim Speichern durch den Anhang-Weg passen —
    # sonst wäre die Arbeit doch umsonst gewesen.
    meldung = zu_gross_meldung(len(pdf), grenze, was="Das fertige PDF")
    if meldung:
        raise HTTPException(status_code=422, detail=meldung)

    return Response(content=pdf, media_type="application/pdf")
