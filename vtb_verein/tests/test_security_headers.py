"""Sicherheits-Header, insbesondere die Content-Security-Policy.

Die Richtlinie ist Tiefenverteidigung: Das Frontend benutzt kein `v-html`, es gibt
also heute keine bekannte XSS-Fläche. Sie soll die Folgen begrenzen, falls doch
einmal eine entsteht — und genau deshalb muss sie zu dem passen, was die App
tatsächlich lädt. Eine zu strenge Richtlinie fällt sofort auf (weiße Seite), eine
zu lasche nie. Hier steht deshalb, warum jede Lockerung drin ist.
"""
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    # Ohne `with`: kein Lifespan, also keine DB nötig – /api/health kommt ohne aus.
    return TestClient(app)


def _csp(client, pfad="/api/health"):
    return client.get(pfad).headers.get("Content-Security-Policy", "")


def _direktive(csp, name):
    treffer = re.search(rf"(?:^|; ){re.escape(name)} ([^;]*)", csp)
    return treffer.group(1).strip() if treffer else None


def test_csp_wird_ausgeliefert(client):
    assert _csp(client)


def test_skripte_nur_aus_eigener_herkunft(client):
    """Der eigentliche Gewinn: Eingeschleuster Code kann weder nachladen noch
    inline laufen. Der Build macht das gratis – die index.html enthält kein
    Inline-Script und keinen Fremd-Host."""
    assert _direktive(_csp(client), "script-src") == "'self'"


def test_keine_fremden_einbettungen_und_objekte(client):
    csp = _csp(client)
    assert _direktive(csp, "object-src") == "'none'"
    assert _direktive(csp, "frame-ancestors") == "'none'"


def test_basis_und_formularziel_sind_festgenagelt(client):
    """base-uri verhindert, dass ein eingeschleustes <base> alle relativen Pfade
    umlenkt; form-action, dass ein Formular woanders hin abgeschickt wird."""
    csp = _csp(client)
    assert _direktive(csp, "base-uri") == "'self'"
    assert _direktive(csp, "form-action") == "'self'"


def test_anhang_vorschau_bleibt_moeglich(client):
    """AnhangPanel baut Bilder und PDFs aus Blob-URLs. Ohne blob: bliebe die
    Vorschau leer – eine Richtlinie, die die App kaputtmacht, wird wieder
    entfernt und schützt dann gar nichts."""
    csp = _csp(client)
    assert "blob:" in _direktive(csp, "img-src")
    assert "blob:" in _direktive(csp, "frame-src")


def test_eingebettete_bilder_aus_dem_css_bleiben_moeglich(client):
    """Das gebaute CSS enthält data:image/png-Icons."""
    assert "data:" in _direktive(_csp(client), "img-src")


def test_stile_duerfen_inline_sein_skripte_nicht(client):
    """Das bewusste Zugeständnis: Vue/Quasar setzen Stil-Attribute. Für Skripte
    gilt es ausdrücklich nicht – dort wäre der Hebel ungleich größer."""
    csp = _csp(client)
    assert "'unsafe-inline'" in _direktive(csp, "style-src")
    assert "'unsafe-inline'" not in _direktive(csp, "script-src")
    assert "'unsafe-eval'" not in csp


def test_api_dokumentation_bleibt_ausgenommen(client):
    """Swagger lädt sein JavaScript von einem CDN. Statt das CDN für die ganze
    App freizugeben, entfällt die Richtlinie auf diesen beiden Seiten – sie
    zeigen keine Nutzerdaten, sondern die eigene API-Beschreibung."""
    assert _csp(client, "/api/docs") == ""
    assert _csp(client, "/api/redoc") == ""


def test_uebrige_sicherheits_header_bleiben(client):
    kopf = client.get("/api/health").headers
    assert kopf["X-Content-Type-Options"] == "nosniff"
    assert kopf["X-Frame-Options"] == "DENY"
    assert kopf["Referrer-Policy"] == "strict-origin-when-cross-origin"


def test_gebautes_frontend_kaeme_ohne_lockerung_aus(client):
    """Wächter gegen späteres Auseinanderlaufen: Sobald der Build ein
    Inline-Script oder einen Fremd-Host einführt, bricht `script-src 'self'` die
    App — dann muss diese Entscheidung neu getroffen werden, nicht die Richtlinie
    stillschweigend aufgeweicht.
    """
    index = _ROOT / "frontend" / "dist" / "spa" / "index.html"
    if not index.is_file():
        pytest.skip("kein gebautes Frontend vorhanden")
    html = index.read_text()
    # <script> ohne src = Inline-Code
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), "Inline-Script im Build"
    fremde = [u for u in re.findall(r'(?:src|href)="(https?://[^"]+)"', html)]
    assert fremde == [], f"Fremd-Host im Build: {fremde}"
