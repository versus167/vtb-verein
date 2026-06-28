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

    # Session-Cookie (Ticket #48, Punkt 4): das JWT wird in einem HttpOnly-Cookie
    # transportiert statt im localStorage. Dev (Quasar-Proxy) wie Prod (SPA-Mount)
    # sind same-origin → SameSite=Strict genügt. Secure muss in Dev (http) auf
    # false stehen, sonst verwirft der Browser das Cookie.
    COOKIE_NAME: str = os.getenv("VTB_COOKIE_NAME", "vtb_session")
    COOKIE_SECURE: bool = os.getenv("VTB_COOKIE_SECURE", "true").lower() == "true"
    COOKIE_SAMESITE: str = os.getenv("VTB_COOKIE_SAMESITE", "strict")

    # Vereins-Stammdaten für Belege/PDFs (z. B. Übungsleiter-Stundennachweis).
    # Defaults entsprechen dem Muster-Beleg; per Env überschreibbar.
    VEREIN_NAME: str = os.getenv("VTB_VEREIN_NAME", "VTB Chemnitz e.V.")
    VEREIN_STRASSE: str = os.getenv("VTB_VEREIN_STRASSE", "Guerickestraße 48")
    VEREIN_PLZ_ORT: str = os.getenv("VTB_VEREIN_PLZ_ORT", "09116 Chemnitz")
    VEREIN_REGISTRIER_NR: str = os.getenv("VTB_VEREIN_REGISTRIER_NR", "400193")

    # SMTP / Magic-Link
    SMTP_SERVER: str = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USE_TLS: bool = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
    SMTP_USERNAME: str = os.getenv("SMTP_USERNAME", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    MAIL_FROM: str = os.getenv("MAIL_FROM", "noreply@vtb-verein.de")
    BASE_URL: str = os.getenv("BASE_URL", "http://localhost:9000")


settings = Settings()
