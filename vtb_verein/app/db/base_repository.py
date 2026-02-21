'''
Created on 21.02.2026

Base Repository with common database operations.

@author: AI Assistant
'''

from contextlib import contextmanager
import sqlite3
from typing import Generator


class BaseRepository:
    """Base class for all repositories providing common database operations.
    
    Each repository gets a connection and provides:
    - Context manager for cursor handling
    - Common query helpers
    - Transaction management
    """
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    @contextmanager
    def cursor(self) -> Generator[sqlite3.Cursor, None, None]:
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
