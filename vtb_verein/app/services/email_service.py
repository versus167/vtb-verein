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

    # ── VTB-Mail-Design (wie Login-Seite) ────────────────────────────────
    # Farben aus frontend/src/css/quasar.variables.scss. E-Mail-Clients
    # (v. a. Outlook mit Word-Renderer) beherrschen weder Gradients noch
    # rgba()/Flexbox — daher Tabellen-Layout, Inline-Styles und auf dem
    # jeweiligen Grund vorgemischte Volltonfarben.
    _VTB_BLAU = "#023a90"       # Wappenblau ($vtb-blau / $primary)
    _VTB_GELB = "#feeb03"       # Wappengelb ($vtb-gelb)
    _BLAU_TEXT_65 = "#a6bad8"   # entspricht weiß 65 % auf Wappenblau (Untertitel)
    _BLAU_TEXT_75 = "#c0cee3"   # entspricht weiß 75 % auf Wappenblau (Hinweise)
    _GELB_TEXT_45 = "#8c8102"   # entspricht schwarz 45 % auf Gelb (Fußzeile)

    @staticmethod
    def render_vtb_email(
        headline: str,
        username: str,
        intro_html: str,
        button_label: str,
        button_url: str,
        hints: list,
        preheader: str,
    ) -> str:
        """
        Rendert eine E-Mail im Look der Login-Seite: Wappen auf gelbem
        Grund, darunter die blaue Karte mit gelbem Voll-Breite-Button.

        Zentrale Vorlage für ALLE Button-Mails des Systems — wird auch vom
        FastAPI-Backend genutzt (backend/api/auth.py, Magic-Link-Versand).

        Args:
            headline: Zweck der Mail (weiße Zeile unter dem Vereinsnamen)
            username: Benutzername für die Anrede
            intro_html: Text zwischen Anrede und Button (darf HTML enthalten)
            button_label: Beschriftung des gelben Buttons
            button_url: Ziel des Buttons (wird auch als Fallback-Link gezeigt)
            hints: Hinweiszeilen unter dem Button (dürfen HTML enthalten)
            preheader: Vorschautext im Posteingang (in der Mail unsichtbar)
        """
        blau = EmailService._VTB_BLAU
        gelb = EmailService._VTB_GELB
        wappen_url = f"{EmailConfig.get_base_url()}/icons/vtb-wappen-512.png"
        hints_html = "".join(
            f'<p style="margin: 14px 0 0; font-size: 13px; line-height: 1.5;'
            f' color: {EmailService._BLAU_TEXT_75};">{hint}</p>'
            for hint in hints
        )
        return f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; background-color: {gelb};">
    <div style="display: none; max-height: 0; overflow: hidden;">{preheader}</div>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="{gelb}">
        <tr>
            <td align="center" style="padding: 36px 16px 28px;">
                <img src="{wappen_url}" alt="VTB-Wappen" width="150"
                     style="display: block; width: 150px; height: auto; margin: 0 auto;">
                <!--[if mso]><table role="presentation" width="460" cellpadding="0" cellspacing="0" border="0"><tr><td><![endif]-->
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
                       bgcolor="{blau}"
                       style="max-width: 460px; margin-top: 20px; background-color: {blau}; border-radius: 20px;">
                    <tr>
                        <td style="padding: 34px 30px 30px; font-family: Arial, Helvetica, sans-serif; color: #ffffff;">
                            <div style="text-align: center; font-size: 24px; font-weight: bold; letter-spacing: 0.5px; color: {gelb};">VTB Chemnitz</div>
                            <div style="text-align: center; font-size: 13px; padding-top: 2px; color: {EmailService._BLAU_TEXT_65};">Vereinsverwaltung</div>
                            <div style="text-align: center; font-size: 17px; font-weight: bold; padding-top: 28px; color: #ffffff;">{headline}</div>
                            <p style="margin: 20px 0 0; font-size: 15px; line-height: 1.6; color: #ffffff;">Hallo <strong>{username}</strong>,</p>
                            <p style="margin: 10px 0 0; font-size: 15px; line-height: 1.6; color: #ffffff;">{intro_html}</p>
                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin: 28px 0 6px;">
                                <tr>
                                    <td align="center" bgcolor="{gelb}" style="border-radius: 12px;">
                                        <a href="{button_url}"
                                           style="display: block; padding: 15px 20px; font-family: Arial, Helvetica, sans-serif; font-size: 16px; font-weight: bold; text-align: center; color: {blau}; text-decoration: none; border-radius: 12px;">{button_label}</a>
                                    </td>
                                </tr>
                            </table>
                            {hints_html}
                            <p style="margin: 14px 0 0; font-size: 13px; line-height: 1.5; color: {EmailService._BLAU_TEXT_75};">
                                Falls der Button nicht funktioniert, öffne diesen Link:<br>
                                <a href="{button_url}" style="color: {gelb}; word-break: break-all;">{button_url}</a>
                            </p>
                        </td>
                    </tr>
                </table>
                <!--[if mso]></td></tr></table><![endif]-->
                <p style="margin: 20px 0 0; font-family: Arial, Helvetica, sans-serif; font-size: 12px; color: {EmailService._GELB_TEXT_45};">
                    Viele Grüße<br>VTB Vereinsverwaltung
                </p>
            </td>
        </tr>
    </table>
