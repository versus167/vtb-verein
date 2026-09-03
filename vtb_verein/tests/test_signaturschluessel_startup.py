"""Die App startet nicht mit fälschbaren Session-Tokens.

VTB_SECRET_KEY fiel bisher stillschweigend auf den Platzhalter
'CHANGE_ME_IN_PRODUCTION' zurück — einen Wert, der im öffentlichen Quellcode
steht. Damit kann sich jeder ein gültiges Token für jedes Konto ausstellen, und
der Widerruf angemeldeter Geräte greift nicht dagegen: Token ohne Session-ID
werden in core/deps.py bewusst geduldet (Altbestand). Eine Instanz, bei der die
Env-Variable vergessen wurde, lief also offen weiter, ohne dass irgendetwas
darauf hinwies.

Geprüft wird die Startup-Wache, nicht die Token-Erzeugung: Sie muss bei fehlendem
und bei Platzhalter-Schlüssel abbrechen, bei einem echten Schlüssel durchlassen
und einen kurzen Schlüssel nur bemängeln, nicht abweisen.
"""
import sys
from pathlib import Path

import pytest

# Repo-Wurzel für den backend.*-Import ergänzen (backend/ ist kein app-Paket).
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.core.config import settings  # noqa: E402
from backend.core.security import pruefe_signaturschluessel  # noqa: E402

_ECHT = "Nx7pQ2vK9mR4wL8jT3sB6hF1cY5aZ0dE7gU2iO4nV6xW"  # 44 Zeichen, wie token_urlsafe(33)


@pytest.mark.parametrize("wert", ["", "   ", settings.SECRET_KEY_PLATZHALTER])
def test_start_bricht_ohne_eigenen_schluessel_ab(monkeypatch, wert):
    monkeypatch.setattr(settings, "SECRET_KEY", wert)
    with pytest.raises(RuntimeError, match="VTB_SECRET_KEY"):
        pruefe_signaturschluessel()


def test_meldung_nennt_den_weg_zum_eigenen_schluessel(monkeypatch):
    """Wer hier steht, soll nicht erst suchen müssen, was zu tun ist."""
    monkeypatch.setattr(settings, "SECRET_KEY", settings.SECRET_KEY_PLATZHALTER)
    with pytest.raises(RuntimeError) as fehler:
        pruefe_signaturschluessel()
    text = str(fehler.value)
    assert "token_urlsafe" in text          # der Erzeugungsbefehl
    assert "meldet alle angemeldeten Nutzer" in text   # die Nebenwirkung


def test_echter_schluessel_laesst_starten(monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", _ECHT)
    pruefe_signaturschluessel()   # kein Abbruch


def test_kurzer_schluessel_warnt_nur(monkeypatch, caplog):
    """Ein kurzer Zufallswert ist schwach, aber nicht öffentlich bekannt.

    Der Unterschied ist der ganze Punkt: Beim Platzhalter kennt der Angreifer den
    Wert, hier muss er ihn raten. Eine Instanz beim Deploy dafür anzuhalten wäre
    die größere Störung — also Warnung statt Abbruch.
    """
    monkeypatch.setattr(settings, "SECRET_KEY", "kurz-aber-zufaellig")
    with caplog.at_level("WARNING", logger="app"):
        pruefe_signaturschluessel()   # kein Abbruch
    assert any("VTB_SECRET_KEY" in eintrag.message for eintrag in caplog.records)


# Bewusst kein Test darauf, dass der Settings-Default gleich dem Platzhalter ist:
# Beides ist dieselbe Konstante (`os.getenv(..., SECRET_KEY_PLATZHALTER)`), ein
# Auseinanderlaufen also konstruktiv ausgeschlossen. Beobachtbar wäre es nur über
# ein neu geladenes Config-Modul — und dessen frisches Settings-Objekt bringt
# Tests durcheinander, die ihre eigene, beim Import gebundene Referenz patchen
# (test_vault_crypto).
