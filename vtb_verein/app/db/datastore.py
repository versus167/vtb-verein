'''
Created on 07.02.2026
Refactored on 21.02.2026
Extended on 07.03.2026 - Magic-Link Authentication
Extended on 11.03.2026 - PermissionRepository hinzugefügt
Extended on 26.03.2026 - Kassenbuch-Repositories und KassenbuchService
Extended on 27.03.2026 - KasseBerechtigungRepository (Phase 3.2)
Extended on 28.03.2026 - KasseBerechtigungRepository an KassenbuchService übergeben (Phase 3.4)
Extended on 05.04.2026 - Ticket-System Repositories und TicketService (Phase 4.1)
Extended on 06.04.2026 - TicketBereichBerechtigungRepository (Phase 4.2)

VereinsDB Facade - Maintains backward compatibility while delegating to repositories.

@author: volker
@refactored: AI Assistant
'''

import os
from typing import Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.kassenbuch_service import KassenbuchService
from app.db.database import Database
from app.db.mitglied_repository import MitgliedRepository
from app.db.abteilung_repository import AbteilungRepository
from app.db.user_repository import UserRepository
from app.db.permission_repository import PermissionRepository
from app.db.auth_token_repository import AuthTokenRepository
from app.db.user_session_repository import UserSessionRepository
from app.db.access_log_repository import AccessLogRepository
from app.db.prune_einstellungen_repository import PruneEinstellungenRepository
from app.db.kasse_repository import KasseRepository
from app.db.kassenbuchung_repository import KassenbuchungRepository
from app.db.kassenbuch_export_repository import KassenbuchExportRepository
from app.db.kasse_berechtigung_repository import KasseBerechtigungRepository
from app.db.kassenbuchung_anhang_repository import KassenbuchungAnhangRepository
from app.db.kassen_kategorie_repository import KassenKategorieRepository
from app.db.kassen_zaehlung_repository import KassenZaehlungRepository
from app.db.ticket_repository import TicketRepository
from app.db.ticket_kommentar_repository import TicketKommentarRepository
from app.db.ticket_anhang_repository import TicketAnhangRepository
from app.db.ticket_bereich_repository import TicketBereichRepository
from app.db.ticket_kategorie_repository import TicketKategorieRepository
from app.db.ticket_teilnehmer_repository import TicketTeilnehmerRepository
from app.db.ticket_bereich_berechtigung_repository import TicketBereichBerechtigungRepository
from app.db.mitglied_abteilung_repository import MitgliedAbteilungRepository, MitgliedAbteilung
from app.db.mitglied_funktion_repository import MitgliedFunktionRepository, MitgliedFunktion
from app.db.mitglied_kontakt_repository import MitgliedKontaktRepository, MitgliedKontakt
from app.db.mannschaft_repository import MannschaftRepository, Mannschaft
from app.db.mitglied_mannschaft_repository import MitgliedMannschaftRepository, MitgliedMannschaft
from app.db.funktion_repository import FunktionRepository
from app.db.funktion_permission_repository import FunktionPermissionRepository
from app.db.beitragsregel_repository import BeitragsregelRepository
from app.db.beitrag_sollstellung_repository import BeitragSollstellungRepository
from app.db.gebuehr_repository import GebuehrRepository
from app.db.gebuehr_forderung_repository import GebuehrForderungRepository
from app.db.fibu_export_repository import FibuExportRepository
from app.db.fibu_einstellungen_repository import FibuEinstellungenRepository
from app.db.beitrag_einstellungen_repository import BeitragEinstellungenRepository
from app.db.statistik_repository import StatistikRepository
from app.db.ul_abrechnung_repository import ULAbrechnungRepository
from app.db.ul_satz_repository import ULSatzRepository
from app.db.ttlock_konto_repository import TTLockKontoRepository
from app.db.tuer_schloss_repository import TuerSchlossRepository
from app.db.schluessel_chip_repository import SchluesselChipRepository
from app.db.tuer_berechtigung_repository import TuerBerechtigungRepository
from app.db.tuer_app_berechtigung_repository import TuerAppBerechtigungRepository
from app.db.tuer_zutritt_log_repository import TuerZutrittLogRepository
from app.db.tuer_credential_repository import TuerCredentialRepository
from app.services.zutritt_service import ZutrittService
from app.models.gebuehr import Gebuehr, GebuehrForderung
from app.models.mitglied import Mitglied
from app.models.abteilung import Abteilung
from app.models.user import User
from app.services.ticket_service import TicketService
from app.services.anhang_service import AnhangService


