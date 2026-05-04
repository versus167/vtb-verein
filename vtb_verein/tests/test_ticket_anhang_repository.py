"""
Tests für TicketAnhangRepository – Bug-Fix-Verifikation + CRUD
"""
import os
import tempfile
import pytest
from app.db.datastore import VereinsDB
from app.models.ticket import TicketAnhang


@pytest.fixture
def db(tmp_path):
    from app.models.ticket import TicketBereich, Ticket, TicketStatus, TicketPrioritaet

    db_path = str(tmp_path / 'test.db')
    db = VereinsDB(db_path, upload_path=str(tmp_path / 'uploads'))
    # VereinsDB legt automatisch Admin-User (id=1) an.

    # Bereich + Ticket via Service anlegen (korrekte updated_by-Felder etc.)
    bereich = db.ticket_bereiche.create(TicketBereich(name='Testbereich'), created_by='system')
    db.tickets.create_ticket(
        Ticket(
            titel='Testticket',
            status=TicketStatus.OFFEN,
            prioritaet=TicketPrioritaet.NORMAL,
            bereich_id=bereich.id,
            gemeldet_von=1,
        ),
        created_by='system',
    )

    yield db
    db.close()


class TestStoredName:

    def test_create_setzt_stored_name_korrekt(self, db):
        anhang = TicketAnhang(
            ticket_id=1,
            original_name='foto.jpg',
            mime_type='image/jpeg',
            dateigroesse=1024,
            hochgeladen_von=1,
        )
        result = db._ticket_anhang_repo.create(anhang)
        assert result.stored_name == f'att_{result.id:06d}.jpg'

    def test_create_pdf_endung(self, db):
        anhang = TicketAnhang(
            ticket_id=1,
            original_name='beleg.pdf',
            mime_type='application/pdf',
            dateigroesse=2048,
            hochgeladen_von=1,
        )
        result = db._ticket_anhang_repo.create(anhang)
        assert result.stored_name.endswith('.pdf')


class TestFeldnamen:

    def test_map_gibt_deutsche_feldnamen_zurueck(self, db):
        anhang = TicketAnhang(
            ticket_id=1,
            kommentar_id=None,
            original_name='test.png',
            mime_type='image/png',
            dateigroesse=512,
            hochgeladen_von=1,
        )
        result = db._ticket_anhang_repo.create(anhang)

        # Verifikation des Bug-Fixes: deutsche Feldnamen müssen gesetzt sein
        assert result.kommentar_id is None
        assert result.dateigroesse == 512
        assert result.hochgeladen_von == 1
        assert result.hochgeladen_am is not None

        # Verifikation dass englische Aliase nicht mehr vorhanden sind
        assert not hasattr(result, 'comment_id')
        assert not hasattr(result, 'file_size')
        assert not hasattr(result, 'uploaded_by')
        assert not hasattr(result, 'uploaded_at')


class TestListByTicket:

    def test_list_by_ticket_gibt_anhaenge_zurueck(self, db):
        for name in ['a.jpg', 'b.png']:
            db._ticket_anhang_repo.create(TicketAnhang(
                ticket_id=1, original_name=name, mime_type='image/jpeg',
                dateigroesse=100, hochgeladen_von=1,
            ))
        result = db._ticket_anhang_repo.list_by_ticket(1)
        assert len(result) == 2

    def test_list_filtert_geloeschte(self, db):
        anhang = db._ticket_anhang_repo.create(TicketAnhang(
            ticket_id=1, original_name='c.jpg', mime_type='image/jpeg',
            dateigroesse=100, hochgeladen_von=1,
        ))
        db._ticket_anhang_repo.mark_deleted(anhang.id, 'tester')
        result = db._ticket_anhang_repo.list_by_ticket(1)
        assert all(a.id != anhang.id for a in result)


class TestGet:

    def test_get_gibt_anhang_zurueck(self, db):
        created = db._ticket_anhang_repo.create(TicketAnhang(
            ticket_id=1, original_name='x.jpg', mime_type='image/jpeg',
            dateigroesse=200, hochgeladen_von=1,
        ))
        fetched = db._ticket_anhang_repo.get(created.id)
        assert fetched is not None
        assert fetched.original_name == 'x.jpg'

    def test_get_nicht_vorhandene_id(self, db):
        assert db._ticket_anhang_repo.get(99999) is None
