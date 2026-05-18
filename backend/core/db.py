from app.db.datastore import VereinsDB
from .config import settings

_db: VereinsDB | None = None


def get_db() -> VereinsDB:
    global _db
    if not settings.DATABASE_URL:
        raise RuntimeError("VTB_DATABASE_URL ist nicht gesetzt. Bitte .env prüfen.")
    if _db is None or _db.conn.closed:
        _db = VereinsDB(settings.DATABASE_URL, upload_path=settings.UPLOAD_PATH)
    return _db
