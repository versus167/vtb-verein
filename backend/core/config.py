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

    # Passwort-Tresor (#85): symmetrischer Schlüssel für die At-rest-Verschlüsselung der
    # Tresor-Secrets. Ein urlsafe-base64-kodierter 32-Byte-Fernet-Key, NUR aus der Env.
    # Fehlt/ungültig → Tresor-Feature deaktiviert (API antwortet 503). Erzeugen mit:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    VAULT_KEY: str = os.getenv("VTB_VAULT_KEY", "")

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

    # TTLock / Zutrittskontrolle (ein Vereinskonto, Secrets nur aus Env/.env).
    # Dev-Account-Portal: euopen.ttlock.com; API-Host ist euapi.ttlock.com (NICHT euopen.*).
    TTLOCK_ENDPOINT: str = os.getenv("TTLOCK_ENDPOINT", "https://euapi.ttlock.com")
    TTLOCK_CLIENT_ID: str = os.getenv("TTLOCK_CLIENT_ID", "")
    TTLOCK_CLIENT_SECRET: str = os.getenv("TTLOCK_CLIENT_SECRET", "")
    TTLOCK_USERNAME: str = os.getenv("TTLOCK_USERNAME", "")
    TTLOCK_PASSWORD: str = os.getenv("TTLOCK_PASSWORD", "")
    # Hintergrund-Log-Sync: Default „paarmal am Tag" (alle 6 h) + Backfill-Fenster bei Erstlauf.
    TTLOCK_SYNC_INTERVAL_HOURS: int = int(os.getenv("TTLOCK_SYNC_INTERVAL_HOURS", "6"))
    TTLOCK_LOG_BACKFILL_DAYS: int = int(os.getenv("TTLOCK_LOG_BACKFILL_DAYS", "30"))

    @property
    def ttlock_configured(self) -> bool:
        """True, wenn ein TTLock-Konto vollständig in der Env hinterlegt ist."""
        return bool(
            self.TTLOCK_CLIENT_ID and self.TTLOCK_CLIENT_SECRET
            and self.TTLOCK_USERNAME and self.TTLOCK_PASSWORD
        )


settings = Settings()
