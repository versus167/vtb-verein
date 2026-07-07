import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# vtb_verein/ in sys.path eintragen, damit 'from app.xxx import yyy' funktioniert
sys.path.insert(0, str(Path(__file__).parent.parent / "vtb_verein"))

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.middleware.base import BaseHTTPMiddleware

from backend.core.config import settings
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
from backend.api.tickets import router as tickets_router
from backend.api.uploads import router as uploads_router
from backend.api.imports import router as imports_router
from backend.api.berichte import router as berichte_router
from backend.api.protokoll import router as protokoll_router
from backend.api.prune import router as prune_router
from backend.api.schliessanlage import router as schliessanlage_router
from backend.api.tresor import router as tresor_router

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

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

app.add_middleware(SecurityHeadersMiddleware)
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
app.include_router(tickets_router, prefix="/api")
app.include_router(uploads_router, prefix="/api")
app.include_router(imports_router, prefix="/api")
app.include_router(berichte_router, prefix="/api")
app.include_router(protokoll_router, prefix="/api")
app.include_router(prune_router, prefix="/api")
app.include_router(schliessanlage_router, prefix="/api")
app.include_router(tresor_router, prefix="/api")



@app.get("/api/health")
def health():
    return {"status": "ok", "version": get_app_version()}


@app.get("/api/app-info")
def app_info():
    """Öffentliche App-Metadaten (Name + Version) für die Anzeige im Frontend."""
    return {"name": APP_NAME, "version": get_app_version()}


# Frontend statisch ausliefern (Produktion: nach `quasar build`)
if _FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_FRONTEND_DIST / "assets")), name="assets")
    app.mount("/icons", StaticFiles(directory=str(_FRONTEND_DIST / "icons")), name="icons")

    _FRONTEND_DIST_RESOLVED = _FRONTEND_DIST.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        index = _FRONTEND_DIST_RESOLVED / "index.html"
        try:
            candidate = (_FRONTEND_DIST_RESOLVED / full_path).resolve()
            candidate.relative_to(_FRONTEND_DIST_RESOLVED)  # raises ValueError on traversal
        except (ValueError, OSError):
            return FileResponse(str(index))
        if candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(index))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=True,
    )
