"""
E-Mail-Service für Versand von Magic-Links und anderen E-Mails
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from app.config.email_config import EmailConfig


# ── Farbrechnung für das Mail-Design ────────────────────────────────────────
# E-Mail-Clients (v. a. Outlook mit Word-Renderer) beherrschen weder Gradients
# noch rgba()/Flexbox — daher Tabellen-Layout, Inline-Styles und auf dem
# jeweiligen Grund *vorgemischte* Volltonfarben. Die Mischtöne standen früher als
# Hexwerte im Code; seit die zwei Grundfarben konfigurierbar sind, werden sie
# ausgerechnet. Für die Standardfarben kommen exakt dieselben Werte heraus.
_WEISS = "#ffffff"
_SCHWARZ = "#000000"


def _kanaele(hexfarbe: str) -> tuple[int, int, int]:
    h = hexfarbe.lstrip('#')
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _mischen(vorder: str, hinter: str, deckkraft: float) -> str:
    """``vorder`` mit ``deckkraft`` über ``hinter`` gelegt, als Volltonfarbe."""
    v, h = _kanaele(vorder), _kanaele(hinter)
    return '#%02x%02x%02x' % tuple(
        round(v[i] * deckkraft + h[i] * (1 - deckkraft)) for i in range(3))


def _relative_helligkeit(hexfarbe: str) -> float:
    """Relative Leuchtdichte nach WCAG — Grundlage des Kontrastverhältnisses."""
    def kanal(wert: int) -> float:
        s = wert / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4
    r, g, b = (kanal(c) for c in _kanaele(hexfarbe))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _kontrast(a: str, b: str) -> float:
    ha, hb = _relative_helligkeit(a), _relative_helligkeit(b)
    hell, dunkel = max(ha, hb), min(ha, hb)
    return (hell + 0.05) / (dunkel + 0.05)


def _lesbar_auf(grund: str, wunsch: str) -> str:
    """``wunsch``, solange er auf ``grund`` lesbar ist — sonst Schwarz oder Weiß.

    Mit den Vereinsfarben des VTB (Blau auf Gelb, Verhältnis ~8,5) greift das
    nie; es fängt den Fall ab, dass ein Verein zwei dunkle oder zwei helle
    Farben einträgt und die Mail sonst unlesbar würde.
    """
    if _kontrast(grund, wunsch) >= 4.5:
        return wunsch
    return _SCHWARZ if _relative_helligkeit(grund) > 0.35 else _WEISS


class EmailService:
    """Service für E-Mail-Versand via SMTP"""

    # Standardfarben = die der ausgelieferten Wortmarke. Ein Verein überschreibt
    # sie per VTB_MAIL_FARBE_FLAECHE/_AKZENT, ohne dass hier etwas anzupassen ist.
    _FLAECHE_DEFAULT = "#023a90"
    _AKZENT_DEFAULT = "#feeb03"

    # Hinweise unter dem Magic-Link-Button. Als Konstante, weil das FastAPI-Backend
    # (backend/api/auth.py) dieselbe Mail baut — beide Wege müssen gleich lauten (#140).
    _MAGIC_LINK_HINTS = [
        "Der Link ist <strong>7 Tage gültig</strong> und funktioniert "
        "<strong>nur ein einziges Mal</strong>. Danach forderst du dir in der App "
        "einfach einen neuen Login-Link an.",
        "Falls du diesen Link nicht angefordert hast, kannst du diese E-Mail ignorieren.",
    ]

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
        Rendert eine E-Mail im Look der Login-Seite: Logo auf der Akzentfarbe,
        darunter die Karte in der Flächenfarbe mit Voll-Breite-Button.

        Vereinsname, Kürzel, beide Farben und der Logo-Schalter kommen aus der
        Env (s. EmailConfig) — die Mail entsteht zur Laufzeit, deshalb genügt das
        hier. Ohne Logo (``VTB_MAIL_LOGO=aus``) entfällt die Bildzeile und die
        Mail trägt den Vereinsnamen nur als Text.

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
        flaeche = EmailConfig.get_mail_farbe_flaeche()
        akzent = EmailConfig.get_mail_farbe_akzent()
        verein_name = EmailConfig.get_verein_name()
        verein_kurz = EmailConfig.get_verein_kurz()
        # Mischtöne auf dem jeweiligen Grund vorgerechnet (s. oben).
        text_65 = _mischen(_WEISS, flaeche, 0.65)   # Untertitel auf der Karte
        text_75 = _mischen(_WEISS, flaeche, 0.75)   # Hinweise auf der Karte
        fuss = _mischen(_SCHWARZ, akzent, 0.45)     # Fußzeile auf dem Seitengrund
        auf_flaeche = _lesbar_auf(flaeche, akzent)  # Akzent-Text auf der Karte
        auf_akzent = _lesbar_auf(akzent, flaeche)   # Button-/Fußzeilen-Text

        base_url = EmailConfig.get_base_url().rstrip('/')
        # Ohne Schema lesbarer in der Fußzeile (app.vtbchemnitz.de statt https://…)
        base_url_label = base_url.split('://', 1)[-1]
        logo_html = ""
        if EmailConfig.get_mail_logo():
            logo_html = (
                f'<img src="{base_url}/icons/logo-512.png" alt="{verein_name}" width="150"'
                f' style="display: block; width: 150px; height: auto; margin: 0 auto;">'
            )
        hints_html = "".join(
            f'<p style="margin: 14px 0 0; font-size: 13px; line-height: 1.5;'
            f' color: {text_75};">{hint}</p>'
            for hint in hints
        )
        return f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; background-color: {akzent};">
    <div style="display: none; max-height: 0; overflow: hidden;">{preheader}</div>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="{akzent}">
        <tr>
            <td align="center" style="padding: 36px 16px 28px;">
                {logo_html}
                <!--[if mso]><table role="presentation" width="460" cellpadding="0" cellspacing="0" border="0"><tr><td><![endif]-->
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
                       bgcolor="{flaeche}"
                       style="max-width: 460px; margin-top: 20px; background-color: {flaeche}; border-radius: 20px;">
                    <tr>
                        <td style="padding: 34px 30px 30px; font-family: Arial, Helvetica, sans-serif; color: #ffffff;">
                            <div style="text-align: center; font-size: 24px; font-weight: bold; letter-spacing: 0.5px; color: {auf_flaeche};">{verein_name}</div>
                            <div style="text-align: center; font-size: 13px; padding-top: 2px; color: {text_65};">Vereinsverwaltung</div>
                            <div style="text-align: center; font-size: 17px; font-weight: bold; padding-top: 28px; color: #ffffff;">{headline}</div>
                            <p style="margin: 20px 0 0; font-size: 15px; line-height: 1.6; color: #ffffff;">Hallo <strong>{username}</strong>,</p>
                            <p style="margin: 10px 0 0; font-size: 15px; line-height: 1.6; color: #ffffff;">{intro_html}</p>
                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin: 28px 0 6px;">
                                <tr>
                                    <td align="center" bgcolor="{akzent}" style="border-radius: 12px;">
                                        <a href="{button_url}"
                                           style="display: block; padding: 15px 20px; font-family: Arial, Helvetica, sans-serif; font-size: 16px; font-weight: bold; text-align: center; color: {auf_akzent}; text-decoration: none; border-radius: 12px;">{button_label}</a>
                                    </td>
                                </tr>
                            </table>
                            {hints_html}
                            <p style="margin: 14px 0 0; font-size: 13px; line-height: 1.5; color: {text_75};">
                                Falls der Button nicht funktioniert, öffne diesen Link:<br>
                                <a href="{button_url}" style="color: {auf_flaeche}; word-break: break-all;">{button_url}</a>
                            </p>
                        </td>
                    </tr>
                </table>
                <!--[if mso]></td></tr></table><![endif]-->
                <p style="margin: 20px 0 0; font-family: Arial, Helvetica, sans-serif; font-size: 12px; color: {fuss};">
                    Viele Grüße<br>{verein_kurz} Vereinsverwaltung
                </p>
                <!-- Direkter Weg zur App – wichtig, wenn der Button-Link (z. B. ein
                     bereits verbrauchter Magic-Link) nicht mehr funktioniert (#140). -->
                <p style="margin: 12px 0 0; font-family: Arial, Helvetica, sans-serif; font-size: 12px; color: {fuss};">
                    Die App erreichst du jederzeit unter
                    <a href="{base_url}" style="color: {auf_akzent}; font-weight: bold;">{base_url_label}</a>
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
        
        base_url = EmailConfig.get_base_url().rstrip('/')
        magic_link = f"{base_url}/auth/magic-link?token={token}"

        kurz = EmailConfig.get_verein_kurz()
        subject = f"Login-Link für {kurz} Vereinsverwaltung"

        # Text-Version
        text_body = f"""
