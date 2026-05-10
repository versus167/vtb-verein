"""
Tests für KassenbuchungAnhangRepository – CRUD und stored_name-Logik
"""
import pytest
from app.db.datastore import VereinsDB
from app.models.kasse import KassenbuchungAnhang, Kasse, Kassenbuchung


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / 'test.db')
    db = VereinsDB(db_path, upload_path=str(tmp_path / 'uploads'))

    kasse = db.kassenbuch.create_kasse(
        Kasse(name='Testkasse', anfangsbestand_cent=10000),
        created_by='system',
    )
    db.kassenbuch.create_buchung(
        Kassenbuchung(
            kasse_id=kasse.id,
            buchungsdatum='2026-01-01',
            buchungstext='Testbuchung',
            kategorie='Allgemein',
            einnahme_cent=500,
        ),
        created_by='system',
        is_admin=True,
    )

    yield db
    db.close()


BUCHUNG_ID = 1


class TestStoredName:

    def test_create_setzt_kabu_prefix(self, db):
        anhang = KassenbuchungAnhang(
            buchung_id=BUCHUNG_ID,
            original_name='quittung.jpg',
            mime_type='image/jpeg',
            dateigroesse=1024,
            hochgeladen_von=1,
        )
        result = db._kassenbuchung_anhang_repo.create(anhang)
        assert result.stored_name == f'kabu_{result.id:06d}.jpg'

    def test_create_pdf_endung(self, db):
        anhang = KassenbuchungAnhang(
            buchung_id=BUCHUNG_ID,
            original_name='rechnung.pdf',
            mime_type='application/pdf',
            dateigroesse=2048,
            hochgeladen_von=1,
        )
        result = db._kassenbuchung_anhang_repo.create(anhang)
        assert result.stored_name.endswith('.pdf')
        assert result.stored_name.startswith('kabu_')

    def test_create_grosse_schreibweise_normalisiert(self, db):
        anhang = KassenbuchungAnhang(
            buchung_id=BUCHUNG_ID,
            original_name='FOTO.JPG',
            mime_type='image/jpeg',
            dateigroesse=512,
            hochgeladen_von=1,
        )
        result = db._kassenbuchung_anhang_repo.create(anhang)
        assert result.stored_name.endswith('.jpg')


class TestFelder:

    def test_create_gibt_alle_felder_zurueck(self, db):
        anhang = KassenbuchungAnhang(
            buchung_id=BUCHUNG_ID,
            original_name='beleg.png',
            mime_type='image/png',
            dateigroesse=300,
            hochgeladen_von=1,
        )
        result = db._kassenbuchung_anhang_repo.create(anhang)

        assert result.id is not None
        assert result.buchung_id == BUCHUNG_ID
        assert result.original_name == 'beleg.png'
        assert result.mime_type == 'image/png'
        assert result.dateigroesse == 300
        assert result.hochgeladen_von == 1
        assert result.hochgeladen_am is not None
        assert result.deleted_at is None


class TestListByBuchung:

    def test_gibt_anhaenge_zurueck(self, db):
        for name in ['a.jpg', 'b.png']:
            db._kassenbuchung_anhang_repo.create(KassenbuchungAnhang(
                buchung_id=BUCHUNG_ID, original_name=name,
                mime_type='image/jpeg', dateigroesse=100, hochgeladen_von=1,
            ))
        result = db._kassenbuchung_anhang_repo.list_by_buchung(BUCHUNG_ID)
        assert len(result) == 2

    def test_filtert_geloeschte(self, db):
        anhang = db._kassenbuchung_anhang_repo.create(KassenbuchungAnhang(
            buchung_id=BUCHUNG_ID, original_name='c.jpg',
            mime_type='image/jpeg', dateigroesse=100, hochgeladen_von=1,
        ))
        db._kassenbuchung_anhang_repo.mark_deleted(anhang.id, 'tester')
        result = db._kassenbuchung_anhang_repo.list_by_buchung(BUCHUNG_ID)
        assert all(a.id != anhang.id for a in result)

    def test_leere_liste_fuer_unbekannte_buchung(self, db):
        result = db._kassenbuchung_anhang_repo.list_by_buchung(99999)
        assert result == []


class TestGet:

    def test_get_gibt_anhang_zurueck(self, db):
        created = db._kassenbuchung_anhang_repo.create(KassenbuchungAnhang(
            buchung_id=BUCHUNG_ID, original_name='x.jpg',
            mime_type='image/jpeg', dateigroesse=200, hochgeladen_von=1,
        ))
        fetched = db._kassenbuchung_anhang_repo.get(created.id)
        assert fetched is not None
        assert fetched.original_name == 'x.jpg'
        assert fetched.buchung_id == BUCHUNG_ID

    def test_get_unbekannte_id_gibt_none(self, db):
        assert db._kassenbuchung_anhang_repo.get(99999) is None


class TestMarkDeleted:

    def test_soft_delete_setzt_deleted_at(self, db):
        anhang = db._kassenbuchung_anhang_repo.create(KassenbuchungAnhang(
            buchung_id=BUCHUNG_ID, original_name='d.jpg',
            mime_type='image/jpeg', dateigroesse=50, hochgeladen_von=1,
        ))
        ok = db._kassenbuchung_anhang_repo.mark_deleted(anhang.id, 'admin')
        assert ok is True
        fetched = db._kassenbuchung_anhang_repo.get(anhang.id)
        assert fetched.deleted_at is not None
        assert fetched.deleted_by == 'admin'

    def test_doppeltes_loeschen_gibt_false(self, db):
        anhang = db._kassenbuchung_anhang_repo.create(KassenbuchungAnhang(
            buchung_id=BUCHUNG_ID, original_name='e.jpg',
            mime_type='image/jpeg', dateigroesse=50, hochgeladen_von=1,
        ))
        db._kassenbuchung_anhang_repo.mark_deleted(anhang.id, 'admin')
        result = db._kassenbuchung_anhang_repo.mark_deleted(anhang.id, 'admin')
        assert result is False
