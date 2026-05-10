"""
AnhangService – Generischer Datei-Speicher-Service

Handles actual file I/O for attachments. Domain-agnostic — used by
TicketService today, prepared for KassenbuchService (Belege) later.

Env-Vars (read by caller, passed into __init__):
  VTB_UPLOAD_PATH   – Speicherpfad (default: uploads/)
  VTB_MAX_UPLOAD_MB – Max. Dateigröße in MB (default: 10)
"""
import io
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

ERLAUBTE_MIME_TYPEN: set[str] = {
    'image/jpeg',
    'image/png',
    'image/gif',
    'image/webp',
    'application/pdf',
}


class DateitypNichtErlaubtError(Exception):
    pass


class DateiZuGrossError(Exception):
    pass


class AnhangService:

    def __init__(self, upload_path: str, max_mb: int = 10):
        self._upload_path = Path(upload_path)
        self._max_bytes = max_mb * 1024 * 1024
        self._upload_path.mkdir(parents=True, exist_ok=True)

    @property
    def upload_path(self) -> Path:
        return self._upload_path

    @property
    def max_mb(self) -> int:
        return self._max_bytes // (1024 * 1024)

    def validiere(self, mime_type: str, dateigroesse: int) -> None:
        """Wirft DateitypNichtErlaubtError oder DateiZuGrossError."""
        if mime_type not in ERLAUBTE_MIME_TYPEN:
            erlaubt = ', '.join(sorted(ERLAUBTE_MIME_TYPEN))
            raise DateitypNichtErlaubtError(
                f"Dateityp '{mime_type}' ist nicht erlaubt. Erlaubt: {erlaubt}"
            )
        if dateigroesse > self._max_bytes:
            raise DateiZuGrossError(
                f"Datei ist zu groß ({dateigroesse / 1024 / 1024:.1f} MB). "
                f"Maximum: {self.max_mb} MB."
            )

    def schreibe(self, stored_name: str, inhalt: bytes | io.BytesIO) -> None:
        """
        Schreibt Dateiinhalt atomisch auf Disk (temp → rename).
        Wirft IOError bei Schreibfehler.
        """
        if isinstance(inhalt, io.BytesIO):
            data = inhalt.read()
        else:
            data = inhalt

        ziel = self._upload_path / stored_name
        tmp = self._upload_path / (stored_name + '.tmp')
        try:
            tmp.write_bytes(data)
            tmp.rename(ziel)
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            raise IOError(f"Schreibfehler für '{stored_name}': {exc}") from exc

    def loesche(self, stored_name: str) -> bool:
        """Löscht Datei von Disk. Gibt True zurück wenn sie existierte. Kein Exception-Raise."""
        pfad = self._upload_path / stored_name
        try:
            pfad.unlink()
            return True
        except FileNotFoundError:
            return False
        except Exception as exc:
            logger.error("Konnte Anhang '%s' nicht löschen: %s", stored_name, exc)
            return False

    def existiert(self, stored_name: str) -> bool:
        return (self._upload_path / stored_name).is_file()

    def get_pfad(self, stored_name: str) -> Path:
        return self._upload_path / stored_name

    def lese(self, stored_name: str) -> bytes | None:
        pfad = self._upload_path / stored_name
        if not pfad.is_file():
            return None
        return pfad.read_bytes()

    def bild_zu_pdf(self, inhalt: bytes, max_dimension: int = 1800) -> bytes:
        """Konvertiert ein Bild zu einem komprimierten A4-PDF.

        Das Bild wird auf max_dimension Pixel (längste Seite) skaliert,
        als JPEG mit Qualität 80 komprimiert und mittig auf einer A4-Seite eingebettet.
        """
        from PIL import Image, ImageOps
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.utils import ImageReader

        img = ImageOps.exif_transpose(Image.open(io.BytesIO(inhalt))).convert('RGB')

        ratio = min(1.0, max_dimension / max(img.width, img.height))
        if ratio < 1.0:
            img = img.resize(
                (int(img.width * ratio), int(img.height * ratio)),
                Image.LANCZOS,
            )

        jpeg_buf = io.BytesIO()
        img.save(jpeg_buf, format='JPEG', quality=80, optimize=True)
        jpeg_buf.seek(0)

        page_w, page_h = A4
        margin = 20  # Punkte
        max_w = page_w - 2 * margin
        max_h = page_h - 2 * margin

        img_ratio = img.width / img.height
        if img_ratio > max_w / max_h:
            draw_w = max_w
            draw_h = draw_w / img_ratio
        else:
            draw_h = max_h
            draw_w = draw_h * img_ratio

        x = (page_w - draw_w) / 2
        y = (page_h - draw_h) / 2

        pdf_buf = io.BytesIO()
        c = canvas.Canvas(pdf_buf, pagesize=A4)
        c.drawImage(ImageReader(jpeg_buf), x, y, draw_w, draw_h)
        c.save()

        return pdf_buf.getvalue()
