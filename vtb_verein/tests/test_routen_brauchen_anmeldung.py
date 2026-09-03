"""Jede API-Route hängt an der Anmeldung – oder steht namentlich auf der Ausnahmeliste.

Anlass: `GET /api/funktionen` nahm nur `db: DB` entgegen und hing damit an keiner
Auth-Dependency. Der Endpunkt beantwortete jede Anfrage aus dem Internet mit 200,
während alle Nachbarrouten derselben Datei korrekt prüften. Das war keine
Entscheidung, sondern ein vergessener Parameter — und genau so etwas findet man
beim Lesen nicht zuverlässig wieder.

Dieser Test schaut deshalb nicht in den Quelltext, sondern in den fertig
verdrahteten Dependency-Baum von FastAPI: Für jede Route wird geprüft, ob
`get_current_user` darin vorkommt. Neue Routen sind damit automatisch erfasst.

Die Ausnahmen stehen unten einzeln mit Begründung. Wer eine Route hinzufügt, die
ohne Anmeldung erreichbar sein soll, trägt sie dort ein — und begründet sie damit
zwangsläufig. Das ist der eigentliche Zweck der Liste: nicht Routen durchwinken,
sondern eine bewusste Entscheidung erzwingen.
"""
import sys
from pathlib import Path

import pytest
from fastapi.routing import APIRoute

# Repo-Wurzel für den backend.*-Import ergänzen (backend/ ist kein app-Paket).
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.core.deps import get_current_user  # noqa: E402
from backend.main import app  # noqa: E402


# (Methode, Pfad) → Grund. Bewusst als Dict: Der Grund ist der Sinn des Eintrags.
OEFFENTLICH: dict[tuple[str, str], str] = {
    ("POST", "/api/auth/login"):
        "Die Anmeldung selbst – prüft Kennung und Passwort, gebremst über das "
        "Zugriffsprotokoll (LOGIN_MAX_PRO_KONTO/_PRO_IP).",
    ("POST", "/api/auth/magic-link/request"):
        "Login-Link anfordern. Antwortet immer 200, um vorhandene Konten nicht zu "
        "verraten; eigene Limits pro IP und pro Empfänger.",
    ("POST", "/api/auth/magic-link/validate"):
        "Login-Link einlösen – der Token IST hier der Nachweis (Single-Use, 7 Tage).",
    ("GET", "/api/kalender/{token}.ics"):
        "ICS-Feed für Kalender-Clients, die sich nicht anmelden können. Der Token "
        "in der URL ist das Geheimnis (256 Bit, nur als Hash gespeichert).",
    ("GET", "/api/health"):
        "Healthcheck des Containers – nennt nur Status und Version.",
    ("GET", "/api/app-info"):
        "Name, Version, Quellcode-Link (AGPL §13) und Vereinsname. Muss die "
        "Login-Seite noch vor jeder Anmeldung anzeigen können.",
    ("GET", "/api/branding.css"):
        "Vereinsfarben als CSS. Hängt in der index.html und färbt die Login-Seite.",
}

# Auslieferung des gebauten Frontends. Diese Routen entstehen nur, wenn
# frontend_dist/ existiert (nach `quasar build`), und liefern ausschließlich
# statische Dateien aus dem Build- bzw. Branding-Verzeichnis.
_STATISCH = {"/icons/{datei:path}", "/{full_path:path}", "/assets"}


def _dependency_calls(dependant) -> set:
    """Alle Callables im Dependency-Baum einer Route (rekursiv, ohne Zyklen)."""
    gefunden, offen = set(), [dependant]
    while offen:
        d = offen.pop()
        if d.call is not None:
            gefunden.add(d.call)
        offen.extend(d.dependencies)
    return gefunden


def _routen():
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.path in _STATISCH:
            continue
        for methode in sorted(route.methods - {"HEAD", "OPTIONS"}):
            yield methode, route.path, route


def test_jede_route_verlangt_anmeldung_oder_steht_auf_der_liste():
    offen = [
        f"{methode} {pfad}  ({route.endpoint.__module__}.{route.endpoint.__name__})"
        for methode, pfad, route in _routen()
        if get_current_user not in _dependency_calls(route.dependant)
        and (methode, pfad) not in OEFFENTLICH
    ]
    assert not offen, (
        "Diese Routen sind ohne Anmeldung erreichbar. Entweder fehlt der "
        "CurrentUser-Parameter, oder der Zugang ist gewollt – dann gehört die "
        "Route mit Begründung in OEFFENTLICH:\n  " + "\n  ".join(sorted(offen))
    )


def test_ausnahmeliste_ist_aktuell():
    """Keine Karteileichen: Jeder Eintrag muss eine Route treffen, die wirklich offen ist.

    Sonst bleibt ein Eintrag stehen, nachdem die Route abgesichert oder entfernt
    wurde – und deckt beim nächsten Mal versehentlich etwas anderes ab.
    """
    vorhanden = {
        (methode, pfad)
        for methode, pfad, route in _routen()
        if get_current_user not in _dependency_calls(route.dependant)
    }
    ueberfluessig = sorted(set(OEFFENTLICH) - vorhanden)
    assert not ueberfluessig, (
        f"Einträge in OEFFENTLICH ohne passende offene Route: {ueberfluessig}"
    )


@pytest.mark.parametrize("methode,pfad", sorted(OEFFENTLICH))
def test_ausnahme_hat_eine_begruendung(methode, pfad):
    assert len(OEFFENTLICH[(methode, pfad)].strip()) > 30
