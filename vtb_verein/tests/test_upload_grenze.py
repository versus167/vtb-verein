"""Uploads werden gestückelt eingelesen und brechen an der Grenze ab.

`await file.read()` ohne Argument zog die komplette Datei in einem Zug in den
Speicher — und zwar *bevor* die Größenprüfung laufen konnte. Starlette hilft
dabei nicht: Sein `max_part_size` greift nur bei Textfeldern, Datei-Parts wandern
unbegrenzt in eine Temp-Datei. Ohne Grenze im Reverse-Proxy gab es also gar keine,
und ein einzelner großer Upload konnte den Container über sein Speicherlimit
drücken.

Der Kern dieser Tests ist deshalb nicht „zu groß wird abgelehnt" — das tat die
alte Prüfung auch —, sondern **wann**: Es muss beim Lesen abgebrochen werden,
nicht danach. Sonst ist die Datei längst im Speicher, und die Ablehnung kommt zu
spät, um noch etwas zu schützen.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402

from app.services.anhang_service import AnhangService, DateiZuGrossError  # noqa: E402
from backend.api.uploads import lese_upload  # noqa: E402


class _FakeUpload:
    """Upload-Attrappe, die mitzählt, wie viel wirklich gelesen wurde.

    Genau darum geht es: Ein Abbruch nützt nur, wenn er passiert, *bevor* alles
    durch den Speicher gelaufen ist.
    """

    def __init__(self, groesse: int):
        self.groesse = groesse
        self.gelesen = 0

    async def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = self.groesse - self.gelesen
        rest = self.groesse - self.gelesen
        happen = min(size, rest)
        self.gelesen += happen
        return b"x" * happen


@pytest.mark.anyio
async def test_datei_unter_der_grenze_kommt_vollstaendig_an():
    datei = _FakeUpload(300_000)
    inhalt = await lese_upload(datei, 1_000_000)
    assert len(inhalt) == 300_000


@pytest.mark.anyio
async def test_leere_datei_ergibt_leere_bytes():
    assert await lese_upload(_FakeUpload(0), 1_000_000) == b""


@pytest.mark.anyio
async def test_datei_genau_auf_der_grenze_ist_noch_erlaubt():
    inhalt = await lese_upload(_FakeUpload(1_000_000), 1_000_000)
    assert len(inhalt) == 1_000_000


@pytest.mark.anyio
async def test_zu_grosse_datei_wird_abgelehnt():
    with pytest.raises(DateiZuGrossError):
        await lese_upload(_FakeUpload(2_000_000), 1_000_000)


@pytest.mark.anyio
async def test_abbruch_erfolgt_beim_lesen_nicht_danach():
    """Der eigentliche Punkt: Von einer 500-MB-Datei darf nur ein Wimpernschlag
    über der Grenze durch den Speicher gelaufen sein, nicht alles."""
    datei = _FakeUpload(500 * 1024 * 1024)
    grenze = 10 * 1024 * 1024
    with pytest.raises(DateiZuGrossError):
        await lese_upload(datei, grenze)
    assert datei.gelesen <= grenze + 64 * 1024, (
        f"{datei.gelesen} Bytes gelesen – der Abbruch kam zu spät"
    )
    assert datei.gelesen < datei.groesse / 10


@pytest.mark.anyio
async def test_meldung_nennt_die_grenze_in_mb():
    with pytest.raises(DateiZuGrossError) as e:
        await lese_upload(_FakeUpload(20 * 1024 * 1024), 10 * 1024 * 1024)
    assert "10 MB" in str(e.value)


def test_anhang_service_gibt_die_grenze_in_bytes_heraus():
    """Die Endpunkte brauchen die Grenze in Bytes, nicht gerundet in MB."""
    dienst = AnhangService("/tmp/vtb-grenze-test", max_mb=7)
    assert dienst.max_bytes == 7 * 1024 * 1024
    assert dienst.max_mb == 7


def test_import_grenze_ist_groesser_als_die_anhang_grenze():
    """Ein Jahresexport des Zutrittslogs ist größer als ein Belegfoto – wären
    beide gleich, würde die Grenze im Alltag stören statt zu schützen."""
    import os
    from backend.core.config import settings
    anhang_mb = int(os.getenv("VTB_MAX_UPLOAD_MB", "10"))
    assert settings.MAX_IMPORT_MB > anhang_mb


@pytest.fixture
def anyio_backend():
    return "asyncio"
