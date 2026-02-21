'''
Created on 21.02.2026

User Repository - All database operations for User entity.

@author: AI Assistant
'''

import sqlite3
from typing import Optional, List
from app.models.user import User
from app.db.base_repository import BaseRepository


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
    
    def get_by_username(self, username: str) -> Optional[User]:
        """Find User by username (only non-deleted)."""
        with self.cursor() as cur:
            cur.execute(
                """SELECT id, username, email, password_hash, role, active, last_login,
                          version, created_at, created_by, updated_at, updated_by
                   FROM users WHERE username = ? AND deleted_at IS NULL""",
                (username,)
            )
            row = cur.fetchone()
            return self._row_to_user(row) if row else None
    
    def get_by_id(self, user_id: int) -> Optional[User]:
        """Find User by ID (only non-deleted)."""
        with self.cursor() as cur:
            cur.execute(
                """SELECT id, username, email, password_hash, role, active, last_login,
                          version, created_at, created_by, updated_at, updated_by
                   FROM users WHERE id = ? AND deleted_at IS NULL""",
                (user_id,)
            )
            row = cur.fetchone()
            return self._row_to_user(row) if row else None
    
    def list_all(self) -> List[User]:
        """List all users (only non-deleted)."""
        with self.cursor() as cur:
            cur.execute(
                """SELECT id, username, email, password_hash, role, active, last_login,
                          version, created_at, created_by, updated_at, updated_by
                   FROM users WHERE deleted_at IS NULL ORDER BY username"""
            )
            return [self._row_to_user(row) for row in cur.fetchall()]
    
    def count_active_admins(self) -> int:
        """Count the number of active administrators."""
        with self.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = 1 AND deleted_at IS NULL"
            )
            return cur.fetchone()[0]
    
    def create(self, username: str, email: str, password_hash: str, role: str,
               created_by: str, active: bool = True) -> User:
        """Create a new user.
        
        Args:
            username: Unique username
            email: Email address
            password_hash: Already hashed password (hashing done in service layer)
            role: Role ('admin', 'user', 'readonly')
            created_by: Username of creator
            active: Whether user is active
            
        Returns:
            Created User (History is written automatically via trigger)
        """
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (username, email, password_hash, role, active, 
                                   version, created_by, updated_by)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (username, email, password_hash, role, active, created_by, created_by)
            )
            user_id = cur.lastrowid
        
        return self.get_by_id(user_id)
    
    def update(self, user_id: int, username: str, email: str, role: str,
               active: bool, updated_by: str, expected_version: int) -> bool:
        """Update user data (without password).
        
        Args:
            user_id: ID of user to update
            username: New username
            email: New email
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
                SET username = ?, email = ?, role = ?, active = ?,
                    version = version + 1, updated_by = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND version = ? AND deleted_at IS NULL
                """,
                (username, email, role, active, updated_by, user_id, expected_version)
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
                SET password_hash = ?, version = version + 1, 
                    updated_by = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND version = ? AND deleted_at IS NULL
                """,
                (password_hash, updated_by, user_id, expected_version)
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
                "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ? AND deleted_at IS NULL",
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
                    deleted_by = ?,
                    version = version + 1
                WHERE id = ? AND deleted_at IS NULL
                """,
                (deleted_by, user_id)
            )
            return cur.rowcount == 1
    
    def _row_to_user(self, row) -> User:
        """Convert DB row to User object."""
        return User(
            id=row['id'],
            username=row['username'],
            email=row['email'],
            password_hash=row['password_hash'],
            role=row['role'],
            active=bool(row['active']),
            last_login=row['last_login'],
            version=row['version'],
            created_at=row['created_at'],
            created_by=row['created_by'],
            updated_at=row['updated_at'],
            updated_by=row['updated_by']
        )