Hallo {username},

hier ist dein Login-Link für die Vereinsverwaltung:

{magic_link}

Wichtig: Der Link ist 7 Tage gültig und funktioniert nur ein einziges Mal.
Danach forderst du dir in der App einfach einen neuen Login-Link an.

Die App erreichst du jederzeit unter:
{base_url}

Falls du diesen Link nicht angefordert hast, kannst du diese E-Mail ignorieren.

Viele Grüße,
{kurz} Vereinsverwaltung
"""

        # HTML-Version im Design der Login-Seite
        html_body = EmailService.render_vtb_email(
            headline="Dein Login-Link",
            username=username,
            intro_html="hier ist dein Login-Link für die Vereinsverwaltung:",
            button_label="Jetzt einloggen",
            button_url=magic_link,
            hints=EmailService._MAGIC_LINK_HINTS,
            preheader=f"Dein Login-Link für die {kurz} Vereinsverwaltung – 7 Tage gültig, einmal nutzbar.",
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

        base_url = EmailConfig.get_base_url().rstrip('/')
        magic_link = f"{base_url}/auth/magic-link?token={token}"

        kurz = EmailConfig.get_verein_kurz()
        subject = f"Willkommen in der {kurz} Vereinsverwaltung"

        text_body = f"""
Hallo {username},

