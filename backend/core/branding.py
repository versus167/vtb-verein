"""Branding-Ordner: instanzeigene Icons überlagern die ausgelieferten.

Ein Image für alle Instanzen. Was ein Verein selbst mitbringt, legt er im Ordner
aus ``VTB_BRANDING_PATH`` ab; alles Übrige kommt weiter aus dem Build. Die
Überlagerung greift **je Datei** und nicht alles-oder-nichts — sonst reichte ein
vergessenes ``apple-icon-180x180.png`` und das PWA-Manifest wäre kaputt.

Der Ordner spiegelt die Struktur von ``frontend/public/``: PWA-Icons und Logo
unter ``icons/``, die Favicons direkt daneben. ``branding/vtb/`` im Repo ist der
vollständige Beispielsatz (und zugleich das Branding der VTB-Instanz).

Wichtig für den Dev-Server: Dort liefert Quasar die Icons direkt aus
``frontend/public/`` aus, ohne das Backend zu fragen. Die Überlagerung wirkt
deshalb nur im echten Betrieb, wo das Backend die SPA ausliefert.
"""
from pathlib import Path

# Im Wurzelverzeichnis wird NUR diese Liste überlagert. Alles andere dort gehört
# der SPA — griffe die Überlagerung auf beliebige Pfade, könnte eine Datei im
# Branding-Ordner eine Route der Anwendung verdecken (etwa ein index.html).
ROOT_DATEIEN = frozenset({
    "favicon.ico",
    "favicon-16x16.png",
    "favicon-32x32.png",
    "favicon-48x48.png",
    "apple-touch-icon.png",
    "mstile-150x150.png",
    "browserconfig.xml",
})


def basis_pfad(pfad: str | None) -> Path | None:
    """Den konfigurierten Ordner auflösen — None, wenn keiner gesetzt ist.

    Ein nicht existierender Pfad ist ausdrücklich kein Fehler: Dann findet
    ``datei()`` schlicht nichts und alles kommt aus der Auslieferung.
    """
    if not pfad:
        return None
    try:
        return Path(pfad).resolve()
    except OSError:
        return None


def datei(basis: Path | None, rel_pfad: str) -> Path | None:
    """Datei aus dem Branding-Ordner, falls vorhanden — sonst None.

    Gibt nur Dateien *innerhalb* des Ordners heraus. Ein ``..`` im angefragten
    Pfad — oder ein Symlink, der hinausführt — fällt beim ``relative_to`` durch
    und liefert None statt einer Datei von außerhalb.
    """
    if basis is None or not rel_pfad:
        return None
    try:
        kandidat = (basis / rel_pfad).resolve()
        kandidat.relative_to(basis)
    except (ValueError, OSError):
        return None
    return kandidat if kandidat.is_file() else None


# ── Vereinsfarben (VTB_FARBE_FLAECHE / VTB_FARBE_AKZENT) ────────────────────
#
# Zwei Farben genügen, weil die Oberfläche genau zwei Rollen kennt — dieselben
# wie die System-Mails: FLAECHE trägt Inhaltsflächen (heller Text darauf),
# AKZENT ist Seitengrund und Markierung (dunkler Text darauf). Ausgeliefert
# werden sie als CSS-Custom-Properties über ``/api/branding.css``; das
# Stylesheet hängt in der index.html und wirkt daher schon beim ersten Bild,
# ohne das Aufblitzen, das ein nachgeladener Wert aus /api/app-info hätte.
#
# Die ``*-rgb``-Fassungen sind kein Luxus: ``rgba(var(--x), .2)`` funktioniert
# nur mit einer Kanalliste, und das Theme braucht überall halbtransparente
# Tönungen der beiden Farben.
#
# Was hier NICHT herauskommt, sind die abgeleiteten Töne (Navy-Stufen des Dark
# Mode, das tiefe Menüblau, die Chip-Blaus): die sind von Hand gemischt und
# lassen sich nicht aus einem Grundton errechnen. Ein fremder Verein bekommt
# darum ein vollständig eigenes Theme „Hell" und in „VTB"/„Dunkel" seine Farben
# als Fläche und Akzent auf einer blau-grauen Struktur.
FLAECHE_STANDARD = "#023a90"  # Wappenblau — gleich gehalten mit email_config.py
AKZENT_STANDARD = "#feeb03"  # Wappengelb