</body>
</html>
"""

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
        
        # HTML-Version im Design der Login-Seite
        html_body = EmailService.render_vtb_email(
            headline="Dein Login-Link",
            username=username,
            intro_html="hier ist dein Login-Link für die Vereinsverwaltung:",
            button_label="Jetzt einloggen",
            button_url=magic_link,
            hints=[
                "Der Link ist <strong>7 Tage gültig</strong> und kann nur einmal verwendet werden.",
                "Falls du diesen Link nicht angefordert hast, kannst du diese E-Mail ignorieren.",
            ],
            preheader="Dein Login-Link für die VTB Vereinsverwaltung – 7 Tage gültig.",
        )
        
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
            
            # SMTP-Verbindung aufbauen (mit Timeout, damit ein hängender
            # Mailserver den aufrufenden Request nicht endlos blockiert)
            with smtplib.SMTP(
                EmailConfig.get_smtp_server(),
                EmailConfig.get_smtp_port(),
                timeout=EmailConfig.get_smtp_timeout()
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
    
    @staticmethod
    def send_welcome_email(recipient_email: str, token: str, username: str) -> bool:
        """
        Sendet Willkommens-E-Mail mit Magic-Link an neu angelegten Benutzer
        """
        if not EmailConfig.is_configured():
            print("⚠️  E-Mail-Konfiguration fehlt. Bitte .env-Datei prüfen.")
            return False

        base_url = EmailConfig.get_base_url()
        magic_link = f"{base_url}/auth/magic-link?token={token}"

        subject = "Willkommen in der VTB Vereinsverwaltung"

        text_body = f"""
Hallo {username},

dein Account in der VTB Vereinsverwaltung wurde eingerichtet.

Du erreichst die App unter:
{base_url}

Um dich direkt einzuloggen, klicke auf den folgenden Link – du brauchst kein Passwort:
{magic_link}

Der Link ist 7 Tage gültig und kann nur einmal verwendet werden.
Danach kannst du dir jederzeit einen neuen Login-Link über die App anfordern.

Viele Grüße,
VTB Vereinsverwaltung
"""

        # HTML-Version im Design der Login-Seite
        html_body = EmailService.render_vtb_email(
            headline="Willkommen!",
            username=username,
            intro_html=(
                f'dein Account wurde eingerichtet. Du erreichst die App ab sofort unter '
                f'<a href="{base_url}" style="color: {EmailService._VTB_GELB};">{base_url}</a>.'
                f'<br><br>Für deinen ersten Login haben wir dir bereits einen Link '
                f'vorbereitet – du brauchst kein Passwort:'
            ),
            button_label="Jetzt einloggen",
            button_url=magic_link,
            hints=[
                "Der Link ist <strong>7 Tage gültig</strong> und kann nur einmal verwendet werden. "
                "Danach kannst du dir jederzeit über die App einen neuen Login-Link anfordern.",
            ],
            preheader="Dein Zugang zur VTB Vereinsverwaltung ist eingerichtet.",
        )

        return EmailService._send_email(
            to=recipient_email,
            subject=subject,
            text_body=text_body,
            html_body=html_body
        )

    @staticmethod
    def send_text_email(recipient_email: str, subject: str, body: str) -> bool:
        """
        Sendet einfache Text-E-Mail (für Benachrichtigungen, etc.)
        
        Args:
            recipient_email: E-Mail-Adresse des Empfängers
            subject: Betreff
            body: E-Mail-Text
            
        Returns:
            True wenn erfolgreich, False bei Fehler
        """
        if not EmailConfig.is_configured():
            print("⚠️  E-Mail-Konfiguration fehlt. Bitte .env-Datei prüfen.")
            return False
        
        return EmailService._send_email(
            to=recipient_email,
            subject=subject,
            text_body=body,
            html_body=None
        )
