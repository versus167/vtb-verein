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
    def get_base_url() -> str:
        """Basis-URL der Anwendung für Links in E-Mails"""
        return os.getenv('BASE_URL', 'http://localhost:8080')
    
    @staticmethod
    def is_configured() -> bool:
        """Prüft ob E-Mail-Konfiguration vollständig ist"""
        return bool(
            EmailConfig.get_smtp_username() and 
            EmailConfig.get_smtp_password()
        )