def hexfarbe(wert: str | None, default: str) -> str:
    """``#rrggbb`` aus der Env — bei allem anderen der Default.

    Streng, weil der Wert ungeprüft in ein ausgeliefertes Stylesheet wandert:
    Nur genau sieben Zeichen, führendes ``#``, Rest hexadezimal. Damit kann
    nichts aus der Env die CSS-Regel verlassen (``}`` oder ``</style>``).
    """
    wert = (wert or "").strip()
    if len(wert) == 7 and wert[0] == "#":
        try:
            int(wert[1:], 16)
            return wert.lower()
        except ValueError:
            pass
    return default


def _kanaele(hexfarbe_: str) -> str:
    """``#023a90`` → ``2, 58, 144`` für die rgba()-Schreibweise."""
    h = hexfarbe_.lstrip("#")
    return ", ".join(str(int(h[i:i + 2], 16)) for i in (0, 2, 4))


def _mischen(farbe: str, ziel: str, anteil: float) -> str:
    """``farbe`` um ``anteil`` in Richtung ``ziel`` verschoben."""
    f = [int(farbe.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    z = [int(ziel.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    return "#%02x%02x%02x" % tuple(
        round(f[i] * (1 - anteil) + z[i] * anteil) for i in range(3))


def _abgeleitete_toene(flaeche: str) -> dict[str, str]:
    """Menü- und Chip-Ton zur Flächenfarbe — abgesenkt und angehoben.

    Beim VTB sind das von Hand gemischte Werte (``$vtb-blau-tief`` für das Menü,
    ``$vtb-blau-btn-dark`` für Chips und Dark-Mode-Buttons). Solange die
    Standardfarbe steht, bleiben genau die stehen: Ein Rechenweg, der beide exakt
    trifft, existiert nicht, und der VTB soll nach diesem Ticket pixelgleich
    aussehen. Erst wenn ein Verein eigene Farben einträgt, werden sie gerechnet —
    dort gibt es keinen Handmisch-Wert, den man erhalten könnte, und ein blaues
    Menü unter einer roten Kopfzeile wäre offensichtlich falsch.
    """
    if flaeche == FLAECHE_STANDARD:
        return {}
    tief = _mischen(flaeche, "#000000", 0.28)
    return {
        "--vtb-flaeche-tief": tief,
        "--vtb-flaeche-tief-rgb": _kanaele(tief),
        "--vtb-flaeche-hoch": _mischen(flaeche, "#ffffff", 0.14),
    }


def farben_css(flaeche: str | None, akzent: str | None) -> str:
    """Das Stylesheet mit den Vereinsfarben.

    ``html:root`` statt ``:root``: Quasar setzt ``--q-primary`` selbst in einem
    ``:root``-Block. Die zusätzliche Elementangabe gewinnt unabhängig davon, in
    welcher Reihenfolge die Stylesheets im Kopf stehen.
    """
    f = hexfarbe(flaeche, FLAECHE_STANDARD)
    a = hexfarbe(akzent, AKZENT_STANDARD)
    werte = {
        "--vtb-flaeche": f,
        "--vtb-flaeche-rgb": _kanaele(f),
        "--vtb-akzent": a,
        "--vtb-akzent-rgb": _kanaele(a),
        "--q-primary": f,
        **_abgeleitete_toene(f),
    }
    zeilen = "".join(f"  {name}: {wert};\n" for name, wert in werte.items())
    return (
        "/* Vereinsfarben dieser Instanz — VTB_FARBE_FLAECHE / VTB_FARBE_AKZENT */\n"
        f"html:root {{\n{zeilen}}}\n"
    )