dein Account in der {kurz} Vereinsverwaltung wurde eingerichtet.

Du erreichst die App unter:
{base_url}

Um dich direkt einzuloggen, klicke auf den folgenden Link – du brauchst kein Passwort:
{magic_link}

Wichtig: Der Link ist 7 Tage gültig und funktioniert nur ein einziges Mal.
Danach kannst du dir jederzeit einen neuen Login-Link über die App anfordern.

Viele Grüße,
{kurz} Vereinsverwaltung
"""

        # HTML-Version im Design der Login-Seite
        html_body = EmailService.render_vtb_email(
            headline="Willkommen!",
            username=username,
            intro_html=(
                f'dein Account wurde eingerichtet. Du erreichst die App ab sofort unter '
                f'<a href="{base_url}" style="color: {EmailConfig.get_mail_farbe_akzent()};">{base_url}</a>.'
                f'<br><br>Für deinen ersten Login haben wir dir bereits einen Link '
                f'vorbereitet – du brauchst kein Passwort:'
            ),
            button_label="Jetzt einloggen",
            button_url=magic_link,
            hints=[
                "Der Link ist <strong>7 Tage gültig</strong> und funktioniert "
                "<strong>nur ein einziges Mal</strong>. Danach kannst du dir jederzeit "
                "über die App einen neuen Login-Link anfordern.",
            ],
            preheader=f"Dein Zugang zur {kurz} Vereinsverwaltung ist eingerichtet.",
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
