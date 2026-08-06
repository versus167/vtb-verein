"""Branding-Überlagerung (backend/core/branding.py).

Der Ordner aus ``VTB_BRANDING_PATH`` überlagert die ausgelieferten Icons — je
Datei, nicht alles-oder-nichts. Genau das ist hier die interessante Eigenschaft:
Ein Verein, der nur ein Favicon mitbringt, darf nicht die restlichen 19 Dateien
verlieren, sonst zerfällt das PWA-Manifest.
"""
import sys
from pathlib import Path

# Repo-Wurzel für den backend.*-Import ergänzen (backend/ ist kein app-Paket).
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402

from backend.core import branding  # noqa: E402


@pytest.fixture
def ordner(tmp_path):
    """Ein Branding-Ordner, der nur zwei der zwanzig Dateien mitbringt."""
    (tmp_path / "icons").mkdir()
    (tmp_path / "icons" / "logo-512.png").write_bytes(b"eigenes-logo")
    (tmp_path / "favicon.ico").write_bytes(b"eigenes-favicon")
    return branding.basis_pfad(str(tmp_path))


def test_vorhandene_datei_wird_gefunden(ordner):
    treffer = branding.datei(ordner, "icons/logo-512.png")
    assert treffer is not None
    assert treffer.read_bytes() == b"eigenes-logo"


def test_fehlende_datei_faellt_zurueck(ordner):
    """Der Kern der Sache: Was der Verein nicht mitbringt, liefert None —
    der Aufrufer greift dann auf die ausgelieferte Datei zurück."""
    assert branding.datei(ordner, "icons/icon-192x192.png") is None
    assert branding.datei(ordner, "apple-touch-icon.png") is None


def test_kein_ordner_konfiguriert():
    assert branding.basis_pfad("") is None
    assert branding.basis_pfad(None) is None
    assert branding.datei(None, "favicon.ico") is None


def test_nicht_existierender_ordner_ist_kein_fehler(tmp_path):
    """Ein falsch gesetzter Pfad darf die App nicht lahmlegen, sondern nur dazu
    führen, dass nichts überlagert wird."""
    basis = branding.basis_pfad(str(tmp_path / "gibtsnicht"))
    assert branding.datei(basis, "favicon.ico") is None


def test_verzeichnis_ist_keine_datei(ordner):
    assert branding.datei(ordner, "icons") is None


def test_leerer_pfad(ordner):
    assert branding.datei(ordner, "") is None


@pytest.mark.parametrize("angriff", [
    "../geheim.txt",
    "icons/../../geheim.txt",
    "icons/../../../etc/passwd",
    "/etc/passwd",
])
def test_kein_ausbruch_aus_dem_ordner(ordner, tmp_path, angriff):
    """Pfade, die aus dem Branding-Ordner hinausführen, liefern nichts."""
    (tmp_path.parent / "geheim.txt").write_bytes(b"nicht ausliefern")
    assert branding.datei(ordner, angriff) is None


def test_symlink_nach_draussen_wird_abgewiesen(ordner, tmp_path):
    """resolve() folgt Symlinks — ein Link aus dem Ordner heraus zeigt danach
    außerhalb und fällt beim relative_to durch."""
    ziel = tmp_path.parent / "ausserhalb.png"
    ziel.write_bytes(b"nicht ausliefern")
    (tmp_path / "icons" / "link.png").symlink_to(ziel)
    assert branding.datei(ordner, "icons/link.png") is None


def test_root_dateien_enthalten_die_favicons():
    """Im Wurzelverzeichnis wird nur eine feste Liste überlagert."""
    assert "favicon.ico" in branding.ROOT_DATEIEN
    assert "apple-touch-icon.png" in branding.ROOT_DATEIEN
    assert "browserconfig.xml" in branding.ROOT_DATEIEN


def test_root_dateien_verdecken_die_spa_nicht():
    """index.html gehört ausdrücklich NICHT dazu — sonst könnte eine Datei im
    Branding-Ordner die Anwendung selbst ersetzen."""
    assert "index.html" not in branding.ROOT_DATEIEN
    assert not any(n.endswith((".js", ".html")) for n in branding.ROOT_DATEIEN)


def test_mitgelieferter_vtb_satz_ist_vollstaendig():
    """branding/vtb/ ist der Beispielsatz und zugleich das VTB-Branding: Er muss
    jede Datei enthalten, die auch ausgeliefert wird — sonst zeigt die
    VTB-Instanz an einzelnen Stellen die neutrale Wortmarke."""
    vtb = _ROOT / "branding" / "vtb"
    public = _ROOT / "frontend" / "public"
    erwartet = {p.relative_to(public).as_posix()
                for p in public.rglob("*")
                if p.is_file() and (p.parent.name == "icons" or p.name in branding.ROOT_DATEIEN)}
    vorhanden = {p.relative_to(vtb).as_posix() for p in vtb.rglob("*") if p.is_file()}
    assert not (erwartet - vorhanden), (
        "Im VTB-Branding fehlen Dateien, die ausgeliefert werden: "
        + ", ".join(sorted(erwartet - vorhanden))
    )
