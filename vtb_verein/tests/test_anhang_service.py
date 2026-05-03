"""
Tests für AnhangService – File I/O, Validierung, Atomizität
"""
import io
import os
import tempfile
import pytest
from pathlib import Path
from app.services.anhang_service import (
    AnhangService, DateitypNichtErlaubtError, DateiZuGrossError
)


@pytest.fixture
def upload_dir(tmp_path):
    return tmp_path / 'uploads'


@pytest.fixture
def service(upload_dir):
    return AnhangService(upload_path=str(upload_dir), max_mb=10)


class TestValidierung:

    def test_erlaubter_typ_jpeg(self, service):
        service.validiere('image/jpeg', 100)  # kein Exception

    def test_erlaubter_typ_pdf(self, service):
        service.validiere('application/pdf', 1024 * 1024)  # kein Exception

    def test_verbotener_typ_wirft_exception(self, service):
        with pytest.raises(DateitypNichtErlaubtError):
            service.validiere('text/html', 100)

    def test_verbotener_typ_docx(self, service):
        with pytest.raises(DateitypNichtErlaubtError):
            service.validiere('application/vnd.openxmlformats-officedocument.wordprocessingml.document', 100)

    def test_zu_gross_wirft_exception(self, service):
        elf_mb = 11 * 1024 * 1024
        with pytest.raises(DateiZuGrossError):
            service.validiere('image/jpeg', elf_mb)

    def test_genau_am_limit_erlaubt(self, service):
        zehn_mb = 10 * 1024 * 1024
        service.validiere('image/png', zehn_mb)  # kein Exception

    def test_einen_byte_ueber_limit(self, service):
        with pytest.raises(DateiZuGrossError):
            service.validiere('image/png', 10 * 1024 * 1024 + 1)


class TestSchreibenUndLesen:

    def test_schreibe_bytes_und_lese_zurueck(self, service):
        data = b'hello world'
        service.schreibe('test.jpg', data)
        assert service.lese('test.jpg') == data

    def test_schreibe_bytesio(self, service):
        data = b'\x89PNG\r\n\x1a\n'  # PNG-Header
        service.schreibe('bild.png', io.BytesIO(data))
        assert service.lese('bild.png') == data

    def test_lese_nicht_vorhandene_datei(self, service):
        assert service.lese('gibts_nicht.jpg') is None

    def test_existiert_nach_schreiben(self, service):
        service.schreibe('da.jpg', b'data')
        assert service.existiert('da.jpg')

    def test_existiert_nicht_vor_schreiben(self, service):
        assert not service.existiert('noch_nicht.jpg')

    def test_get_pfad(self, service, upload_dir):
        pfad = service.get_pfad('att_000001.pdf')
        assert pfad == upload_dir / 'att_000001.pdf'

    def test_upload_verzeichnis_wird_erstellt(self, tmp_path):
        nested = tmp_path / 'a' / 'b' / 'c'
        svc = AnhangService(upload_path=str(nested), max_mb=5)
        assert nested.is_dir()


class TestAtomizitaet:

    def test_kein_orphan_bei_schreibfehler(self, service, upload_dir, monkeypatch):
        upload_dir.mkdir(parents=True, exist_ok=True)

        def kaputtes_rename(self, dst):
            raise OSError("Disk voll")

        monkeypatch.setattr(Path, 'rename', kaputtes_rename)

        with pytest.raises(IOError):
            service.schreibe('att_000001.jpg', b'foto')

        # Weder finale noch temp-Datei soll übrig bleiben
        assert not (upload_dir / 'att_000001.jpg').exists()
        assert not (upload_dir / 'att_000001.jpg.tmp').exists()


class TestLoeschen:

    def test_loesche_vorhandene_datei(self, service):
        service.schreibe('del_me.pdf', b'pdf')
        assert service.loesche('del_me.pdf') is True
        assert not service.existiert('del_me.pdf')

    def test_loesche_nicht_vorhandene_datei_gibt_false(self, service):
        assert service.loesche('nicht_da.pdf') is False

    def test_loesche_wirft_keine_exception(self, service):
        # Darf nicht werfen, auch bei fehlender Datei
        service.loesche('xyz.jpg')
