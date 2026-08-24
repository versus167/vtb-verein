"""Jeder Sidecar-Dienst muss sein Skript auch im Image finden.

Die Compose-Datei startet die Hintergrund-Läufe (`python tools/…py`), das Image
kopiert die Skripte aber EINZELN — bewusst, denn `tools/` enthält auch lokale
Secrets und Entwickler-Werkzeuge, die im Container nichts verloren haben. Genau
daran ist der Ticket-Erinnerungs-Dienst beim ersten Deploy gescheitert: Der
Container startete, das Skript fehlte, und gemerkt hat es niemand vor dem Log.

Der Test hält beide Dateien gegeneinander. Er braucht weder Docker noch eine DB.
"""
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE = _ROOT / "docker-compose.yml"
_DOCKERFILE = _ROOT / "backend" / "Dockerfile"

_SKRIPT = re.compile(r"tools/([A-Za-z0-9_]+\.py)")


def _gestartete_skripte() -> set[str]:
    """Skripte, die ein Compose-Dienst aufruft."""
    return set(_SKRIPT.findall(_COMPOSE.read_text(encoding="utf-8")))


def _kopierte_skripte() -> set[str]:
    """Skripte, die im Image landen."""
    zeilen = [z for z in _DOCKERFILE.read_text(encoding="utf-8").splitlines()
              if z.startswith("COPY tools/")]
    return {m for z in zeilen for m in _SKRIPT.findall(z)}


def test_jedes_gestartete_skript_ist_im_image():
    fehlend = _gestartete_skripte() - _kopierte_skripte()
    assert not fehlend, (
        "In docker-compose.yml gestartet, aber nicht im Image: "
        + ", ".join(sorted(fehlend))
        + " – COPY-Zeile in backend/Dockerfile ergänzen.")


def test_jedes_kopierte_skript_existiert():
    """Ein Tippfehler in der COPY-Zeile bricht erst beim Bauen auf."""
    fehlend = {s for s in _kopierte_skripte() if not (_ROOT / "tools" / s).exists()}
    assert not fehlend, f"COPY zeigt auf nicht vorhandene Datei(en): {sorted(fehlend)}"


def test_die_pruefung_greift_ueberhaupt():
    """Gegenprobe: Findet das Muster nichts mehr (umbenannte Datei, anderes
    Compose-Format), prüfen die beiden Tests oben stillschweigend nichts."""
    assert len(_gestartete_skripte()) >= 2
    assert len(_kopierte_skripte()) >= 2
