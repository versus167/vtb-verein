import sys
from pathlib import Path

# vtb_verein/ in sys.path eintragen, damit 'from app.xxx import yyy' funktioniert
sys.path.insert(0, str(Path(__file__).parent.parent / "vtb_verein"))

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.core.config import settings
from backend.api.auth import router as auth_router
from backend.api.mitglieder import router as mitglieder_router
from backend.api.users import router as users_router
from backend.api.personen import router as personen_router
from backend.api.beitraege import router as beitraege_router
from backend.api.abteilungen import router as abteilungen_router
from backend.api.mitglied_abteilungen import router as mitglied_abteilungen_router
from backend.api.mitglied_funktionen import router as mitglied_funktionen_router
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
app.include_router(kassenbuch_router, prefix="/api")
app.include_router(tickets_router, prefix="/api")
app.include_router(uploads_router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "2.0.0"}


# Frontend statisch ausliefern (Produktion: nach `quasar build`)
if _FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_FRONTEND_DIST / "assets")), name="assets")
    app.mount("/icons", StaticFiles(directory=str(_FRONTEND_DIST / "icons")), name="icons")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        file = _FRONTEND_DIST / full_path
        if file.is_file():
            return FileResponse(str(file))
        return FileResponse(str(_FRONTEND_DIST / "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=True,
    )
