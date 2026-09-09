import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# vtb_verein/ in sys.path eintragen, damit 'from app.xxx import yyy' funktioniert
sys.path.insert(0, str(Path(__file__).parent.parent / "vtb_verein"))

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

from backend.core import branding
from backend.core.config import settings
from backend.core.security import pruefe_signaturschluessel
from app.config.app_info import APP_NAME, get_app_version
from backend.api.auth import router as auth_router
from backend.api.mitglieder import router as mitglieder_router
from backend.api.users import router as users_router
from backend.api.personen import router as personen_router
from backend.api.beitraege import router as beitraege_router
from backend.api.gebuehren import router as gebuehren_router
from backend.api.ul_stunden import router as ul_stunden_router
from backend.api.fibu import router as fibu_router
from backend.api.abteilungen import router as abteilungen_router
from backend.api.mitglied_abteilungen import router as mitglied_abteilungen_router
from backend.api.mitglied_funktionen import router as mitglied_funktionen_router
from backend.api.mitglied_kontakte import router as mitglied_kontakte_router
from backend.api.mannschaften import router as mannschaften_router
from backend.api.funktionen import router as funktionen_router
from backend.api.kassenbuch import router as kassenbuch_router
from backend.api.rechnungen import router as rechnungen_router
from backend.api.tickets import router as tickets_router
from backend.api.imports import router as imports_router
from backend.api.berichte import router as berichte_router
from backend.api.protokoll import router as protokoll_router
from backend.api.prune import router as prune_router
from backend.api.konsistenz import router as konsistenz_router
from backend.api.schliessanlage import router as schliessanlage_router
from backend.api.tresor import router as tresor_router
from backend.api.push import router as push_router
from backend.api.termine import router as termine_router
from backend.api.spielstaetten import router as spielstaetten_router
from backend.api.clubdeckel import router as clubdeckel_router
from backend.api.aufgaben import router as aufgaben_router
from backend.api.kalender import AccessLogTokenFilter, router as kalender_router

_FRONTEND_DIST = Path(__file__).parent.parent / "frontend_dist"

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Logging-Format
    fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        for handler in logging.getLogger(name).handlers:
            handler.setFormatter(fmt)
    logging.getLogger("app").setLevel(logging.INFO)
    logging.getLogger("app").handlers = logging.getLogger("uvicorn").handlers
    # Kalender-Feed-Token stehen in der URL und dürfen nicht im Access-Log landen (#153)
    logging.getLogger("uvicorn.access").addFilter(AccessLogTokenFilter())

    # Signaturschlüssel prüfen, bevor irgendetwas anderes passiert: Mit dem
    # Platzhalter aus dem Quellcode wäre jede Sitzung fälschbar. Lieber gar nicht
    # starten als angreifbar laufen — Details in core/security.py.
    pruefe_signaturschluessel()

    # DB eagerly initialisieren → Migration läuft hier, nicht beim ersten Request
    from backend.core.db import get_db
    get_db()

    # Hinweis: Das frühere Startup-Pruning der Protokoll-Seitenaufrufe entfällt – die
    # Bereinigung läuft jetzt manuell über die Datenbereinigungs-Seite (und künftig per Cron).
    yield


app = FastAPI(
    title="VTB Vereinsverwaltung API",
    version="2.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# Content-Security-Policy. Tiefenverteidigung: Das Frontend benutzt kein einziges
# `v-html`, es gibt also heute keine bekannte XSS-Fläche — die Richtlinie soll die
# Folgen begrenzen, falls doch einmal eine entsteht.
#
# Der Build macht das leicht: Die ausgelieferte index.html enthält kein Inline-Script
# und keinen Fremd-Host, Schriften und Icons liegen unter /assets. `script-src 'self'`
# kostet hier also nichts und ist der eigentliche Gewinn — eingeschleuster Code
# könnte weder von außen nachladen noch inline ausgeführt werden.
#
# Drei bewusste Zugeständnisse:
#   * `style-src` erlaubt 'unsafe-inline'. Vue und Quasar setzen Stil-Attribute,
#     ohne Nonce/Hash je Response ginge das nicht. Der Hebel für einen Angreifer
#     ist dort ungleich kleiner als bei Skripten.
#   * `img-src`/`frame-src` erlauben blob:. Die Anhang-Vorschau baut ihre Bilder
#     und PDFs aus Blob-URLs (s. AnhangPanel.vue) — ohne das bliebe sie leer.
#   * `script-src` erlaubt 'wasm-unsafe-eval' (Beleg-Scanner, Ticket #197).
#     Der Scanner erkennt die Belegkanten mit OpenCV.js, und WebAssembly zu
#     übersetzen zählt für den Browser als Code-Erzeugung zur Laufzeit — unter
#     'self' allein bricht das mit einem CSP-Verstoß ab, die Seite bliebe
#     einfach leer. Bewusst NICHT 'unsafe-eval': das Schlüsselwort erlaubt nur
#     WebAssembly, nicht eval()/new Function() auf beliebigen Text. Die
#     Bibliothek selbst kommt weiter nur von uns (frontend/public/vendor/,
#     kein CDN), und `blob:` bleibt aus script-src heraus — der Lader in
#     frontend/src/lib/belegScanner.js hängt sie deshalb als normales
#     <script src> ein und holt den Fortschrittsbalken aus einem
#     vorgeschalteten fetch, statt ein Blob-Script zu bauen.
_CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'wasm-unsafe-eval'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self'",
    "connect-src 'self'",
    "frame-src blob:",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])

