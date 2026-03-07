"""
E-Mail-Service für Versand von Magic-Links und anderen E-Mails
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from app.config.email_config import EmailConfig

class EmailService:
    """Service für E-Mail-Versand via SMTP"""
    
    @staticmethod
    def send_magic_link(recipient_email: str, token: str, username: str) -> bool:
        """
        Sendet Magic-Link E-Mail an Benutzer
        
        Args:
            recipient_email: E-Mail-Adresse des Empfängers
            token: Authentifizierungs-Token
            username: Benutzername für Personalisierung
            
        Returns:
            True wenn erfolgreich, False bei Fehler
        """
        if not EmailConfig.is_configured():
            print("⚠️  E-Mail-Konfiguration fehlt. Bitte .env-Datei prüfen.")
            return False
        
        base_url = EmailConfig.get_base_url()
        magic_link = f"{base_url}/auth/magic-link?token={token}"
        
        subject = "Login-Link für VTB Vereinsverwaltung"
        
        # Text-Version
        text_body = f"""
Hallo {username},

hier ist dein Login-Link für die Vereinsverwaltung:

{magic_link}

Der Link ist 7 Tage gültig und kann nur einmal verwendet werden.

Falls du diesen Link nicht angefordert hast, kannst du diese E-Mail ignorieren.

Viele Grüße,
VTB Vereinsverwaltung
"""
        
        # HTML-Version
        html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
</head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
    <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #2c3e50;">Login-Link für VTB Vereinsverwaltung</h2>
        
        <p>Hallo <strong>{username}</strong>,</p>
        
        <p>hier ist dein Login-Link für die Vereinsverwaltung:</p>
        
        <div style="margin: 30px 0;">
            <a href="{magic_link}" 
               style="display: inline-block; padding: 12px 24px; background-color: #3498db; 
                      color: white; text-decoration: none; border-radius: 4px; font-weight: bold;">
                Jetzt einloggen
            </a>
        </div>
        
        <p style="color: #7f8c8d; font-size: 14px;">
            Der Link ist <strong>7 Tage gültig</strong> und kann nur einmal verwendet werden.
        </p>
        
        <p style="color: #7f8c8d; font-size: 14px;">
            Falls du diesen Link nicht angefordert hast, kannst du diese E-Mail ignorieren.
        </p>
        
        <hr style="border: none; border-top: 1px solid #ecf0f1; margin: 30px 0;">
        
        <p style="color: #95a5a6; font-size: 12px;">
            Viele Grüße,<br>
            VTB Vereinsverwaltung
        </p>
    </div>
</body>
</html>
"""
        
        return EmailService._send_email(
            to=recipient_email,
            subject=subject,
            text_body=text_body,
            html_body=html_body
        )
    
    @staticmethod
    def _send_email(
        to: str, 
        subject: str, 
        text_body: str, 
        html_body: Optional[str] = None
    ) -> bool:
        """
        Interner Mail-Versand via SMTP
        
        Args:
            to: Empfänger-E-Mail
            subject: Betreff
            text_body: Text-Version der E-Mail
            html_body: Optional HTML-Version
            
        Returns:
            True wenn erfolgreich, False bei Fehler
        """
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = EmailConfig.get_mail_from()
            msg['To'] = to
            
            # Text-Teil hinzufügen
            text_part = MIMEText(text_body, 'plain', 'utf-8')
            msg.attach(text_part)
            
            # HTML-Teil hinzufügen (wenn vorhanden)
            if html_body:
                html_part = MIMEText(html_body, 'html', 'utf-8')
                msg.attach(html_part)
            
            # SMTP-Verbindung aufbauen
            with smtplib.SMTP(
                EmailConfig.get_smtp_server(), 
                EmailConfig.get_smtp_port()
            ) as server:
                if EmailConfig.get_use_tls():
                    server.starttls()
                
                server.login(
                    EmailConfig.get_smtp_username(),
                    EmailConfig.get_smtp_password()
                )
                
                server.sendmail(
                    EmailConfig.get_mail_from(),
                    to,
                    msg.as_string()
                )
            
            print(f"✅ E-Mail erfolgreich gesendet an {to}")
            return True
            
        except Exception as e:
            print(f"❌ E-Mail-Fehler: {e}")
            return False
