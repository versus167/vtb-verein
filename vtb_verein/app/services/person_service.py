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
            telefon = mitglied_data.pop('telefon', None)
            m = Mitglied(
                vorname=vorname,
                nachname=nachname,
                user_id=user.id,
                **mitglied_data,
            )
            mitglied = self.db.create_mitglied(m, created_by=created_by)
            self._create_initial_kontakte(mitglied, email, telefon, created_by)
        except Exception:
            # Kompensation: User soft-deleten wenn Mitglied-Anlage fehlschlägt
            try:
                self.user_service.delete(user.id, deleted_by=created_by)
            except Exception:
                pass
            raise

        return user, mitglied

    def create_mitglied_ohne_user(
        self,
        vorname: str,
        nachname: str,
        created_by: str,
        mitglied_data: dict,
    ) -> Mitglied:
        """Legt nur einen Mitglied-Datensatz an (kein User, kein Login)."""
        telefon = mitglied_data.pop('telefon', None)
        email = mitglied_data.pop('email', None)
        m = Mitglied(vorname=vorname, nachname=nachname, user_id=None, **mitglied_data)
        mitglied = self.db.create_mitglied(m, created_by=created_by)
        self._create_initial_kontakte(mitglied, email, telefon, created_by)
        return mitglied

    def _create_initial_kontakte(self, mitglied: Mitglied, email: Optional[str],
                                 telefon: Optional[str], created_by: str) -> None:
        """Legt die anfänglichen primären Kontakte (E-Mail/Telefon) an und spiegelt sie
        in die transienten Felder mitglied.email/telefon für die Rückgabe."""
        if email:
            self.db.create_mitglied_kontakt(mitglied.id, 'email', email, None, True, created_by)
            mitglied.email = email
        if telefon:
            self.db.create_mitglied_kontakt(mitglied.id, 'telefon', telefon, None, True, created_by)
            mitglied.telefon = telefon

    def delete_mitglied_ohne_user(self, mitglied_id: int, deleted_by: str) -> None:
        """Soft-löscht einen Mitglied-Datensatz ohne User.

        Abteilungs-Zuordnungen (und Funktionen) bleiben bestehen: alle relevanten
        Abfragen filtern ohnehin über ``mitglied.deleted_at``; endgültig entfernt
        werden sie später durch den Prune-Mechanismus. So bleibt das Verhalten zu
        Funktionen konsistent und ein Restore holt die Person vollständig zurück.
        """
        self.db.mark_mitglied_deleted(mitglied_id, deleted_by)

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
        """Soft-löscht User und verknüpften Mitglied-Datensatz.

        Abteilungs-Zuordnungen und Funktionen bleiben bestehen (s.
        delete_mitglied_ohne_user) – Bereinigung erfolgt später per Prune.
        """
        mitglied = self.db.get_mitglied_by_user_id(user_id)
        if mitglied:
            self.db.mark_mitglied_deleted(mitglied.id, deleted_by)
        # UserService.delete() beinhaltet last-admin-Check + Permissions-Bereinigung
        self.user_service.delete(user_id, deleted_by=deleted_by)

    # ------------------------------------------------------------------
    # Wiederherstellen (Papierkorb)
    # ------------------------------------------------------------------

    def restore_person(self, user_id: int, restored_by: str) -> None:
        """Hebt den Soft-Delete eines Users und seines Mitglied-Datensatzes auf.

        Abteilungs-Zuordnungen und Funktionen werden beim Löschen nicht angetastet
        und kommen daher automatisch wieder mit. Entzogene Einzel-Berechtigungen
        werden NICHT automatisch wiederhergestellt (rollenbasierte Rechte bleiben).
        """
        self.db.restore_user(user_id, restored_by)
        self.db.restore_mitglied_by_user_id(user_id, restored_by)

    def restore_mitglied_ohne_user(self, mitglied_id: int, restored_by: str) -> bool:
        """Hebt den Soft-Delete eines Mitglieds ohne Login-Account auf."""
        return self.db.restore_mitglied(mitglied_id, restored_by)

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
