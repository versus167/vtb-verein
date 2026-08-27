'''
Created on 21.02.2026
Extended on 07.03.2026 - Magic-Link Authentication
Extended on 11.03.2026 - Permissions nach User-Load befüllen

User Repository - All database operations for User entity.

@author: AI Assistant
'''

from psycopg import Connection as PgConnection
from psycopg.errors import UniqueViolation
from typing import Optional, List
from app.models.user import User
from app.db.base_repository import BaseRepository
from app.db.permission_repository import PermissionRepository

# Spaltenliste aller User-Lesezugriffe – genau die Felder, die `_row_to_user`
# erwartet. Als Konstante, damit ein neues Feld nicht an einer der Abfragen
# vergessen wird (`get_username` liest bewusst weniger und bleibt außen vor).
_USER_SELECT = """SELECT id, username, email, password_hash, role, active, last_login, last_seen,
                         version, created_at, created_by, updated_at, updated_by,
                         matrix_id, preferred_contact
                  FROM users"""

# Anmelde-Kennung = Benutzername ODER E-Mail-Adresse. Beide Merkmale sind im
# Bestand eindeutig, also darf man sich mit beiden anmelden. Verglichen wird ohne
# Rücksicht auf Groß-/Kleinschreibung – wie schon immer beim Benutzernamen.
_KENNUNG_WHERE = ("deleted_at IS NULL "
                  "AND (LOWER(username) = LOWER(%(k)s) OR LOWER(email) = LOWER(%(k)s))")


def _kennung_order(kennung: str) -> str:
    """Macht die Auswahl eindeutig, falls eine Kennung auf zwei Konten passt.

    Das kann nur passieren, wenn ein Benutzername wie die Adresse eines anderen
    Kontos aussieht oder sich zwei Adressen allein in der Schreibweise
    unterscheiden (der Unique-Index vergleicht exakt). Beides kommt in einem
    Verein nicht vor – aber „irgendeine" Zeile darf hier nie herauskommen, sonst
    hinge der Anmeldeweg vom Zufall der Sortierung ab.

    Reihenfolge: erst die naheliegende Deutung (mit @ die Adresse, sonst der
    Benutzername), dann die exakte Schreibweise, zuletzt die kleinste id.
    """
    erst = 'email' if '@' in kennung else 'username'
    # COALESCE, weil `email` NULL sein darf (Konto ohne Zugang): Ein Vergleich mit
    # NULL ergibt NULL, und `ORDER BY … DESC` stellt NULL in Postgres nach vorn –
    # ausgerechnet die Zeile, die *nicht* passt, käme also zuerst.
    return (f"ORDER BY COALESCE(LOWER({erst}) = LOWER(%(k)s), FALSE) DESC, "
            "(COALESCE(username = %(k)s, FALSE) OR COALESCE(email = %(k)s, FALSE)) DESC, "
            "id")


