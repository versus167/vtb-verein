"""Eigenständige Seiten unter public/ dürfen nicht im SPA-Fallback landen.

Der Beleg-Scanner (#197) war produktiv unbenutzbar, und niemand hat es an den
Tests gemerkt. Der Ablauf:

1. Der Service Worker registriert eine ``NavigationRoute``, die **jede**
   Navigation mit der precachten ``index.html`` beantwortet.
2. Eine iframe-Navigation ist eine Navigation. Die App bettet den Scanner aber
   genau so ein.
3. Zurück kam also die index.html — samt der Header, mit denen sie im Cache
   liegt: ``frame-ancestors 'none'`` und ``X-Frame-Options: DENY``.
4. Chrome verweigert daraufhin den Rahmen. Der Nutzer sieht eine leere
   Fehlerseite, ohne jeden Hinweis worauf.

Warum das durch jede Prüfung rutschte, ist der eigentliche Lehrsatz: Der Block
steht unter ``if (process.env.PROD)``, greift im Dev-Build also nicht; ``curl``
geht am Service Worker vorbei und bekommt die richtige Datei mit den richtigen
Headern; und ``quasar build`` ohne ``--mode pwa`` baut überhaupt keinen Service
Worker — das Deployment (backend/Dockerfile) aber schon.

Deshalb prüft dieser Test die Regel und nicht den Einzelfall: Jede
eigenständige HTML-Seite unter ``frontend/public/`` muss in der denylist
stehen. Wer die nächste anlegt, bekommt hier einen Fehlschlag statt einer
weißen Seite auf dem Handy eines Vereinsmitglieds.
"""
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_SW = _ROOT / "frontend/src-pwa/custom-service-worker.js"
_PUBLIC = _ROOT / "frontend/public"


def _denylist_muster() -> list[str]:
    """Die regulären Ausdrücke aus der denylist der NavigationRoute."""
    quelle = _SW.read_text(encoding="utf-8")
    block = re.search(r"NICHT_UEBER_DIE_SPA\s*=\s*\[(.*?)\]", quelle, re.S)
    assert block, "denylist der NavigationRoute nicht gefunden"
    return re.findall(r"/((?:[^/\\\n]|\\.)+)/[a-z]*", block.group(1))


def _eigenstaendige_seiten() -> list[str]:
    return sorted(p.name for p in _PUBLIC.glob("*.html"))


def test_es_gibt_ueberhaupt_eine_denylist():
    assert _denylist_muster(), "ohne denylist verschluckt der Fallback alles"


def test_public_hat_die_erwarteten_seiten():
    """Stolperdraht: Kommt eine Seite dazu, fällt der Test unten auf.

    index.html zählt nicht mit — die ist der Fallback selbst und wird von
    Quasar erzeugt, nicht hier abgelegt.
    """
    assert _eigenstaendige_seiten() == ["beleg-scanner.html"]


@pytest.mark.parametrize("seite", _eigenstaendige_seiten())
def test_jede_eigenstaendige_seite_ist_ausgenommen(seite):
    """Sonst beantwortet der Service Worker sie mit der index.html."""
    treffer = [m for m in _denylist_muster()
               if re.search(m.replace("\\\\", "\\"), "/" + seite)]
    assert treffer, (
        f"/{seite} steht nicht in der denylist der NavigationRoute. "
        f"Der Service Worker liefert dafür die index.html aus, und im iframe "
        f"blockiert deren 'frame-ancestors: none' die Anzeige.")


@pytest.mark.parametrize("seite", _eigenstaendige_seiten())
def test_ausnahme_greift_auch_mit_query(seite):
    """NavigationRoute prüft gegen ``pathname + search``.

    Die App hängt ein ``?v=<Version>`` an die Adresse des Scanners (für den
    Cache der Bibliothek). Ein am Ende verankertes Muster (``…\\.html$``) ginge
    daran vorbei und die Regel wäre wirkungslos — genau dort, wo sie zählt.
    """
    treffer = [m for m in _denylist_muster()
               if re.search(m.replace("\\\\", "\\"), f"/{seite}?v=2026.09.10.267")]
    assert treffer, f"/{seite} mit ?v=… fällt wieder in den SPA-Fallback"


def test_deployment_baut_ueberhaupt_eine_pwa():
    """Ohne diesen Modus gibt es keinen Service Worker — und damit auch das
    Problem nicht. Baut das Deployment eines Tages ohne, sind die Tests hier
    gegenstandslos und sollen das sagen, statt still zu bestehen."""
    dockerfile = (_ROOT / "backend/Dockerfile").read_text(encoding="utf-8")
    assert "--mode pwa" in dockerfile
