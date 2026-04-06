'''
TicketRepository - CRUD für tickets, ticket_bereiche, ticket_kategorien,
ticket_kommentare und ticket_anhaenge.

Alle Spaltennamen entsprechen der DB-Migration 8->9 (deutsche Namen).
'''

from typing import Optional
from app.models.ticket import (
    Ticket, TicketBereich, TicketKategorie,
    TicketKommentar, TicketAnhang, TicketTeilnehmer
)


class TicketRepository:

    def __init__(self, conn):
        self.conn = conn

    # ------------------------------------------------------------------
    # Tickets
    # ------------------------------------------------------------------

    _SELECT_TICKET = (
        "SELECT id, titel, beschreibung, status, prioritaet, "
        "bereich_id, kategorie_id, gemeldet_von, zugewiesen_an, "
        "faellig_am, geschlossen_am, geschlossen_von, "
        "version, created_at, deleted_at, deleted_by FROM tickets"
    )

    def get(self, id: int) -> Optional[Ticket]:
        cursor = self.conn.execute(
            self._SELECT_TICKET + " WHERE id = ?", (id,)
        )
        row = cursor.fetchone()
        return self._map_ticket(row) if row else None

    def list_all(self, include_deleted: bool = False) -> list[Ticket]:
        if include_deleted:
            cursor = self.conn.execute(
                self._SELECT_TICKET + " ORDER BY created_at DESC"
            )
        else:
            cursor = self.conn.execute(
                self._SELECT_TICKET + " WHERE deleted_at IS NULL ORDER BY created_at DESC"
            )
        return [self._map_ticket(row) for row in cursor.fetchall()]

    def list_by_bereich(self, bereich_id: int) -> list[Ticket]:
        cursor = self.conn.execute(
            self._SELECT_TICKET + " WHERE bereich_id = ? AND deleted_at IS NULL ORDER BY created_at DESC",
            (bereich_id,)
        )
        return [self._map_ticket(row) for row in cursor.fetchall()]

    def list_by_status(self, status: str) -> list[Ticket]:
        cursor = self.conn.execute(
            self._SELECT_TICKET + " WHERE status = ? AND deleted_at IS NULL ORDER BY created_at DESC",
            (status,)
        )
        return [self._map_ticket(row) for row in cursor.fetchall()]

    def list_by_zugewiesen(self, user_id: int) -> list[Ticket]:
        cursor = self.conn.execute(
            self._SELECT_TICKET + " WHERE zugewiesen_an = ? AND deleted_at IS NULL ORDER BY created_at DESC",
            (user_id,)
        )
        return [self._map_ticket(row) for row in cursor.fetchall()]

    def list_by_gemeldet(self, user_id: int) -> list[Ticket]:
        cursor = self.conn.execute(
            self._SELECT_TICKET + " WHERE gemeldet_von = ? AND deleted_at IS NULL ORDER BY created_at DESC",
            (user_id,)
        )
        return [self._map_ticket(row) for row in cursor.fetchall()]

    def create(self, ticket: Ticket, created_by: str) -> Ticket:
        cursor = self.conn.execute(
            "INSERT INTO tickets "
            "(titel, beschreibung, status, prioritaet, bereich_id, kategorie_id, "
            "gemeldet_von, zugewiesen_an, faellig_am, created_by, updated_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ticket.titel, ticket.beschreibung, ticket.status, ticket.prioritaet,
                ticket.bereich_id, ticket.kategorie_id, ticket.gemeldet_von,
                ticket.zugewiesen_an, ticket.faellig_am,
                created_by, created_by
            )
        )
        self.conn.commit()
        return self.get(cursor.lastrowid)

    def update(self, ticket: Ticket, updated_by: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE tickets SET "
            "titel = ?, beschreibung = ?, status = ?, prioritaet = ?, "
            "bereich_id = ?, kategorie_id = ?, zugewiesen_an = ?, faellig_am = ?, "
            "geschlossen_am = ?, geschlossen_von = ?, "
            "updated_at = CURRENT_TIMESTAMP, updated_by = ?, version = version + 1 "
            "WHERE id = ? AND version = ? AND deleted_at IS NULL",
            (
                ticket.titel, ticket.beschreibung, ticket.status, ticket.prioritaet,
                ticket.bereich_id, ticket.kategorie_id, ticket.zugewiesen_an, ticket.faellig_am,
                ticket.geschlossen_am, ticket.geschlossen_von,
                updated_by,
                ticket.id, ticket.version
            )
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def mark_deleted(self, id: int, deleted_by: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE tickets SET deleted_at = datetime('now'), deleted_by = ?, "
            "version = version + 1, updated_at = CURRENT_TIMESTAMP, updated_by = ? "
            "WHERE id = ? AND deleted_at IS NULL",
            (deleted_by, deleted_by, id)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def get_history(self, ticket_id: int) -> list[dict]:
        cursor = self.conn.execute(
            "SELECT id, version, titel, status, prioritaet, bereich_id, kategorie_id, "
            "zugewiesen_an, faellig_am, geschlossen_am, geschlossen_von, "
            "deleted_at, deleted_by, created_at, updated_at "
            "FROM tickets_history WHERE id = ? ORDER BY version ASC",
            (ticket_id,)
        )
        cols = [
            'id', 'version', 'titel', 'status', 'prioritaet', 'bereich_id', 'kategorie_id',
            'zugewiesen_an', 'faellig_am', 'geschlossen_am', 'geschlossen_von',
            'deleted_at', 'deleted_by', 'created_at', 'updated_at'
        ]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]

    def _map_ticket(self, row) -> Ticket:
        return Ticket(
            id=row[0], titel=row[1], beschreibung=row[2], status=row[3], prioritaet=row[4],
            bereich_id=row[5], kategorie_id=row[6], gemeldet_von=row[7], zugewiesen_an=row[8],
            faellig_am=row[9], geschlossen_am=row[10], geschlossen_von=row[11],
            version=row[12], created_at=row[13], deleted_at=row[14], deleted_by=row[15]
        )

    # ------------------------------------------------------------------
    # Bereiche
    # ------------------------------------------------------------------

    def get_bereich(self, id: int) -> Optional[TicketBereich]:
        cursor = self.conn.execute(
            "SELECT id, name, beschreibung, version, created_at, deleted_at, deleted_by "
            "FROM ticket_bereiche WHERE id = ?", (id,)
        )
        row = cursor.fetchone()
        return self._map_bereich(row) if row else None

    def list_bereiche(self, include_deleted: bool = False) -> list[TicketBereich]:
        sql = "SELECT id, name, beschreibung, version, created_at, deleted_at, deleted_by FROM ticket_bereiche"
        if not include_deleted:
            sql += " WHERE deleted_at IS NULL"
        sql += " ORDER BY name"
        return [self._map_bereich(row) for row in self.conn.execute(sql).fetchall()]

    def create_bereich(self, bereich: TicketBereich, created_by: str) -> TicketBereich:
        cursor = self.conn.execute(
            "INSERT INTO ticket_bereiche (name, beschreibung, created_by, updated_by) VALUES (?, ?, ?, ?)",
            (bereich.name, bereich.beschreibung, created_by, created_by)
        )
        self.conn.commit()
        return self.get_bereich(cursor.lastrowid)

    def update_bereich(self, bereich: TicketBereich, updated_by: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE ticket_bereiche SET name = ?, beschreibung = ?, "
            "updated_at = CURRENT_TIMESTAMP, updated_by = ?, version = version + 1 "
            "WHERE id = ? AND version = ? AND deleted_at IS NULL",
            (bereich.name, bereich.beschreibung, updated_by, bereich.id, bereich.version)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def mark_bereich_deleted(self, id: int, deleted_by: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE ticket_bereiche SET deleted_at = datetime('now'), deleted_by = ?, "
            "version = version + 1, updated_at = CURRENT_TIMESTAMP, updated_by = ? "
            "WHERE id = ? AND deleted_at IS NULL",
            (deleted_by, deleted_by, id)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def _map_bereich(self, row) -> TicketBereich:
        return TicketBereich(
            id=row[0], name=row[1], beschreibung=row[2],
            version=row[3], created_at=row[4], deleted_at=row[5], deleted_by=row[6]
        )

    # ------------------------------------------------------------------
    # Kategorien
    # ------------------------------------------------------------------

    def get_kategorie(self, id: int) -> Optional[TicketKategorie]:
        cursor = self.conn.execute(
            "SELECT id, name, icon, version, deleted_at, deleted_by "
            "FROM ticket_kategorien WHERE id = ?", (id,)
        )
        row = cursor.fetchone()
        return self._map_kategorie(row) if row else None

    def list_kategorien(self, include_deleted: bool = False) -> list[TicketKategorie]:
        sql = "SELECT id, name, icon, version, deleted_at, deleted_by FROM ticket_kategorien"
        if not include_deleted:
            sql += " WHERE deleted_at IS NULL"
        sql += " ORDER BY name"
        return [self._map_kategorie(row) for row in self.conn.execute(sql).fetchall()]

    def create_kategorie(self, kategorie: TicketKategorie, created_by: str) -> TicketKategorie:
        cursor = self.conn.execute(
            "INSERT INTO ticket_kategorien (name, icon, created_by, updated_by) VALUES (?, ?, ?, ?)",
            (kategorie.name, kategorie.icon, created_by, created_by)
        )
        self.conn.commit()
        return self.get_kategorie(cursor.lastrowid)

    def update_kategorie(self, kategorie: TicketKategorie, updated_by: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE ticket_kategorien SET name = ?, icon = ?, "
            "updated_at = CURRENT_TIMESTAMP, updated_by = ?, version = version + 1 "
            "WHERE id = ? AND version = ? AND deleted_at IS NULL",
            (kategorie.name, kategorie.icon, updated_by, kategorie.id, kategorie.version)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def mark_kategorie_deleted(self, id: int, deleted_by: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE ticket_kategorien SET deleted_at = datetime('now'), deleted_by = ?, "
            "version = version + 1, updated_at = CURRENT_TIMESTAMP, updated_by = ? "
            "WHERE id = ? AND deleted_at IS NULL",
            (deleted_by, deleted_by, id)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def _map_kategorie(self, row) -> TicketKategorie:
        return TicketKategorie(
            id=row[0], name=row[1], icon=row[2],
            version=row[3], deleted_at=row[4], deleted_by=row[5]
        )

    # ------------------------------------------------------------------
    # Kommentare
    # ------------------------------------------------------------------

    _SELECT_KOMMENTAR = (
        "SELECT id, ticket_id, autor_id, inhalt, sichtbarkeit, "
        "version, created_at, deleted_at, deleted_by FROM ticket_kommentare"
    )

    def get_kommentar(self, id: int) -> Optional[TicketKommentar]:
        cursor = self.conn.execute(
            self._SELECT_KOMMENTAR + " WHERE id = ?", (id,)
        )
        row = cursor.fetchone()
        return self._map_kommentar(row) if row else None

    def list_kommentare(self, ticket_id: int, nur_oeffentlich: bool = False) -> list[TicketKommentar]:
        if nur_oeffentlich:
            cursor = self.conn.execute(
                self._SELECT_KOMMENTAR +
                " WHERE ticket_id = ? AND sichtbarkeit = 'oeffentlich' AND deleted_at IS NULL ORDER BY created_at",
                (ticket_id,)
            )
        else:
            cursor = self.conn.execute(
                self._SELECT_KOMMENTAR +
                " WHERE ticket_id = ? AND deleted_at IS NULL ORDER BY created_at",
                (ticket_id,)
            )
        return [self._map_kommentar(row) for row in cursor.fetchall()]

    def create_kommentar(self, kommentar: TicketKommentar, created_by: str) -> TicketKommentar:
        cursor = self.conn.execute(
            "INSERT INTO ticket_kommentare "
            "(ticket_id, autor_id, inhalt, sichtbarkeit, created_by, updated_by) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                kommentar.ticket_id, kommentar.autor_id, kommentar.inhalt,
                kommentar.sichtbarkeit, created_by, created_by
            )
        )
        self.conn.commit()
        return self.get_kommentar(cursor.lastrowid)

    def mark_kommentar_deleted(self, id: int, deleted_by: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE ticket_kommentare SET deleted_at = datetime('now'), deleted_by = ?, "
            "version = version + 1, updated_at = CURRENT_TIMESTAMP, updated_by = ? "
            "WHERE id = ? AND deleted_at IS NULL",
            (deleted_by, deleted_by, id)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def _map_kommentar(self, row) -> TicketKommentar:
        return TicketKommentar(
            id=row[0], ticket_id=row[1], autor_id=row[2], inhalt=row[3],
            sichtbarkeit=row[4], version=row[5], created_at=row[6],
            deleted_at=row[7], deleted_by=row[8]
        )

    # ------------------------------------------------------------------
    # Anhänge
    # ------------------------------------------------------------------

    def list_anhaenge(self, ticket_id: int) -> list[TicketAnhang]:
        cursor = self.conn.execute(
            "SELECT id, ticket_id, kommentar_id, original_name, stored_name, "
            "mime_type, dateigroesse, hochgeladen_von, hochgeladen_am, deleted_at, deleted_by "
            "FROM ticket_anhaenge WHERE ticket_id = ? AND deleted_at IS NULL ORDER BY hochgeladen_am",
            (ticket_id,)
        )
        return [self._map_anhang(row) for row in cursor.fetchall()]

    def _map_anhang(self, row) -> TicketAnhang:
        return TicketAnhang(
            id=row[0], ticket_id=row[1], kommentar_id=row[2],
            original_name=row[3], stored_name=row[4], mime_type=row[5],
            dateigroesse=row[6], hochgeladen_von=row[7], hochgeladen_am=row[8],
            deleted_at=row[9], deleted_by=row[10]
        )

    # ------------------------------------------------------------------
    # Teilnehmer
    # ------------------------------------------------------------------

    def list_teilnehmer(self, ticket_id: int) -> list[TicketTeilnehmer]:
        cursor = self.conn.execute(
            "SELECT ticket_id, user_id, hinzugefuegt_von, hinzugefuegt_am "
            "FROM ticket_teilnehmer WHERE ticket_id = ?",
            (ticket_id,)
        )
        return [
            TicketTeilnehmer(
                ticket_id=row[0], user_id=row[1],
                hinzugefuegt_von=row[2], hinzugefuegt_am=row[3]
            )
            for row in cursor.fetchall()
        ]

    def add_teilnehmer(self, ticket_id: int, user_id: int, hinzugefuegt_von: int) -> bool:
        try:
            self.conn.execute(
                "INSERT INTO ticket_teilnehmer (ticket_id, user_id, hinzugefuegt_von) VALUES (?, ?, ?)",
                (ticket_id, user_id, hinzugefuegt_von)
            )
            self.conn.commit()
            return True
        except Exception:
            return False

    def remove_teilnehmer(self, ticket_id: int, user_id: int) -> bool:
        cursor = self.conn.execute(
            "DELETE FROM ticket_teilnehmer WHERE ticket_id = ? AND user_id = ?",
            (ticket_id, user_id)
        )
        self.conn.commit()
        return cursor.rowcount > 0
