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
