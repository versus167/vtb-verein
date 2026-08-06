#!/usr/bin/env python3
"""Erzeugt den ausgelieferten Standard-Icon-Satz („VTB"-Wortmarke der Software).

Das ist NICHT das Vereinsbranding — Vereine überlagern die Dateien über den
Branding-Ordner (VTB_BRANDING_PATH). Hier entsteht nur der neutrale Auslieferungs-
Stand, der zeigt, welche Software läuft.

Aufruf:  ./venv/bin/python tools/make_default_icons.py frontend
Erzeugt <ziel>/public/… und <ziel>/public/icons/… — genau die Struktur, die auch
ein Branding-Ordner spiegelt (vgl. branding/vtb/).

Entwickler-Werkzeug, kein Laufzeit-Code: braucht Pillow, das bewusst NICHT in
backend/requirements.txt steht. Der erzeugte Satz liegt im Repo; das Skript wird
nur gebraucht, wenn die Wortmarke sich ändert.
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BLAU = (2, 58, 144)          # $vtb-blau #023a90 – zugleich $primary der App
WEISS = (255, 255, 255)
FONT = "/usr/share/fonts/truetype/roboto/unhinted/RobotoTTF/Roboto-Bold.ttf"
SS = 8                       # Supersampling: erst groß zeichnen, dann herunterrechnen
TEXT = "VTB"


def _mark(size: int, *, breite: float, radius: float, hintergrund=BLAU) -> Image.Image:
    """Ein Kachelbild: abgerundetes Quadrat mit zentrierter Wortmarke.

    ``breite`` = Anteil der Kachelbreite, den die Schrift einnimmt (kleine Icons
    vertragen mehr, weil sonst nur ein Fleck bleibt). ``radius`` = Eckenradius als
    Anteil der Kantenlänge; 0 liefert ein volles Quadrat (Apple und maskable
    runden selbst).
    """
    gross = size * SS
    img = Image.new("RGBA", (gross, gross), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if radius > 0:
        d.rounded_rectangle([0, 0, gross - 1, gross - 1],
                            radius=int(gross * radius), fill=hintergrund)
    else:
        d.rectangle([0, 0, gross - 1, gross - 1], fill=hintergrund)

    # Schriftgröße iterativ an die Zielbreite annähern – Roboto hat keine
    # verlässliche Vorhersage von Punktgröße auf Pixelbreite.
    ziel = gross * breite
    groesse, letzte = int(gross * 0.5), None
    for _ in range(40):
        f = ImageFont.truetype(FONT, groesse)
        l, t, r, b = d.textbbox((0, 0), TEXT, font=f)
        if abs((r - l) - ziel) < gross * 0.005:
            letzte = (f, (l, t, r, b))
            break
        groesse = max(1, int(groesse * ziel / max(r - l, 1)))
        letzte = (f, d.textbbox((0, 0), TEXT, font=f))
    f, (l, t, r, b) = letzte
    d.text(((gross - (r - l)) / 2 - l, (gross - (b - t)) / 2 - t), TEXT,
           font=f, fill=WEISS)
    return img.resize((size, size), Image.LANCZOS)


def _speichern(img: Image.Image, pfad: Path) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    img.save(pfad)
    print(f"  {pfad.name:<28} {img.size[0]}×{img.size[1]}")


# Safari-Pinned-Tab: einfarbige Silhouette, 16×16-Raster. Bewusst als Striche
# statt als Buchstaben-Umrisse – bei 16 px ist das lesbarer und braucht keine
# Font-Konvertierung.
PINNED_TAB = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">
  <g fill="none" stroke="#000" stroke-width="1.35" stroke-linecap="butt" stroke-linejoin="miter">
    <path d="M1.1 4.6 3.0 11.4 4.9 4.6"/>
    <path d="M5.9 4.6h4.0M7.9 4.6v6.8"/>
    <path d="M11.2 4.6v6.8M11.2 4.6h1.4a1.6 1.6 0 0 1 0 3.2h-1.4m0 0h1.7a1.7 1.7 0 0 1 0 3.4h-1.7"/>
  </g>
</svg>
"""

BROWSERCONFIG = """<?xml version="1.0" encoding="utf-8"?>
<browserconfig>
  <msapplication>
    <tile>
      <square150x150logo src="/mstile-150x150.png"/>
      <TileColor>#023a90</TileColor>
    </tile>
  </msapplication>
</browserconfig>
"""


def main(ziel: Path) -> None:
    public, icons = ziel / "public", ziel / "public" / "icons"

    print("PWA-Icons (abgerundet, wie das Original von 05/2026):")
    for s in (128, 192, 256, 384, 512):
        _speichern(_mark(s, breite=0.78, radius=0.16), icons / f"icon-{s}x{s}.png")
    _speichern(_mark(128, breite=0.78, radius=0.16), icons / "favicon-128x128.png")

    # maskable: volle Fläche, Marke innerhalb des sicheren Kreises (~80 %).
    print("Maskable (Sicherheitsrand):")
    _speichern(_mark(512, breite=0.56, radius=0.0), icons / "icon-maskable-512x512.png")

    # Apple rundet selbst – ein eigener Radius ergäbe doppelte Ecken.
    print("Apple (volle Fläche, iOS rundet selbst):")
    for s in (120, 152, 167, 180):
        _speichern(_mark(s, breite=0.74, radius=0.0), icons / f"apple-icon-{s}x{s}.png")
    _speichern(_mark(180, breite=0.74, radius=0.0), public / "apple-touch-icon.png")

    print("Microsoft-Kacheln:")
    _speichern(_mark(144, breite=0.74, radius=0.0), icons / "ms-icon-144x144.png")
    _speichern(_mark(150, breite=0.74, radius=0.0), public / "mstile-150x150.png")

    # Favicons: je kleiner, desto randloser – sonst bleibt bei 16 px nur ein Fleck.
    print("Favicons:")
    for s, breite in ((16, 0.92), (32, 0.88), (48, 0.86)):
        _speichern(_mark(s, breite=breite, radius=0.12), public / f"favicon-{s}x{s}.png")
    ico = _mark(48, breite=0.86, radius=0.12)
    ico.save(public / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    print(f"  {'favicon.ico':<28} 16/32/48 (multi-res)")

    # Mail- und Login-Logo. Hieß früher vtb-wappen-512.png; das Wappen selbst
    # liegt jetzt als branding/vtb/icons/logo-512.png im Branding-Ordner.
    print("Mail-Logo:")
    _speichern(_mark(512, breite=0.78, radius=0.16), icons / "logo-512.png")

    (icons / "safari-pinned-tab.svg").write_text(PINNED_TAB, encoding="utf-8")
    print(f"  {'safari-pinned-tab.svg':<28} einfarbig")
    (public / "browserconfig.xml").write_text(BROWSERCONFIG, encoding="utf-8")
    print(f"  {'browserconfig.xml':<28} TileColor #023a90")


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
