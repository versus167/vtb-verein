import os
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent  # Repo-Root


class Settings:
    SECRET_KEY: str = os.getenv("VTB_SECRET_KEY", "CHANGE_ME_IN_PRODUCTION")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("VTB_TOKEN_EXPIRE_MINUTES", "1440"))  # 24h
    DATABASE_URL: str = os.getenv("VTB_DATABASE_URL", "")
    UPLOAD_PATH: str = os.getenv("VTB_UPLOAD_PATH", str(_ROOT / "vtb_verein" / "uploads"))
    HOST: str = os.getenv("VTB_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("VTB_PORT", "8000"))
    FRONTEND_ORIGINS: list[str] = os.getenv(
        "VTB_FRONTEND_ORIGINS", "http://localhost:9000,http://localhost:8080"
    ).split(",")


settings = Settings()
