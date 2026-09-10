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
    Inline-Script und keinen Fremd-Host.

    Kein eval, in keiner Form. Der Beleg-Scanner braucht es, bekommt es aber
    nur in seinem eigenen Dokument (s. die Scanner-Tests unten)."""
    assert _direktive(_csp(client), "script-src") == "'self'"
    assert "eval" not in _csp(client)


# --- Beleg-Scanner: gelockert, aber nur dort (Ticket #197) ------------------
#
# Der Scanner erkennt die Belegkanten mit OpenCV.js. Dessen Anbindungsschicht
# baut Funktionen zur Laufzeit aus Zeichenketten und holt das WebAssembly aus
# einer data:-URI. Gemessen mit Headless-Chrome am 09.09.2026: Unter
# `script-src 'self'` bricht die Bibliothek mit EvalError ab, mit
# 'wasm-unsafe-eval' ebenso — das Schlüsselwort deckt echtes eval nicht ab.
# Sie läuft erst mit 'unsafe-eval' UND `connect-src data:`.
#
# Deshalb liegt der Scanner in einem eigenen Dokument, das die App einbettet.
# Diese Tests halten fest, dass die Lockerung genau dort endet.

SCANNER = "/beleg-scanner.html"


def test_scanner_dokument_darf_eval(client):
    """Ohne diese beiden Lockerungen startet OpenCV.js gar nicht."""
    csp = _csp(client, SCANNER)
    assert "'unsafe-eval'" in _direktive(csp, "script-src")
    assert "data:" in _direktive(csp, "connect-src")


def test_scanner_lockerung_gilt_nirgends_sonst(client):
    """Die Kernaussage dieser Bauweise: Der Rest der App bleibt streng.

    Sonst hätte man sich das eigene Dokument sparen und die Richtlinie gleich
    überall aufmachen können — auch auf den Seiten mit Mitglieder-, Kassen-
    und Tresordaten.
    """
    for pfad in ("/api/health", "/", "/rechnungen"):
        csp = _csp(client, pfad)
        assert "eval" not in csp, pfad
        assert "data:" not in _direktive(csp, "connect-src"), pfad


def test_scanner_bleibt_ohne_blob_und_fremde_herkunft(client):
    """Auch die gelockerte Richtlinie gibt nur das Nötige her.

    `blob:` bleibt draußen, obwohl der Lader des ERP es bräuchte — genau
    darüber baut sich eine XSS-Lücke zu Skriptausführung aus. Der Lader in
    public/vendor/beleg-scan.js hängt die Bibliothek deshalb als normales
    <script src> ein.
    """
    script_src = _direktive(_csp(client, SCANNER), "script-src")
    assert "blob:" not in script_src
    assert "http" not in script_src  # kein CDN, die Bibliothek liegt bei uns


def test_scanner_darf_nur_von_uns_eingebettet_werden(client):
    """Der Rahmen ist die Grenze der Lockerung — fremde Seiten dürfen das
    Dokument nicht einbetten, sonst liehen sie sich unsere Kamera-Erlaubnis.

    Passend dazu erlaubt die App-Richtlinie `frame-src 'self'`, sonst bliebe
    der Rahmen leer.
    """
    assert _direktive(_csp(client, SCANNER), "frame-ancestors") == "'self'"
    assert client.get(SCANNER).headers["X-Frame-Options"] == "SAMEORIGIN"
    assert "'self'" in _direktive(_csp(client), "frame-src")


def test_uebrige_seiten_bleiben_uneinbettbar(client):
    """Für alles andere gilt weiter: gar kein Rahmen, von niemandem."""
    assert _direktive(_csp(client), "frame-ancestors") == "'none'"
    assert client.get("/api/health").headers["X-Frame-Options"] == "DENY"


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
