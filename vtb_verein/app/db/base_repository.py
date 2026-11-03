'''
Created on 21.02.2026

Base Repository with common database operations.

@author: AI Assistant
'''

from contextlib import contextmanager
from typing import Generator

import psycopg


# Merker an der Verbindung: Solange er gesetzt ist, committen die Repositories
# nicht selbst – das übernimmt `sammeltransaktion` am Ende des Blocks.
_SAMMEL_ATTR = '_vtb_sammeltransaktion'


def in_sammeltransaktion(conn: psycopg.Connection) -> bool:
    """Läuft auf dieser Verbindung gerade ein `sammeltransaktion`-Block?"""
    return getattr(conn, _SAMMEL_ATTR, False)


@contextmanager
def sammeltransaktion(conn: psycopg.Connection) -> Generator[psycopg.Connection, None, None]:
    """Alle Repository-Aufrufe im Block in EINER Transaktion: alles oder nichts.

    Normal committet jeder Repository-Aufruf für sich. Für mehrstufige Läufe wie
    die Mitglieder-Importe heißt das: Bricht Zeile 200 ab, stehen die Zeilen davor
    schon in der Datenbank – ein Teilbestand, den ein zweiter Lauf als „schon da"
    überspringt (#66). Im Block committen die Repositories nicht; am Ende wird
    einmal committet, bei einer Ausnahme alles zurückgerollt.

    Nur auf einer Verbindung nutzen, die sonst niemand gleichzeitig verwendet:
    Ein fremdes commit()/rollback() dazwischen würde den halben Block festschreiben
    bzw. still verwerfen. Verschachtelt läuft der innere Block im äußeren mit.
    """
    if in_sammeltransaktion(conn):
        yield conn
        return
    conn.commit()                      # Vorher Offenes nicht in den Block ziehen
    setattr(conn, _SAMMEL_ATTR, True)
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        setattr(conn, _SAMMEL_ATTR, False)


class BaseRepository:
    """Base class for all repositories providing common database operations."""

    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    @contextmanager
    def cursor(self) -> Generator[psycopg.Cursor, None, None]:
        """Context manager for cursor with automatic commit/rollback.

        Innerhalb von `sammeltransaktion` weder commit noch rollback: Den Abschluss
        macht der Block, und eine Ausnahme rollt dort alles zurück.
        """
        cur = self.conn.cursor()
        sammel = in_sammeltransaktion(self.conn)
        try:
            yield cur
            if not sammel:
                self.conn.commit()
        except Exception:
            if not sammel:
                self.conn.rollback()
            raise
        finally:
            cur.close()