# Swagger/ReDoc laden ihr JavaScript von einem CDN — unter `script-src 'self'`
# blieben beide Seiten weiß. Sie zeigen keine Nutzerdaten, sondern die eigene
# API-Beschreibung; die Richtlinie entfällt dort deshalb, statt das CDN für die
# ganze App freizugeben.
_OHNE_CSP = ("/api/docs", "/api/redoc")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if not request.url.path.startswith(_OHNE_CSP):
            response.headers["Content-Security-Policy"] = _CSP
        return response

app.add_middleware(SecurityHeadersMiddleware)
# Antworten komprimieren. Ausschlaggebend war der Beleg-Scanner (#197): dessen
# OpenCV-Bibliothek ist unkomprimiert 10,9 MB und gepackt 3,4 MB — ein Drittel,
# einmal je Gerät über Mobilfunk. Der Rest der App profitiert nebenbei, JS und
# JSON packen ähnlich gut. Unter 1 KB lohnt der Aufwand nicht, deshalb der
# Mindestwert; bereits komprimierte Formate (JPEG, PNG, PDF) lässt gzip von
# selbst nahezu unverändert.
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api")
app.include_router(mitglieder_router, prefix="/api")
app.include_router(users_router, prefix="/api")
app.include_router(personen_router, prefix="/api")
app.include_router(beitraege_router, prefix="/api")
app.include_router(gebuehren_router, prefix="/api")
app.include_router(ul_stunden_router, prefix="/api")
app.include_router(fibu_router, prefix="/api")
app.include_router(abteilungen_router, prefix="/api")
app.include_router(mitglied_abteilungen_router, prefix="/api")
app.include_router(mitglied_funktionen_router, prefix="/api")
app.include_router(mitglied_kontakte_router, prefix="/api")
app.include_router(mannschaften_router, prefix="/api")
app.include_router(funktionen_router, prefix="/api")
app.include_router(kassenbuch_router, prefix="/api")
app.include_router(rechnungen_router, prefix="/api")
app.include_router(tickets_router, prefix="/api")
app.include_router(imports_router, prefix="/api")
app.include_router(berichte_router, prefix="/api")
app.include_router(protokoll_router, prefix="/api")
app.include_router(prune_router, prefix="/api")
app.include_router(konsistenz_router, prefix="/api")
app.include_router(schliessanlage_router, prefix="/api")
app.include_router(tresor_router, prefix="/api")
app.include_router(push_router, prefix="/api")
app.include_router(termine_router, prefix="/api")
app.include_router(spielstaetten_router, prefix="/api")
app.include_router(clubdeckel_router, prefix="/api")
app.include_router(aufgaben_router, prefix="/api")
app.include_router(kalender_router, prefix="/api")



@app.get("/api/health")
def health():
    return {"status": "ok", "version": get_app_version()}


@app.get("/api/app-info")
def app_info():
    """Öffentliche App-Metadaten (Name, Version, Quellcode-Link) fürs Frontend.

    ``source_url`` erfüllt AGPL §13: die App verweist auf den Quellcode dieser
    Fassung (per ``VTB_SOURCE_URL`` überschreibbar, s. Settings).
    ``verein_kurz`` ist das Kürzel vor dem Mannschaftsnamen – das Frontend baut
    daraus den Spieltitel („VTB AH – SV X"), ohne den Verein fest zu verdrahten.
    ``verein_name`` trägt die Login-Seite. Beides ist öffentlich, weil die
    Login-Seite vor der Anmeldung wissen muss, für welchen Verein sie steht."""
    return {"name": APP_NAME, "version": get_app_version(), "source_url": settings.SOURCE_URL,
            "verein_kurz": settings.VEREIN_KURZ, "verein_name": settings.VEREIN_NAME}


@app.get("/api/branding.css", include_in_schema=False)
def branding_css():
    """Vereinsfarben als CSS-Custom-Properties (s. backend/core/branding.py).

    Hängt als ``<link>`` in der index.html, damit die Farben schon im ersten
    Bild stimmen — auch auf der Login-Seite, die vor jeder Anmeldung steht.
    Bewusst ohne Cache: die Datei ist ein paar hundert Byte, dafür wirkt eine
    geänderte Env sofort nach dem Neustart statt erst nach Ablauf eines TTL.
    """
    return Response(
        content=branding.farben_css(settings.FARBE_FLAECHE, settings.FARBE_AKZENT),
        media_type="text/css",
        headers={"Cache-Control": "no-cache"},
    )


