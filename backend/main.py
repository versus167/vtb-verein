import logging
import sys
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
from backend.api.auth import router as auth_router
from backend.api.mitglieder import router as mitglieder_router
from backend.api.users import router as users_router
from backend.api.personen import router as personen_router
from backend.api.beitraege import router as beitraege_router
from backend.api.abteilungen import router as abteilungen_router
from backend.api.mitglied_abteilungen import router as mitglied_abteilungen_router
from backend.api.mitglied_funktionen import router as mitglied_funktionen_router
from backend.api.funktionen import router as funktionen_router
from backend.api.kassenbuch import router as kassenbuch_router
from backend.api.tickets import router as tickets_router
from backend.api.uploads import router as uploads_router

_FRONTEND_DIST = Path(__file__).parent.parent / "frontend_dist"

app = FastAPI(
    title="VTB Vereinsverwaltung API",
    version="2.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
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
app.include_router(abteilungen_router, prefix="/api")
app.include_router(mitglied_abteilungen_router, prefix="/api")
app.include_router(mitglied_funktionen_router, prefix="/api")
app.include_router(funktionen_router, prefix="/api")
app.include_router(kassenbuch_router, prefix="/api")
app.include_router(tickets_router, prefix="/api")
app.include_router(uploads_router, prefix="/api")


@app.on_event("startup")
def startup():
    fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        for handler in logging.getLogger(name).handlers:
            handler.setFormatter(fmt)

    # app.* Logger in den uvicorn-Handler einhängen
    logging.getLogger("app").setLevel(logging.INFO)
    logging.getLogger("app").handlers = logging.getLogger("uvicorn").handlers

    # DB eagerly initialisieren → Migration läuft hier, nicht beim ersten Request
    from backend.core.db import get_db
    get_db()


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "2.0.0"}


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