class UserRepository(BaseRepository):
    """Repository for User CRUD operations.
    
    Handles:
    - User authentication data access
    - Create, Read, Update operations
    - Soft-delete operations
    - Password management
    - History tracking (via database triggers)
    
    Note: Password hashing and validation logic belongs in the service layer.
    """
    
    def __init__(self, db_conn):
        super().__init__(db_conn)
        self._permission_repo = PermissionRepository(db_conn)
    
    def _load_permissions(self, user: User) -> User:
        """Befüllt user.effective + user.permissions über den PermissionRepository.

        Wird nach jedem User-Load aufgerufen, damit Permissions
        direkt verfügbar sind für has_permission() und @require_permission().
        Effektiv = (Sockel ∪ Funktionsrechte ∪ Grants) − Denies, siehe BERECHTIGUNGEN.md.
        """
        user.effective = self._permission_repo.get_effective_permissions(user.id)
        user.permissions = user.effective.keys()
        return user
    
    def get_by_username(self, username: str) -> Optional[User]:
        """Find User by username (only non-deleted)."""
        with self.cursor() as cur:
            cur.execute(
                f"""{_USER_SELECT}
                    WHERE LOWER(username) = LOWER(%s) AND deleted_at IS NULL""",
                (username,)
            )
            row = cur.fetchone()
            if not row:
                return None
            return self._load_permissions(self._row_to_user(row))
    
    def get_by_email(self, email: str) -> Optional[User]:
        """Find User by email (only non-deleted). Used for Magic-Link authentication.

        Ohne Adresse gibt es nichts zu suchen: Konten ohne Zugang haben email IS NULL,
        und eine leer abgeschickte Anmeldung darf niemanden treffen.

        Groß-/Kleinschreibung spielt keine Rolle — wie beim Benutzernamen. Der
        Unique-Index vergleicht dagegen exakt, zwei Konten könnten sich also
        theoretisch allein in der Schreibweise unterscheiden. Für diesen Fall ist
        die Auswahl fest verdrahtet: exakte Schreibweise zuerst, danach die
        kleinste id — nie „irgendeine" Zeile.
        """
        email = (email or '').strip()
        if not email:
            return None
        with self.cursor() as cur:
            cur.execute(
                f"""{_USER_SELECT}
                    WHERE LOWER(email) = LOWER(%s) AND deleted_at IS NULL
                    ORDER BY (email = %s) DESC, id
                    LIMIT 1""",
                (email, email)
            )
            row = cur.fetchone()
            if not row:
                return None
            return self._load_permissions(self._row_to_user(row))

    def get_by_kennung(self, kennung: str) -> Optional[User]:
        """Konto zu einer Anmelde-Kennung: Benutzername **oder** E-Mail-Adresse.

        Beides ist im Bestand eindeutig (partielle Unique-Indizes
        `uix_users_username_active` / `uix_users_email_active`), also taugt auch
        beides als Kennung: Der Passwort-Login nimmt die Adresse, der Login-Link
        den Benutzernamen. Niemand muss sich merken, welches der beiden Merkmale
        an welcher Stelle gemeint war.

        Der Vorrang steht in `_kennung_order` – gebraucht wird er nur in dem
        praktisch nicht vorkommenden Fall, dass ein Benutzername wie die Adresse
        eines *anderen* Kontos aussieht. Ein fremdes Konto lässt sich damit nicht
        übernehmen: Was danach folgt, ist weiterhin die Passwortprüfung bzw. die
        Zustellung an die am Konto hinterlegte Adresse.
        """
        kennung = (kennung or '').strip()
        if not kennung:
            return None
        with self.cursor() as cur:
            cur.execute(
                f"""{_USER_SELECT}
                    WHERE {_KENNUNG_WHERE}
                    {_kennung_order(kennung)}
                    LIMIT 1""",
                {'k': kennung}
            )
            row = cur.fetchone()
            if not row:
                return None
            return self._load_permissions(self._row_to_user(row))

    def get_username_by_kennung(self, kennung: str) -> Optional[str]:
        """Nur den Benutzernamen zur Kennung – ohne den Permission-Fanout von
        `get_by_kennung` (`_load_permissions`).

        Für die Anmelde-Bremse: Die muss Benutzername und E-Mail auf *einen*
        Zählschlüssel bringen, und das **vor** der eigentlichen Prüfung – ein
        abgewiesener Versuch soll so wenig wie möglich kosten. Vorrang und
        Auswahl sind dieselben wie bei `get_by_kennung`, sonst zählte die Bremse
        auf ein anderes Konto als das, gegen das geprüft wird.
        """
        kennung = (kennung or '').strip()
        if not kennung:
            return None
        with self.cursor() as cur:
            cur.execute(
                f"""SELECT username FROM users
                    WHERE {_KENNUNG_WHERE}
                    {_kennung_order(kennung)}
                    LIMIT 1""",
                {'k': kennung}
            )
            row = cur.fetchone()
            return row['username'] if row else None

    def finde_kennungs_kollision(self, *, username: str, email: Optional[str],
                                 ausser_id: Optional[int] = None) -> Optional[dict]:
        """Sucht ein *anderes* Konto, dessen Benutzername auf die Adresse trifft –
        oder umgekehrt. None, wenn nichts kollidiert.

        Für sich genommen ist jeder der beiden Werte eindeutig (partielle
        Unique-Indizes), über Kreuz prüft die Datenbank aber nichts. Seit beides
        als Anmelde-Kennung gilt, muss diese Prüfung jemand machen –
        `UserService._pruefe_kennung_kollision` tut es.

        `ausser_id` klammert das eigene Konto aus: Benutzername *gleich* eigener
        Adresse ist ausdrücklich in Ordnung (beide Wege führen zum selben Konto).
        """
        username = (username or '').strip()
        email = (email or '').strip() or None
        if not username and not email:
            return None
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT username,
                       LOWER(email)    = LOWER(%(u)s) AS name_trifft_adresse,
                       LOWER(username) = LOWER(%(e)s) AS adresse_trifft_namen
                FROM users
                WHERE deleted_at IS NULL
                  AND (id <> %(id)s OR %(id)s IS NULL)
                  AND (LOWER(email) = LOWER(%(u)s) OR LOWER(username) = LOWER(%(e)s))
                ORDER BY id
                LIMIT 1
                """,
                {'u': username or None, 'e': email, 'id': ausser_id}
            )
            return cur.fetchone()

    def get_by_id(self, user_id: int) -> Optional[User]:
        """Find User by ID (only non-deleted)."""
        with self.cursor() as cur:
            cur.execute(
                f"""{_USER_SELECT}
                    WHERE id = %s AND deleted_at IS NULL""",
                (user_id,)
            )
            row = cur.fetchone()
            if not row:
                return None
            return self._load_permissions(self._row_to_user(row))
    
    def get_username(self, user_id: int) -> Optional[str]:
        """Nur den Benutzernamen laden – ohne den teuren Permission-Fanout von
        get_by_id (_load_permissions). Für reine Anzeige-Lookups (z. B. Melder-Name)."""
        with self.cursor() as cur:
            cur.execute(
                "SELECT username FROM users WHERE id = %s AND deleted_at IS NULL",
                (user_id,)
            )
            row = cur.fetchone()
            return row['username'] if row else None

    def list_all(self) -> List[User]:
        """List all users (only non-deleted)."""
        with self.cursor() as cur:
            cur.execute(
                f"""{_USER_SELECT}
                    WHERE deleted_at IS NULL ORDER BY username"""
            )
            return [self._load_permissions(self._row_to_user(row)) for row in cur.fetchall()]
    
    def count_active_admins(self) -> int:
        """Count the number of active administrators."""
        with self.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = 1 AND deleted_at IS NULL"
            )
            return cur.fetchone()['count']
    
    def create(self, username: str, email: Optional[str], password_hash: str, role: str,
               created_by: str, active: bool = True) -> User:
        """Create a new user.

        Args:
            username: Unique username
            email: Email address (None = Konto ohne Zugang, siehe UserService.create)
            password_hash: Already hashed password (hashing done in service layer)
            role: Role ('admin', 'user', 'special', 'readonly')
            created_by: Username of creator
            active: Whether user is active
            
        Returns:
            Created User with default permissions for their role already loaded.
            (History is written automatically via trigger)
        """
        try:
            with self.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users (username, email, password_hash, role, active,
                                       version, created_by, updated_by)
                    VALUES (%s, %s, %s, %s, %s, 1, %s, %s)
                    RETURNING id
                    """,
                    (username, email, password_hash, role, int(active), created_by, created_by)
                )
                user_id = cur.fetchone()['id']
        except UniqueViolation as e:
            detail = str(e)
            if 'email' in detail:
                raise ValueError(f"E-Mail '{email}' ist bereits vergeben")
            if 'username' in detail:
                raise ValueError(f"Benutzername '{username}' ist bereits vergeben")
            raise ValueError("Benutzer existiert bereits")
        
        return self.get_by_id(user_id)
    
    def update(self, user_id: int, username: str, email: Optional[str], role: str,
               active: bool, updated_by: str, expected_version: int) -> bool:
        """Update user data (without password).

        Args:
            user_id: ID of user to update
            username: New username
            email: New email (None = Zugang per Magic-Link entfällt)
            role: New role
            active: New active status
            updated_by: Username of updater
            expected_version: Expected version for optimistic locking
            
        Returns:
            bool: True if update successful, False if version conflict or not found
            (History is written automatically via trigger)
        """
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE users 
                SET username = %s, email = %s, role = %s, active = %s,
                    version = version + 1, updated_by = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND version = %s AND deleted_at IS NULL
                """,
                (username, email, role, int(active), updated_by, user_id, expected_version)
            )
            return cur.rowcount == 1
    
    def update_contact_preferences(self, user_id: int, matrix_id: str | None,
                                   preferred_contact: str, updated_by: str,
                                   expected_version: int) -> bool:
        """Update user contact preferences for notifications.

        Args:
            user_id: ID of user to update
            matrix_id: Matrix ID like @user:matrix.org (optional)
            preferred_contact: Preferred channel ('email', 'matrix')
            updated_by: Username of updater
            expected_version: Expected version for optimistic locking

        Returns:
            bool: True if update successful, False if version conflict or not found
        """
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET matrix_id = %s, preferred_contact = %s,
                    version = version + 1, updated_by = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND version = %s AND deleted_at IS NULL
                """,
                (matrix_id, preferred_contact, updated_by, user_id, expected_version)
            )
            return cur.rowcount == 1
    
    def update_password(self, user_id: int, password_hash: str, updated_by: str,
                       expected_version: int) -> bool:
        """Update user password.
        
        Args:
            user_id: ID of user
            password_hash: New hashed password (hashing done in service layer)
            updated_by: Username of updater
            expected_version: Expected version for optimistic locking
            
        Returns:
            bool: True if update successful, False if version conflict or not found
            (History is written automatically via trigger)
        """
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE users 
                SET password_hash = %s, version = version + 1, 
                    updated_by = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND version = %s AND deleted_at IS NULL
                """,
                (password_hash, updated_by, user_id, expected_version)
            )
            return cur.rowcount == 1
    
    def setze_einladung_status(self, user_id: int, versendet: bool) -> bool:
        """Ergebnis der zuletzt versendeten Einladung am Konto festhalten (Schema v97).

        Wie `update_last_login` ohne version-Bump: Das ist Betriebszustand, keine
        fachliche Änderung – die History soll davon nicht volllaufen.

        `versendet` bezieht sich auf die Übergabe an den Mailserver. Ob die Mail
        ankommt, weiß danach niemand mehr: Ein Bounce läuft an die Absenderadresse
        zurück, nicht in die App.

        Args:
            user_id: Konto, an das die Einladung ging
            versendet: True, wenn der Mailserver sie angenommen hat

        Returns:
            bool: True, wenn das Konto existiert und aktualisiert wurde
        """
        with self.cursor() as cur:
            cur.execute(
                "UPDATE users SET einladung_zuletzt = CURRENT_TIMESTAMP, "
                "einladung_status = %s WHERE id = %s AND deleted_at IS NULL",
                ('ok' if versendet else 'fehler', user_id),
            )
            return cur.rowcount == 1

    def update_last_login(self, user_id: int) -> bool:
        """Update last login timestamp (without incrementing version).
        
        Args:
            user_id: ID of user
            
        Returns:
            bool: True if update successful
        """
        with self.cursor() as cur:
            cur.execute(
                "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = %s AND deleted_at IS NULL",
                (user_id,)
            )
            return cur.rowcount == 1

    def update_last_seen(self, user_id: int) -> bool:
        """Aktualisiert den 'zuletzt aktiv'-Zeitpunkt bei jedem authentifizierten Request.

        Gedrosselt: schreibt höchstens einmal pro Minute, damit ein einzelner
        Seitenaufruf (viele API-Calls) nur einen Write auslöst. Ohne Versions-Bump,
        also kein History-Eintrag.
        """
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE users SET last_seen = CURRENT_TIMESTAMP
                WHERE id = %s AND deleted_at IS NULL
                  AND (last_seen IS NULL OR last_seen::timestamptz < now() - interval '1 minute')
                """,
                (user_id,)
            )
            return cur.rowcount == 1

    def mark_user_deleted(self, user_id: int, deleted_by: str) -> bool:
        """Soft-delete: Mark user as deleted.
        
        Note: Does NOT check for "last admin" constraint - that's business logic in the service layer.
        
        Args:
            user_id: ID of user to delete
            deleted_by: Username of deleter
            
        Returns:
            bool: True if marked as deleted, False if not found or already deleted
            (History is written automatically via trigger)
        """
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET deleted_at = CURRENT_TIMESTAMP,
                    deleted_by = %s,
                    version = version + 1
                WHERE id = %s AND deleted_at IS NULL
                """,
                (deleted_by, user_id)
            )
            return cur.rowcount == 1

    def restore_user(self, user_id: int, restored_by: str) -> bool:
        """Hebt einen Soft-Delete eines Users auf (deleted_at/deleted_by → NULL).

        Hinweis: Stellt KEINE entzogenen Berechtigungen wieder her – die müssen ggf.
        neu vergeben werden. History wird per Trigger geschrieben.

        Returns:
            bool: True wenn wiederhergestellt, False wenn nicht gefunden oder nicht gelöscht
        """
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET deleted_at = NULL,
                    deleted_by = NULL,
                    version = version + 1
                WHERE id = %s AND deleted_at IS NOT NULL
                """,
                (restored_by, user_id)
            )
            return cur.rowcount == 1

    def _row_to_user(self, row) -> User:
        """Convert DB row to User object (ohne Permissions – die lädt _load_permissions)."""
        return User(
            id=row['id'],
            username=row['username'],
            email=row['email'],
            password_hash=row['password_hash'],
            role=row['role'],
            active=bool(row['active']),
            last_login=row['last_login'],
            last_seen=row['last_seen'],
            version=row['version'],
            created_at=row['created_at'],
            created_by=row['created_by'],
            updated_at=row['updated_at'],
            updated_by=row['updated_by'],
            matrix_id=row['matrix_id'],
            preferred_contact=row['preferred_contact']
        )
