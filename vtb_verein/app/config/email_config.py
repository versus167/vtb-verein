"""
E-Mail-Konfiguration für SMTP-Versand
"""
import os
from typing import Optional

class EmailConfig:
    """E-Mail-Konfiguration aus Environment-Variablen"""
    
    @staticmethod
    def get_smtp_server() -> str:
        return os.getenv('SMTP_SERVER', 'smtp.gmail.com')
    
    @staticmethod
    def get_smtp_port() -> int:
        return int(os.getenv('SMTP_PORT', '587'))
    
    @staticmethod
    def get_smtp_username() -> Optional[str]:
        return os.getenv('SMTP_USERNAME')
    
    @staticmethod
    def get_smtp_password() -> Optional[str]:
        return os.getenv('SMTP_PASSWORD')
    
    @staticmethod
    def get_mail_from() -> str:
        return os.getenv('MAIL_FROM', 'noreply@vtb-verein.de')
    
    @staticmethod
    def get_use_tls() -> bool:
        return os.getenv('SMTP_USE_TLS', 'true').lower() == 'true'

    @staticmethod
    def get_smtp_timeout() -> int:
        """Timeout (Sekunden) für die SMTP-Verbindung, damit ein hängender/
        blockender Mailserver (z. B. IONOS) den Request nicht endlos aufhält."""
        return int(os.getenv('SMTP_TIMEOUT', '10'))
    
    @staticmethod
    def get_base_url() -> str:
        """Basis-URL der Anwendung für Links in E-Mails"""
        return os.getenv('BASE_URL', 'http://localhost:8080')
    
    # ── Absender-Identität und Aussehen der System-Mails ─────────────────────
    # Die Mail entsteht zur Laufzeit, deshalb genügen hier Env-Werte — anders als
    # beim SPA-Theme, das beim Bauen eingebacken wird.

    @staticmethod
    def get_verein_name() -> str:
        """Voller Vereinsname — steht als Überschrift auf der Mail-Karte."""
        return os.getenv('VTB_VEREIN_NAME', 'VTB Chemnitz e.V.')

    @staticmethod
    def get_verein_kurz() -> str:
        """Kürzel für Betreff und Signatur („<Kürzel> Vereinsverwaltung")."""
        return os.getenv('VTB_VEREIN_KURZ', 'VTB')

    @staticmethod
    def get_mail_farbe_flaeche() -> str:
        """Farbe der Inhaltsflächen (Karte). Muss hellen Text tragen können."""
        return EmailConfig._hexfarbe('VTB_MAIL_FARBE_FLAECHE', '#023a90')

    @staticmethod
    def get_mail_farbe_akzent() -> str:
        """Akzentfarbe (Seitengrund, Button). Muss dunklen Text tragen können."""
        return EmailConfig._hexfarbe('VTB_MAIL_FARBE_AKZENT', '#feeb03')

    @staticmethod
    def get_mail_logo() -> bool:
        """Ob die Mail ein Logo zeigt (``VTB_MAIL_LOGO=aus`` schaltet es ab).

        Der Schalter hängt bewusst nicht daran, ob eine Logodatei existiert:
        Ausgeliefert wird immer eine (die Wortmarke der Software), und die möchte
        ein fremder Verein nicht zwingend in seinen Mails haben. Ohne Logo
        entsteht die schlichte Bauform — nur Typografie, Vereinsname als Text.
        """
        return os.getenv('VTB_MAIL_LOGO', 'an').strip().lower() not in (
            'aus', 'off', 'nein', 'no', 'false', '0')

    @staticmethod
    def _hexfarbe(env_name: str, default: str) -> str:
        """Hexfarbe aus der Env — bei Unsinn der Default statt einer kaputten Mail."""
        wert = (os.getenv(env_name) or '').strip()
        if len(wert) == 7 and wert[0] == '#':
            try:
                int(wert[1:], 16)
                return wert.lower()
            except ValueError:
                pass
        return default

    @staticmethod
    def is_configured() -> bool:
        """Prüft ob E-Mail-Konfiguration vollständig ist"""
        return bool(
            EmailConfig.get_smtp_username() and 
            EmailConfig.get_smtp_password()
        )
