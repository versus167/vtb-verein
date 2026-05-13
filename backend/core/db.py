from app.db.datastore import VereinsDB
from .config import settings

_db: VereinsDB | None = None


def get_db() -> VereinsDB:
    global _db
    if _db is None:
        _db = VereinsDB(settings.DB_PATH, upload_path=settings.UPLOAD_PATH)
    return _db
