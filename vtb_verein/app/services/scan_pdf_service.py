"""Gescannte Seiten zu einem Beleg-PDF zusammensetzen (Ticket #197).

Gegenstück zum ``ScanPdfBuilder`` des X1-ERP, aus dem der Beleg-Scanner
übernommen wurde. Die Seitengeometrie ist dort abgenommen worden und wird
hier bewusst *identisch* nachgebaut, nicht „verbessert":

* eine PDF-Seite je Bild, in der Reihenfolge der Übergabe,
* lange Kante immer 297 mm, kurze Kante nach dem Seitenverhältnis des Bildes,
* das Bild füllt die Seite randlos.

Ein Kassenbon wird damit eine schmale, hohe Seite statt eines Schnipsels in
der Mitte einer weißen A4-Fläche. Genau deshalb taugt ``AnhangService.
bild_zu_pdf`` hier nicht: das legt jedes Bild mittig auf A4 mit Rand.

Die Bilddaten wandern **unverändert** ins PDF. ReportLab bettet JPEG direkt
als DCTDecode-Strom ein, es wird also weder neu kodiert noch skaliert — die
2400 px lange Kante, die der Scanner nach der Entzerrung liefert, bleibt
erhalten. Das ist der Grund, warum der Scanner-Upload nicht durch
``AnhangService.bild_zu_jpeg`` läuft: das würde auf 1800 px und Qualität 80
herunterrechnen und die Entzerrung teilweise wieder einkassieren.
"""
import io
from typing import Sequence

# Lange Kante jeder Seite. 297 mm ist die lange Kante von A4 — ein Hochformat-
# Scan trifft damit A4 genau, alles andere wird schmaler oder breiter.
LANGE_KANTE_MM = 297.0

MAX_SEITEN = 20
MAX_SEITE_BYTES = 12 * 1024 * 1024

ERLAUBTE_TYPEN = ("image/jpeg", "image/png")


class ScanFehlerError(ValueError):
    """Übergebene Seiten taugen nicht für ein PDF."""


class ScanPdfService:
    """Baut aus JPEG-/PNG-Seiten ein Bild-PDF ohne Textebene."""

    def __init__(self, lange_kante_mm: float = LANGE_KANTE_MM,
                 max_seiten: int = MAX_SEITEN,
                 max_seite_bytes: int = MAX_SEITE_BYTES) -> None:
        self._lange_kante_mm = lange_kante_mm
        self._max_seiten = max_seiten
        self._max_seite_bytes = max_seite_bytes

    @property
    def max_seiten(self) -> int:
        return self._max_seiten

    @property
    def max_seite_bytes(self) -> int:
        return self._max_seite_bytes

    def pruefe(self, seiten: Sequence[bytes]) -> None:
        """Wirft :class:`ScanFehlerError`, wenn die Seiten so nicht taugen."""
        if not seiten:
            raise ScanFehlerError("Keine Seiten übergeben.")
        if len(seiten) > self._max_seiten:
            raise ScanFehlerError(
                f"Mehr als {self._max_seiten} Seiten je Beleg sind nicht vorgesehen.")
        for nr, inhalt in enumerate(seiten, start=1):
            if not inhalt:
                raise ScanFehlerError(f"Seite {nr} ist leer.")
            if len(inhalt) > self._max_seite_bytes:
                grenze_mb = self._max_seite_bytes // (1024 * 1024)
                raise ScanFehlerError(
                    f"Seite {nr} ist größer als {grenze_mb} MB.")

    def seitenmass_pt(self, breite_px: int, hoehe_px: int) -> tuple:
        """Seitengröße in Punkt zu einem Bild dieser Pixelmaße.

        Die lange Bildkante wird zur langen Seitenkante; die kurze ergibt sich
        aus dem Seitenverhältnis. Ein querformatiges Bild ergibt also eine
        querformatige Seite, ein Kassenbon eine schmale hohe.
        """
        from reportlab.lib.units import mm

        if breite_px <= 0 or hoehe_px <= 0:
            raise ScanFehlerError("Seite hat keine gültigen Bildmaße.")
        lang = self._lange_kante_mm * mm
        if breite_px >= hoehe_px:
            return (lang, lang * hoehe_px / breite_px)
        return (lang * breite_px / hoehe_px, lang)

    def baue(self, seiten: Sequence[bytes]) -> bytes:
        """Setzt die Seiten zu einem PDF zusammen und gibt es als Bytes zurück.

        Reihenfolge der Übergabe = Seitenreihenfolge im PDF.
        """
        import reportlab.rl_config as rl_config
        from PIL import Image
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen import canvas

        self.pruefe(seiten)

        # ReportLab armiert Bildströme standardmäßig mit ASCII85 — eine
        # Textkodierung aus der Zeit, als PDFs über 7-Bit-Kanäle gingen. Sie
        # bläht jedes Bild um ein Viertel auf, ohne hier etwas zu leisten.
        # Ausgeschaltet wandert das JPEG als roher DCTDecode-Strom ins PDF:
        # byte-identisch, aber spürbar kleiner. Das zählt doppelt, weil dieses
        # PDF zum Handy zurückgeht und von dort erneut hochgeladen wird.
        #
        # Der Schalter ist leider global. Deshalb wird er nur um den Bau herum
        # umgelegt. Trifft das zeitgleich einen anderen PDF-Bau (Kassenbuch,
        # Stundennachweis), ist der Ausgang in beide Richtungen harmlos: Die
        # Streams werden dort dann roh statt ASCII85-kodiert oder umgekehrt —
        # beides sind gültige PDFs mit identischem Inhalt.
        vorher = rl_config.useA85
        rl_config.useA85 = 0
        try:
            puffer = io.BytesIO()
            c = canvas.Canvas(puffer)
            for nr, inhalt in enumerate(seiten, start=1):
                try:
                    # Nur den Kopf lesen: Pillow ermittelt die Maße, ohne das
                    # ganze Bild zu dekodieren. Die Bytes selbst reicht
                    # ReportLab unverändert weiter.
                    with Image.open(io.BytesIO(inhalt)) as bild:
                        breite_px, hoehe_px = bild.size
                except Exception as exc:  # defekte oder fremde Datei
                    raise ScanFehlerError(
                        f"Seite {nr} ist kein lesbares Bild.") from exc

                seite = self.seitenmass_pt(breite_px, hoehe_px)
                c.setPageSize(seite)
                # ReportLab legt bildgleiche Seiten nur einmal ab. Sein
                # Schlüssel ist der dekodierte Pixelstrom OHNE die Bildmaße —
                # zwei Bilder mit gleichen Pixeln, aber vertauschten Kanten
                # teilten sich also ein XObject und die zweite Seite käme
                # verzerrt heraus. Für Scanner-Seiten ist das nicht
                # erreichbar (lange Kante immer 2400 px, gleiche Pixelzahl
                # bei vertauschten Kanten nur im Quadrat — dann stimmen die
                # Maße wieder). Wer diesen Dienst anderswo benutzt, sollte es
                # wissen; s. Test `test_gleiche_bilddaten_werden_einmal_abgelegt`.
                c.drawImage(ImageReader(io.BytesIO(inhalt)), 0, 0,
                            width=seite[0], height=seite[1])
                c.showPage()
            c.save()
            return puffer.getvalue()
        finally:
            rl_config.useA85 = vorher