class VereinsDB:
    """Data Access Layer Facade - Delegates to specialized repositories."""

    def __init__(self, database_url: str, upload_path: str = 'uploads/'):
        from app.services.kassenbuch_service import KassenbuchService
        self._database = Database(database_url)
        self.conn = self._database.conn

        self._mitglied_repo = MitgliedRepository(self.conn)
        self._abteilung_repo = AbteilungRepository(self.conn)
        self._mitglied_abteilung_repo = MitgliedAbteilungRepository(self.conn)
        self._mitglied_funktion_repo = MitgliedFunktionRepository(self.conn)
        self._mitglied_kontakt_repo = MitgliedKontaktRepository(self.conn)
        self._mannschaft_repo = MannschaftRepository(self.conn)
        self._mitglied_mannschaft_repo = MitgliedMannschaftRepository(self.conn)
        self._funktion_repo = FunktionRepository(self.conn)
        self._funktion_permission_repo = FunktionPermissionRepository(self.conn)
        self._user_repo = UserRepository(self.conn)
        self._permission_repo = PermissionRepository(self.conn)
        self._auth_token_repo = AuthTokenRepository(self._database)
        self._user_session_repo = UserSessionRepository(self._database)
        self._access_log_repo = AccessLogRepository(self._database)
        self._prune_einstellungen_repo = PruneEinstellungenRepository(self.conn)
        self._kasse_repo = KasseRepository(self.conn)
        self._kassenbuchung_repo = KassenbuchungRepository(self.conn)
        self._kassenbuch_export_repo = KassenbuchExportRepository(self.conn)
        self._kasse_berechtigung_repo = KasseBerechtigungRepository(self.conn)
        self._kassenbuchung_anhang_repo = KassenbuchungAnhangRepository(self.conn)
        self._kassen_kategorie_repo = KassenKategorieRepository(self.conn)
        self._kassen_zaehlung_repo = KassenZaehlungRepository(self.conn)
        self._beitragsregel_repo = BeitragsregelRepository(self.conn)
        self._sollstellung_repo = BeitragSollstellungRepository(self.conn)
        self._beitrag_einstellungen_repo = BeitragEinstellungenRepository(self.conn)
        self._gebuehr_repo = GebuehrRepository(self.conn)
        self._gebuehr_forderung_repo = GebuehrForderungRepository(self.conn)
        self._fibu_export_repo = FibuExportRepository(self.conn)
        self._fibu_einstellungen_repo = FibuEinstellungenRepository(self.conn)
        self._ul_abrechnung_repo = ULAbrechnungRepository(self.conn)
        self._ul_satz_repo = ULSatzRepository(self.conn)
        self._statistik_repo = StatistikRepository(self.conn)

        # Zutrittskontrolle / Schließanlage (TT-Lock)
        self._ttlock_konto_repo = TTLockKontoRepository(self.conn)
        self._tuer_schloss_repo = TuerSchlossRepository(self.conn)
        self._schluessel_chip_repo = SchluesselChipRepository(self.conn)
        self._tuer_berechtigung_repo = TuerBerechtigungRepository(self.conn)
        self._tuer_app_berechtigung_repo = TuerAppBerechtigungRepository(self.conn)
        self._tuer_zutritt_log_repo = TuerZutrittLogRepository(self.conn)
        self._tuer_credential_repo = TuerCredentialRepository(self.conn)
        self._zutritt_service = ZutrittService(
            konto_repo=self._ttlock_konto_repo,
            schloss_repo=self._tuer_schloss_repo,
            chip_repo=self._schluessel_chip_repo,
            berechtigung_repo=self._tuer_berechtigung_repo,
            log_repo=self._tuer_zutritt_log_repo,
            credential_repo=self._tuer_credential_repo,
            # Log-Auflösung von App-/Gateway-Öffnungen (#66): access_log-Korrelation → Mitglied.
            access_log_repo=self._access_log_repo,
            mitglied_repo=self._mitglied_repo,
        )

        self._anhang_service = AnhangService(
            upload_path=upload_path,
            max_mb=int(os.getenv('VTB_MAX_UPLOAD_MB', '10')),
        )

        self._kassenbuch_service = KassenbuchService(
            kasse_repo=self._kasse_repo,
            buchung_repo=self._kassenbuchung_repo,
            export_repo=self._kassenbuch_export_repo,
            berechtigung_repo=self._kasse_berechtigung_repo,
            anhang_repo=self._kassenbuchung_anhang_repo,
            anhang_service=self._anhang_service,
            kategorie_repo=self._kassen_kategorie_repo,
            zaehlung_repo=self._kassen_zaehlung_repo,
        )

        self._ticket_repo = TicketRepository(self.conn)
        self._ticket_kommentar_repo = TicketKommentarRepository(self.conn)
        self._ticket_anhang_repo = TicketAnhangRepository(self.conn)
        self._ticket_bereich_repo = TicketBereichRepository(self.conn)
        self._ticket_kategorie_repo = TicketKategorieRepository(self.conn)
        self._ticket_teilnehmer_repo = TicketTeilnehmerRepository(self.conn)
        self._ticket_bereich_berechtigung_repo = TicketBereichBerechtigungRepository(self.conn)

        self._ticket_service = TicketService(
            ticket_repo=self._ticket_repo,
            kommentar_repo=self._ticket_kommentar_repo,
            anhang_repo=self._ticket_anhang_repo,
            bereich_repo=self._ticket_bereich_repo,
            kategorie_repo=self._ticket_kategorie_repo,
            teilnehmer_repo=self._ticket_teilnehmer_repo,
            berechtigung_repo=self._ticket_bereich_berechtigung_repo,
            user_repo=self._user_repo,
            anhang_service=self._anhang_service,
        )

    @property
    def user_repository(self) -> UserRepository:
        return self._user_repo

    @property
    def users(self) -> UserRepository:
        return self._user_repo

    @property
    def permissions(self) -> PermissionRepository:
        return self._permission_repo

    @property
    def funktion_permissions(self) -> FunktionPermissionRepository:
        return self._funktion_permission_repo

    @property
    def auth_token_repository(self) -> AuthTokenRepository:
        return self._auth_token_repo

    @property
    def user_session_repository(self) -> UserSessionRepository:
        return self._user_session_repo

    @property
    def access_log_repository(self) -> AccessLogRepository:
        return self._access_log_repo

    @property
    def prune_einstellungen(self) -> PruneEinstellungenRepository:
        return self._prune_einstellungen_repo

    @property
    def kassenbuch(self) -> "KassenbuchService":
        return self._kassenbuch_service

    @property
    def kassen(self) -> KasseRepository:
        """Direktzugriff auf KasseRepository (für Admin-Operationen)."""
        return self._kasse_repo

    @property
    def kasse_berechtigungen(self) -> KasseBerechtigungRepository:
        """Zugriff auf KasseBerechtigungRepository."""
        return self._kasse_berechtigung_repo

    @property
    def kassen_kategorien(self) -> KassenKategorieRepository:
        """Direktzugriff auf KassenKategorieRepository (Stammdaten)."""
        return self._kassen_kategorie_repo

    # --- Zutrittskontrolle / Schließanlage ---
    @property
    def zutritt(self) -> ZutrittService:
        return self._zutritt_service

    @property
    def tuer_schloesser(self) -> TuerSchlossRepository:
        return self._tuer_schloss_repo

    @property
    def schluessel_chips(self) -> SchluesselChipRepository:
        return self._schluessel_chip_repo

    @property
    def tuer_berechtigungen(self) -> TuerBerechtigungRepository:
        return self._tuer_berechtigung_repo

    @property
    def tuer_app_berechtigungen(self) -> TuerAppBerechtigungRepository:
        return self._tuer_app_berechtigung_repo

    @property
    def tuer_zutritt_logs(self) -> TuerZutrittLogRepository:
        return self._tuer_zutritt_log_repo

    @property
    def tuer_credentials(self) -> TuerCredentialRepository:
        return self._tuer_credential_repo

    @property
    def ttlock_konto(self) -> TTLockKontoRepository:
        return self._ttlock_konto_repo

    @property
    def anhang_service(self) -> AnhangService:
        return self._anhang_service

    @property
    def tickets(self) -> TicketService:
        """Zugriff auf TicketService (Business-Logik + alle Ticket-Repos)."""
        return self._ticket_service

    @property
    def ticket_bereiche(self) -> TicketBereichRepository:
        """Direktzugriff auf TicketBereichRepository."""
        return self._ticket_bereich_repo

    @property
    def ticket_kategorien(self) -> TicketKategorieRepository:
        """Direktzugriff auf TicketKategorieRepository."""
        return self._ticket_kategorie_repo

    @property
    def ticket_bereich_berechtigungen(self) -> TicketBereichBerechtigungRepository:
        """Zugriff auf TicketBereichBerechtigungRepository."""
        return self._ticket_bereich_berechtigung_repo

    @property
    def funktionen(self) -> FunktionRepository:
        return self._funktion_repo

    @property
    def statistik(self) -> StatistikRepository:
        """Aggregierte Kennzahlen für das Berichte-/Statistik-Dashboard."""
        return self._statistik_repo

    def cursor(self):
        return self._database.cursor()

    def close(self):
        self._database.close()

    # -----------------------------------
    # Mitglied Operations
    # -----------------------------------

    def get_next_mitgliedsnummer(self) -> int:
        return self._mitglied_repo.get_next_mitgliedsnummer()

    def is_mitgliedsnummer_available(self, nummer: int, exclude_id: int = None) -> bool:
        return self._mitglied_repo.is_mitgliedsnummer_available(nummer, exclude_id)

    def get_mitglied(self, id: int) -> Mitglied:
        return self._mitglied_repo.get_mitglied(id)

    def list_mitglieder(self) -> list[Mitglied]:
        return self._mitglied_repo.list_mitglieder()

    def list_mitglieder_for_standard_view(self) -> list[tuple[Mitglied, bool]]:
        return self._mitglied_repo.list_mitglieder_for_standard_view()

    def create_mitglied(self, mitglied: Mitglied, created_by: str) -> Mitglied:
        return self._mitglied_repo.create_mitglied(mitglied, created_by)

    def update_mitglied(self, mitglied: Mitglied, updated_by: str) -> bool:
        return self._mitglied_repo.update_mitglied(mitglied, updated_by)

    def mark_mitglied_deleted(self, mitglied_id: int, deleted_by: str) -> bool:
        return self._mitglied_repo.mark_mitglied_deleted(mitglied_id, deleted_by)

    def restore_mitglied(self, mitglied_id: int, restored_by: str) -> bool:
        return self._mitglied_repo.restore_mitglied(mitglied_id, restored_by)

    def restore_mitglied_by_user_id(self, user_id: int, restored_by: str) -> bool:
        return self._mitglied_repo.restore_mitglied_by_user_id(user_id, restored_by)

    def get_mitglied_by_user_id(self, user_id: int) -> Optional[Mitglied]:
        return self._mitglied_repo.get_by_user_id(user_id)

    def get_mitglied_history(self, mitglied_id: int) -> list[dict]:
        return self._mitglied_repo.get_history(mitglied_id)

    # -----------------------------------
    # Abteilung Operations
    # -----------------------------------

    def get_abteilung(self, id: int) -> Abteilung:
        return self._abteilung_repo.get_abteilung(id)

    def list_abteilungen(self) -> list[Abteilung]:
        return self._abteilung_repo.list_abteilungen()

    def list_deleted_abteilungen(self) -> list[dict]:
        return self._abteilung_repo.list_deleted_abteilungen()

    def create_abteilung(self, abt: Abteilung, created_by: str) -> Abteilung:
        return self._abteilung_repo.create_abteilung(abt, created_by)

    def update_abteilung(self, abt: Abteilung, updated_by: str) -> bool:
        return self._abteilung_repo.update_abteilung(abt, updated_by)

    def mark_abteilung_deleted(self, abteilung_id: int, deleted_by: str) -> bool:
        return self._abteilung_repo.mark_abteilung_deleted(abteilung_id, deleted_by)

    def restore_abteilung(self, abteilung_id: int, restored_by: str) -> bool:
        return self._abteilung_repo.restore_abteilung(abteilung_id, restored_by)

    def has_active_mitglied_abteilung_references(self, abteilung_id: int) -> bool:
        return self._abteilung_repo.has_active_mitglied_abteilung_references(abteilung_id)

    def has_active_beitragsregel_references(self, abteilung_id: int) -> bool:
        return self._abteilung_repo.has_active_beitragsregel_references(abteilung_id)

    def has_active_mitglied_funktion_references(self, funktion_id: int) -> bool:
        return self._funktion_repo.has_active_mitglied_funktion_references(funktion_id)

    def has_mitglied_abteilung_history(self, abteilung_id: int) -> bool:
        return self._abteilung_repo.has_mitglied_abteilung_history(abteilung_id)

    def has_beitragsregel_history(self, abteilung_id: int) -> bool:
        return self._abteilung_repo.has_beitragsregel_history(abteilung_id)

    def prune_deleted_abteilungen(self, days_old: int) -> int:
        return self._abteilung_repo.prune_deleted_abteilungen(days_old)

    # -----------------------------------
    # Mitglied-Abteilung-Zuordnung
    # -----------------------------------

    def list_mitglied_abteilungen(self, mitglied_id: int) -> list[MitgliedAbteilung]:
        return self._mitglied_abteilung_repo.list_for_mitglied(mitglied_id)

    def get_mitglied_abteilung(self, id: int) -> Optional[MitgliedAbteilung]:
        return self._mitglied_abteilung_repo.get(id)

    def create_mitglied_abteilung(self, mitglied_id: int, abteilung_id: int, status: str,
                                   von: Optional[str], bis: Optional[str],
                                   created_by: str) -> MitgliedAbteilung:
        return self._mitglied_abteilung_repo.create(
            mitglied_id, abteilung_id, status, von, bis, created_by
        )

    def update_mitglied_abteilung(self, id: int, status: str, von: Optional[str],
                                   bis: Optional[str], updated_by: str,
                                   expected_version: int) -> bool:
        return self._mitglied_abteilung_repo.update(
            id, status, von, bis, updated_by, expected_version
        )

    def mark_mitglied_abteilung_deleted(self, id: int, deleted_by: str) -> bool:
        return self._mitglied_abteilung_repo.mark_deleted(id, deleted_by)

    def mitglied_abteilung_exists_active(self, mitglied_id: int, abteilung_id: int) -> bool:
        return self._mitglied_abteilung_repo.exists_active(mitglied_id, abteilung_id)

    def list_mitglied_funktionen(self, mitglied_id: int) -> list[MitgliedFunktion]:
        return self._mitglied_funktion_repo.list_for_mitglied(mitglied_id)

    def list_mitglieder_mit_funktion(self, *funktionen: str) -> list[dict]:
        return self._mitglied_funktion_repo.list_mitglieder_mit_funktion(*funktionen)

    def abteilung_ids_fuer_funktion(self, mitglied_id: int, *funktionen: str) -> list:
        return self._mitglied_funktion_repo.abteilung_ids_fuer_funktion(mitglied_id, *funktionen)

    def get_mitglied_funktion(self, id: int) -> Optional[MitgliedFunktion]:
        return self._mitglied_funktion_repo.get(id)

    def create_mitglied_funktion(self, mitglied_id: int, abteilung_id: Optional[int],
                                  funktion: str, von: Optional[str], bis: Optional[str],
                                  created_by: str) -> MitgliedFunktion:
        return self._mitglied_funktion_repo.create(
            mitglied_id, abteilung_id, funktion, von, bis, created_by
        )

    def update_mitglied_funktion(self, id: int, abteilung_id: Optional[int], funktion: str,
                                  von: Optional[str], bis: Optional[str],
                                  updated_by: str, expected_version: int) -> bool:
        return self._mitglied_funktion_repo.update(
            id, abteilung_id, funktion, von, bis, updated_by, expected_version
        )

    def mark_mitglied_funktion_deleted(self, id: int, deleted_by: str) -> bool:
        return self._mitglied_funktion_repo.mark_deleted(id, deleted_by)

    # -----------------------------------
    # Mitglied-Kontakt-Zuordnung (mehrere E-Mails/Telefonnummern)
    # -----------------------------------

    def list_mitglied_kontakte(self, mitglied_id: int) -> list[MitgliedKontakt]:
        return self._mitglied_kontakt_repo.list_for_mitglied(mitglied_id)

    def get_mitglied_kontakt(self, id: int) -> Optional[MitgliedKontakt]:
        return self._mitglied_kontakt_repo.get(id)

    def get_mitglied_kontakt_primaer(self, mitglied_id: int, typ: str) -> Optional[str]:
        return self._mitglied_kontakt_repo.get_primaer(mitglied_id, typ)

    def create_mitglied_kontakt(self, mitglied_id: int, typ: str, wert: str,
                                label: Optional[str], ist_primaer: bool,
                                created_by: str) -> MitgliedKontakt:
        return self._mitglied_kontakt_repo.create(
            mitglied_id, typ, wert, label, ist_primaer, created_by
        )

    def update_mitglied_kontakt(self, id: int, typ: str, wert: str, label: Optional[str],
                                ist_primaer: bool, updated_by: str,
                                expected_version: int) -> bool:
        return self._mitglied_kontakt_repo.update(
            id, typ, wert, label, ist_primaer, updated_by, expected_version
        )

    def mark_mitglied_kontakt_deleted(self, id: int, deleted_by: str) -> bool:
        return self._mitglied_kontakt_repo.mark_deleted(id, deleted_by)

    def set_mitglied_primaer_kontakt(self, mitglied_id: int, typ: str,
                                     wert: Optional[str], actor: str) -> None:
        return self._mitglied_kontakt_repo.upsert_primaer(mitglied_id, typ, wert, actor)

    # -----------------------------------
    # Mannschaften / Teams
    # -----------------------------------

    def list_mannschaften(self, abteilung_id: Optional[int] = None) -> list[Mannschaft]:
        return self._mannschaft_repo.list_all(abteilung_id)

    def get_mannschaft(self, id: int) -> Optional[Mannschaft]:
        return self._mannschaft_repo.get(id)

    def list_mannschaft_kandidaten(self, mannschaft_id: int) -> list[dict]:
        return self._mannschaft_repo.list_kandidaten(mannschaft_id)

    def create_mannschaft(self, m: Mannschaft, created_by: str) -> Mannschaft:
        return self._mannschaft_repo.create(m, created_by)

    def update_mannschaft(self, m: Mannschaft, updated_by: str) -> bool:
        return self._mannschaft_repo.update(m, updated_by)

    def mark_mannschaft_deleted(self, id: int, deleted_by: str) -> bool:
        return self._mannschaft_repo.mark_deleted(id, deleted_by)

    def mannschaft_has_active_mitglieder(self, mannschaft_id: int) -> bool:
        return self._mannschaft_repo.has_active_mitglied_references(mannschaft_id)

    def list_mannschaft_kader(self, mannschaft_id: int) -> list[MitgliedMannschaft]:
        return self._mitglied_mannschaft_repo.list_for_mannschaft(mannschaft_id)

    def list_mitglied_mannschaften(self, mitglied_id: int) -> list[MitgliedMannschaft]:
        return self._mitglied_mannschaft_repo.list_for_mitglied(mitglied_id)

    def get_mitglied_mannschaft(self, id: int) -> Optional[MitgliedMannschaft]:
        return self._mitglied_mannschaft_repo.get(id)

    def create_mitglied_mannschaft(self, mitglied_id: int, mannschaft_id: int, rolle: str,
                                   von: str, bis: Optional[str], created_by: str) -> MitgliedMannschaft:
        return self._mitglied_mannschaft_repo.create(mitglied_id, mannschaft_id, rolle, von, bis, created_by)

    def update_mitglied_mannschaft(self, id: int, rolle: str, von: str, bis: Optional[str],
                                   updated_by: str, expected_version: int) -> bool:
        return self._mitglied_mannschaft_repo.update(id, rolle, von, bis, updated_by, expected_version)

    def mark_mitglied_mannschaft_deleted(self, id: int, deleted_by: str) -> bool:
        return self._mitglied_mannschaft_repo.mark_deleted(id, deleted_by)

    # -----------------------------------
    # User Operations
    # -----------------------------------

    def get_user_by_username(self, username: str) -> Optional[User]:
        return self._user_repo.get_by_username(username)

    def get_user_by_email(self, email: str) -> Optional[User]:
        return self._user_repo.get_by_email(email)

    def get_user_by_id(self, user_id: int) -> Optional[User]:
        return self._user_repo.get_by_id(user_id)

    def list_users(self) -> List[User]:
        return self._user_repo.list_all()

    def count_active_admins(self) -> int:
        return self._user_repo.count_active_admins()

    def create_user(self, username: str, email: str, password_hash: str, role: str,
                    created_by: str, active: bool = True) -> User:
        return self._user_repo.create(username, email, password_hash, role, created_by, active)

    def update_user(self, user_id: int, username: str, email: str, role: str,
                    active: bool, updated_by: str, expected_version: int) -> bool:
        return self._user_repo.update(user_id, username, email, role, active, updated_by, expected_version)

    def update_user_password(self, user_id: int, password_hash: str, updated_by: str,
                             expected_version: int) -> bool:
        return self._user_repo.update_password(user_id, password_hash, updated_by, expected_version)

    def update_last_login(self, user_id: int) -> bool:
        return self._user_repo.update_last_login(user_id)

    def update_last_seen(self, user_id: int) -> bool:
        return self._user_repo.update_last_seen(user_id)

    def mark_user_deleted(self, user_id: int, deleted_by: str) -> bool:
        return self._user_repo.mark_user_deleted(user_id, deleted_by)

    def restore_user(self, user_id: int, restored_by: str) -> bool:
        return self._user_repo.restore_user(user_id, restored_by)

    # -----------------------------------
    # Beiträge
    # -----------------------------------

    @property
    def beitragsregeln(self) -> BeitragsregelRepository:
        return self._beitragsregel_repo

    @property
    def sollstellungen(self) -> BeitragSollstellungRepository:
        return self._sollstellung_repo

    @property
    def beitrag_einstellungen(self) -> BeitragEinstellungenRepository:
        return self._beitrag_einstellungen_repo

    @property
    def gebuehren(self) -> GebuehrRepository:
        return self._gebuehr_repo

    @property
    def gebuehr_forderungen(self) -> GebuehrForderungRepository:
        return self._gebuehr_forderung_repo

    @property
    def fibu_exporte(self) -> FibuExportRepository:
        return self._fibu_export_repo

    @property
    def fibu_einstellungen(self) -> FibuEinstellungenRepository:
        return self._fibu_einstellungen_repo

    @property
    def ul_abrechnungen(self) -> ULAbrechnungRepository:
        return self._ul_abrechnung_repo

    @property
    def ul_saetze(self) -> ULSatzRepository:
        return self._ul_satz_repo

    # --- Gebühren-Delegationen (für Service/API) ---
    def get_gebuehr(self, id: int) -> Optional[Gebuehr]:
        return self._gebuehr_repo.get(id)

    def get_gebuehr_forderung(self, id: int) -> Optional[GebuehrForderung]:
        return self._gebuehr_forderung_repo.get(id)

    def gebuehr_forderung_exists(self, mitglied_id: int, gebuehr_id: int) -> bool:
        return self._gebuehr_forderung_repo.exists(mitglied_id, gebuehr_id)

    def create_gebuehr_forderung(self, f: GebuehrForderung, created_by: str) -> GebuehrForderung:
        return self._gebuehr_forderung_repo.create(f, created_by)

    def set_gebuehr_forderung_kassenbuchung(self, id: int, kassenbuchung_id: int, updated_by: str) -> bool:
        return self._gebuehr_forderung_repo.set_kassenbuchung(id, kassenbuchung_id, updated_by)

