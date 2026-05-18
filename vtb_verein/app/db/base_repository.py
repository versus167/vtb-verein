'''
Created on 21.02.2026

Base Repository with common database operations.

@author: AI Assistant
'''

from contextlib import contextmanager
from typing import Generator

import psycopg


class BaseRepository:
    """Base class for all repositories providing common database operations."""

    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    @contextmanager
    def cursor(self) -> Generator[psycopg.Cursor, None, None]:
        """Context manager for cursor with automatic commit/rollback."""
        cur = self.conn.cursor()
        try:
            yield cur
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        finally:
            cur.close()
