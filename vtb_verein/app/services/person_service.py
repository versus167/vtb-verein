"""
PersonService — atomisches Anlegen/Löschen von User + Mitglied-Datensatz.
"""
import re
import unicodedata
from typing import Optional

from app.models.mitglied import Mitglied
from app.models.user import User
from app.services.user_service import UserService


class PersonService:
    """Koordiniert User + Mitglied als zusammengehörige Einheit."""

    def __init__(self, db):
        self.db = db
        self.user_service = UserService(db)

    # ------------------------------------------------------------------
    # Anlegen
    # ------------------------------------------------------------------

    def create_vereinsmitglied(
        self,
        vorname: str,
        nachname: str,
        email: str,
        role: str,
        active: bool,
        created_by: str,
        mitglied_data: dict,
        password: Optional[str] = None,
    ) -> tuple[User, Mitglied]:
        """Legt User + Mitglied atomisch an. Bei Fehler wird der User rückgängig gemacht."""
        username = self._generate_username(vorname, nachname)

        user = self.user_service.create(
            username=username,
            email=email,
            role=role,
            active=active,
            created_by=created_by,
            password=password,
            send_magic_link=active,
        )

        try:
            m = Mitglied(
                vorname=vorname,
                nachname=nachname,
                email=email,
                user_id=user.id,
                **mitglied_data,
            )
            mitglied = self.db.create_mitglied(m, created_by=created_by)
        except Exception:
            # Kompensation: User soft-deleten wenn Mitglied-Anlage fehlschlägt
            try:
                self.user_service.delete(user.id, deleted_by=created_by)
            except Exception:
                pass
            raise

        return user, mitglied

    def create_user_only(
        self,
        username: str,
        email: str,
        role: str,
        active: bool,
        created_by: str,
        password: Optional[str] = None,
    ) -> User:
        """Legt nur einen User an (Admin/Benutzer ohne Vereinsmitglied-Datensatz)."""
        return self.user_service.create(
            username=username,
            email=email,
            role=role,
            active=active,
            created_by=created_by,
            password=password,
            send_magic_link=active,
        )

    # ------------------------------------------------------------------
    # Löschen
    # ------------------------------------------------------------------

    def delete_person(self, user_id: int, deleted_by: str) -> None:
        """Soft-löscht User und verknüpften Mitglied-Datensatz (inkl. Abteilungs-Zuordnungen)."""
        mitglied = self.db.get_mitglied_by_user_id(user_id)
        if mitglied:
            for zuordnung in self.db.list_mitglied_abteilungen(mitglied.id):
                self.db.mark_mitglied_abteilung_deleted(zuordnung.id, deleted_by)
            self.db.mark_mitglied_deleted(mitglied.id, deleted_by)
        # UserService.delete() beinhaltet last-admin-Check + Permissions-Bereinigung
        self.user_service.delete(user_id, deleted_by=deleted_by)

    # ------------------------------------------------------------------
    # Hilfsmethoden
    # ------------------------------------------------------------------

    def _generate_username(self, vorname: str, nachname: str) -> str:
        """Generiert 'vorname.nachname' (ASCII, lowercase), disambiguiert bei Kollision."""
        def normalize(s: str) -> str:
            s = unicodedata.normalize('NFKD', s)
            s = s.encode('ascii', 'ignore').decode('ascii')
            return re.sub(r'[^a-z0-9]', '', s.lower())

        base = f"{normalize(vorname)}.{normalize(nachname)}"
        if not base.replace('.', ''):
            base = 'mitglied'

        username = base
        counter = 2
        while self.db.get_user_by_username(username) is not None:
            username = f"{base}{counter}"
            counter += 1
        return username
