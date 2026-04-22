"""
Tests für den UserService - Schutz des letzten aktiven Admins
"""
import pytest
import os
import tempfile
from app.services.user_service import UserService
from app.db.datastore import VereinsDB


class TestLastAdminProtection:
    """Tests für den Schutz des letzten aktiven Administrators"""
    
    @pytest.fixture
    def db(self):
        """Erstellt temporäre Testdatenbank"""
        # Temporäre Datei für Test-DB
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        
        # VereinsDB initialisiert sich selbst beim Erstellen
        # und legt automatisch Standard-Admin an
        db = VereinsDB(db_path)
        
        # Standard-Admin löschen, damit Tests mit sauberem Zustand starten
        # Wichtig: Auch History löschen, da DELETE-Trigger sonst Constraint verletzt
        with db.cursor() as cur:
            cur.execute("DELETE FROM users_history")
            cur.execute("DELETE FROM users")
        
        yield db
        
        # Cleanup
        db.close()
        if os.path.exists(db_path):
            os.remove(db_path)
    
    @pytest.fixture
    def user_service(self, db):
        """Erstellt UserService-Instanz mit Test-DB"""
        return UserService(db)
    
    def test_single_admin_role_change_blocked(self, user_service):
        """
        Test: 1 aktiver Admin, Änderung Rolle ADMIN → BEARBEITER
        Erwartet: Request wird mit Fehler abgelehnt
        """
        # Arrange: Erstelle einen einzigen aktiven Admin
        admin = user_service.create(
            username="admin1",
            email="admin1@example.com",
            password="password123",
            role="admin",
            created_by="system",
            active=True
        )
        
        # Verifiziere Ausgangszustand
        assert user_service.count_active_admins() == 1
        
        # Act & Assert: Versuch, Rolle zu ändern, sollte fehlschlagen
        with pytest.raises(ValueError) as exc_info:
            user_service.update(
                user_id=admin.id,
                username=admin.username,
                email=admin.email,
                role="user",
                active=admin.active,
                updated_by="system",
                expected_version=admin.version
            )
        
        assert "letzte aktive Administrator" in str(exc_info.value)
        assert "herabgestuft" in str(exc_info.value)
        
        # Verifiziere, dass sich nichts geändert hat
        updated_admin = user_service.get_by_id(admin.id)
        assert updated_admin.role == "admin"
        assert updated_admin.active is True
        assert user_service.count_active_admins() == 1
    
    def test_single_admin_deactivation_blocked(self, user_service):
        """
        Test: 1 aktiver Admin, Änderung active: true → false
        Erwartet: Request wird mit Fehler abgelehnt
        """
        # Arrange: Erstelle einen einzigen aktiven Admin
        admin = user_service.create(
            username="admin1",
            email="admin1@example.com",
            password="password123",
            role="admin",
            created_by="system",
            active=True
        )
        
        # Verifiziere Ausgangszustand
        assert user_service.count_active_admins() == 1
        
        # Act & Assert: Versuch, Admin zu deaktivieren, sollte fehlschlagen
        with pytest.raises(ValueError) as exc_info:
            user_service.update(
                user_id=admin.id,
                username=admin.username,
                email=admin.email,
                role=admin.role,
                active=False,
                updated_by="system",
                expected_version=admin.version
            )
        
        assert "letzte aktive Administrator" in str(exc_info.value)
        assert "deaktiviert" in str(exc_info.value)
        
        # Verifiziere, dass sich nichts geändert hat
        updated_admin = user_service.get_by_id(admin.id)
        assert updated_admin.role == "admin"
        assert updated_admin.active is True
        assert user_service.count_active_admins() == 1
    
    def test_two_admins_role_change_allowed(self, user_service):
        """
        Test: 2 aktive Admins, einer wird herabgestuft
        Erwartet: Operation ist erlaubt
        """
        # Arrange: Erstelle zwei aktive Admins
        admin1 = user_service.create(
            username="admin1",
            email="admin1@example.com",
            password="password123",
            role="admin",
            created_by="system",
            active=True
        )
        
        admin2 = user_service.create(
            username="admin2",
            email="admin2@example.com",
            password="password123",
            role="admin",
            created_by="system",
            active=True
        )
        
        # Verifiziere Ausgangszustand
        assert user_service.count_active_admins() == 2
        
        # Act: Ändere Rolle von admin2 zu user
        success = user_service.update(
            user_id=admin2.id,
            username=admin2.username,
            email=admin2.email,
            role="user",
            active=admin2.active,
            updated_by="system",
            expected_version=admin2.version
        )
        assert success is True
        
        # Hole aktualisiertes Objekt
        updated_admin2 = user_service.get_by_id(admin2.id)
        
        # Assert: Änderung sollte erfolgreich sein
        assert updated_admin2.role == "user"
        assert updated_admin2.active is True
        assert user_service.count_active_admins() == 1
        
        # Admin1 sollte unverändert sein
        admin1_check = user_service.get_by_id(admin1.id)
        assert admin1_check.role == "admin"
        assert admin1_check.active is True
    
    def test_two_admins_deactivation_allowed(self, user_service):
        """
        Test: 2 aktive Admins, einer wird deaktiviert
        Erwartet: Operation ist erlaubt
        """
        # Arrange: Erstelle zwei aktive Admins
        admin1 = user_service.create(
            username="admin1",
            email="admin1@example.com",
            password="password123",
            role="admin",
            created_by="system",
            active=True
        )
        
        admin2 = user_service.create(
            username="admin2",
            email="admin2@example.com",
            password="password123",
            role="admin",
            created_by="system",
            active=True
        )
        
        # Verifiziere Ausgangszustand
        assert user_service.count_active_admins() == 2
        
        # Act: Deaktiviere admin2
        success = user_service.update(
            user_id=admin2.id,
            username=admin2.username,
            email=admin2.email,
            role=admin2.role,
            active=False,
            updated_by="system",
            expected_version=admin2.version
        )
        assert success is True
        
        # Hole aktualisiertes Objekt
        updated_admin2 = user_service.get_by_id(admin2.id)
        
        # Assert: Änderung sollte erfolgreich sein
        assert updated_admin2.role == "admin"
        assert updated_admin2.active is False
        assert user_service.count_active_admins() == 1
        
        # Admin1 sollte unverändert sein
        admin1_check = user_service.get_by_id(admin1.id)
        assert admin1_check.role == "admin"
        assert admin1_check.active is True
    
    def test_single_admin_combined_change_blocked(self, user_service):
        """
        Test: 1 aktiver Admin, gleichzeitige Änderung von Rolle UND Status
        Erwartet: Request wird mit Fehler abgelehnt
        """
        # Arrange: Erstelle einen einzigen aktiven Admin
        admin = user_service.create(
            username="admin1",
            email="admin1@example.com",
            password="password123",
            role="admin",
            created_by="system",
            active=True
        )
        
        # Verifiziere Ausgangszustand
        assert user_service.count_active_admins() == 1
        
        # Act & Assert: Versuch, sowohl Rolle als auch Status zu ändern
        with pytest.raises(ValueError) as exc_info:
            user_service.update(
                user_id=admin.id,
                username=admin.username,
                email=admin.email,
                role="user",
                active=False,
                updated_by="system",
                expected_version=admin.version
            )
        
        assert "letzte aktive Administrator" in str(exc_info.value)
        
        # Verifiziere, dass sich nichts geändert hat
        updated_admin = user_service.get_by_id(admin.id)
        assert updated_admin.role == "admin"
        assert updated_admin.active is True
        assert user_service.count_active_admins() == 1
    
    def test_non_admin_user_changes_allowed(self, user_service):
        """
        Test: Änderungen an Nicht-Admin-Usern sind immer erlaubt,
        auch wenn nur ein Admin existiert
        """
        # Arrange: Erstelle einen Admin und einen normalen User
        admin = user_service.create(
            username="admin1",
            email="admin1@example.com",
            password="password123",
            role="admin",
            created_by="system",
            active=True
        )
        
        normal_user = user_service.create(
            username="user1",
            email="user1@example.com",
            password="password123",
            role="user",
            created_by="system",
            active=True
        )
        
        assert user_service.count_active_admins() == 1
        
        # Act: Ändere normalen User (sollte erlaubt sein)
        success = user_service.update(
            user_id=normal_user.id,
            username=normal_user.username,
            email=normal_user.email,
            role=normal_user.role,
            active=False,
            updated_by="system",
            expected_version=normal_user.version
        )
        assert success is True
        
        # Hole aktualisiertes Objekt
        updated_user = user_service.get_by_id(normal_user.id)
        
        # Assert: Änderung sollte erfolgreich sein
        assert updated_user.active is False
        assert user_service.count_active_admins() == 1  # Admin bleibt unverändert
    
    def test_inactive_admin_can_be_changed(self, user_service):
        """
        Test: Ein inaktiver Admin kann geändert werden,
        auch wenn nur ein aktiver Admin existiert
        """
        # Arrange: Erstelle einen aktiven Admin und einen inaktiven Admin
        active_admin = user_service.create(
            username="admin1",
            email="admin1@example.com",
            password="password123",
            role="admin",
            created_by="system",
            active=True
        )
        
        inactive_admin = user_service.create(
            username="admin2",
            email="admin2@example.com",
            password="password123",
            role="admin",
            created_by="system",
            active=False
        )
        
        assert user_service.count_active_admins() == 1
        
        # Act: Ändere inaktiven Admin (sollte erlaubt sein)
        success = user_service.update(
            user_id=inactive_admin.id,
            username=inactive_admin.username,
            email=inactive_admin.email,
            role="user",
            active=inactive_admin.active,
            updated_by="system",
            expected_version=inactive_admin.version
        )
        assert success is True
        
        # Hole aktualisiertes Objekt
        updated_admin = user_service.get_by_id(inactive_admin.id)
        
        # Assert: Änderung sollte erfolgreich sein
        assert updated_admin.role == "user"
        assert user_service.count_active_admins() == 1  # Aktiver Admin unverändert