# Branding-Ordner: instanzeigene Icons überlagern die ausgelieferten, je Datei.
# Zwei Stellen sind zu bedienen, weil die Icons an zwei Orten liegen — der
# PWA-Satz unter /icons/…, die Favicons direkt im Wurzelverzeichnis. Details und
# die Traversal-Absicherung stehen in backend/core/branding.py.
_BRANDING = branding.basis_pfad(settings.BRANDING_PATH)


def sieht_wie_datei_aus(pfad: str) -> bool:
    """Ist der Pfad eine Datei-Anfrage statt einer Route der SPA?

    Zwei Merkmale, beide gelten für keine Route der Anwendung (siehe
    ``frontend/src/router/index.js``):

    * **Punkt im letzten Segment** — ``/xmlrpc.php``, ``/.env``,
      ``//wp-includes/wlwmanifest.xml``. Das meint eine Datei; fehlt die im
      Build, ist das ein echtes 404 und nicht die ``index.html``.
    * **Ein Segment, das mit einem Punkt beginnt** — ``/.git/config``,
      ``/.aws/credentials``, ``/.stripe/``. Die haben keinen Punkt im *letzten*
      Segment und galten deshalb als Route: Der Scanner bekam die index.html
      mit 200 quittiert, was in seinem Protokoll wie ein Fund aussieht.

    Sonst quittiert die App jeden Scanner-Griff mit 200, lädt ihn zum
    Weitersuchen ein und schiebt dabei jedes Mal die ganze index.html raus.

    Dateien, die es im Build wirklich gibt, sind davon unberührt: Der Aufrufer
    liefert sie vorher aus — auch unter ``/.well-known/``, wo genau das der
    Sinn wäre.
    """
    segmente = pfad.split("/")
    if any(segment.startswith(".") for segment in segmente):
        return True
    return "." in segmente[-1]


# Ein Jahr, unveränderlich. Gilt nur für /vendor/: dort liegen fremde
# Bibliotheken, die wir nie im Nachhinein ändern, sondern nur austauschen — und
# jeder Aufruf hängt `?v=<mtime>` an, ein Austausch ergibt also ohnehin eine
# neue URL. Ausschlaggebend ist opencv.js für den Beleg-Scanner (#197): ohne
# das lädt jedes Handy 10,9 MB bei jedem Aufruf neu bzw. fragt zumindest jedes
# Mal nach. `immutable` erspart auch die Rückfrage.
_VENDOR_CACHE = {"Cache-Control": "public, max-age=31536000, immutable"}


def _cache_header(pfad: str) -> dict:
    return _VENDOR_CACHE if pfad.startswith("vendor/") else {}


# Frontend statisch ausliefern (Produktion: nach `quasar build`)
if _FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_FRONTEND_DIST / "assets")), name="assets")

    _FRONTEND_DIST_RESOLVED = _FRONTEND_DIST.resolve()
    _ICONS_DIST = _FRONTEND_DIST_RESOLVED / "icons"

    @app.get("/icons/{datei:path}", include_in_schema=False)
    def icons(datei: str):
        """PWA-Icons und Logo — Branding-Ordner schlägt Auslieferung, je Datei."""
        if (eigene := branding.datei(_BRANDING, f"icons/{datei}")) is not None:
            return FileResponse(str(eigene))
        try:
            kandidat = (_ICONS_DIST / datei).resolve()
            kandidat.relative_to(_ICONS_DIST)
        except (ValueError, OSError):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Icon nicht gefunden")
        if kandidat.is_file():
            return FileResponse(str(kandidat))
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Icon nicht gefunden")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        """Alles Übrige: erst Branding, dann Build, sonst die SPA selbst.

        Der Branding-Griff gilt hier den Favicons im Wurzelverzeichnis. Er kommt
        vor dem Build-Verzeichnis, damit ein Verein sie überhaupt ersetzen kann.
        """
        index = _FRONTEND_DIST_RESOLVED / "index.html"
        if full_path in branding.ROOT_DATEIEN:
            if (eigene := branding.datei(_BRANDING, full_path)) is not None:
                return FileResponse(str(eigene))
        try:
            candidate = (_FRONTEND_DIST_RESOLVED / full_path).resolve()
            candidate.relative_to(_FRONTEND_DIST_RESOLVED)  # raises ValueError on traversal
        except (ValueError, OSError):
            candidate = None
        if candidate is not None and candidate.is_file():
            return FileResponse(str(candidate), headers=_cache_header(full_path))
        # Datei-Anfragen, die es nicht gibt, sind 404 — nicht die SPA.
        if sieht_wie_datei_aus(full_path):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Nicht gefunden")
        return FileResponse(str(index))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=True,
    )
