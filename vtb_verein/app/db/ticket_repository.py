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
        "version, created_at, updated_at, deleted_at, deleted_by FROM tickets"
    )

    def get(self, id: int) -> Optional[Ticket]:
        cursor = self.conn.execute(
            self._SELECT_TICKET + " WHERE id = %s", (id,)
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
            self._SELECT_TICKET + " WHERE bereich_id = %s AND deleted_at IS NULL ORDER BY created_at DESC",
            (bereich_id,)
        )
        return [self._map_ticket(row) for row in cursor.fetchall()]

    def list_by_status(self, status: str) -> list[Ticket]:
        cursor = self.conn.execute(
            self._SELECT_TICKET + " WHERE status = %s AND deleted_at IS NULL ORDER BY created_at DESC",
            (status,)
        )
        return [self._map_ticket(row) for row in cursor.fetchall()]

    def list_by_zugewiesen(self, user_id: int) -> list[Ticket]:
        cursor = self.conn.execute(
            self._SELECT_TICKET + " WHERE zugewiesen_an = %s AND deleted_at IS NULL ORDER BY created_at DESC",
            (user_id,)
        )
        return [self._map_ticket(row) for row in cursor.fetchall()]

    def list_by_gemeldet(self, user_id: int) -> list[Ticket]:
        cursor = self.conn.execute(
            self._SELECT_TICKET + " WHERE gemeldet_von = %s AND deleted_at IS NULL ORDER BY created_at DESC",
            (user_id,)
        )
        return [self._map_ticket(row) for row in cursor.fetchall()]

    def create(self, ticket: Ticket, created_by: str) -> Ticket:
        cursor = self.conn.execute(
            "INSERT INTO tickets "
            "(titel, beschreibung, status, prioritaet, bereich_id, kategorie_id, "
            "gemeldet_von, zugewiesen_an, faellig_am, created_by, updated_by) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (
                ticket.titel, ticket.beschreibung, ticket.status, ticket.prioritaet,
                ticket.bereich_id, ticket.kategorie_id, ticket.gemeldet_von,
                ticket.zugewiesen_an, ticket.faellig_am,
                created_by, created_by
            )
        )
        self.conn.commit()
        return self.get(cursor.fetchone()['id'])

    def update(self, ticket: Ticket, updated_by: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE tickets SET "
            "titel = %s, beschreibung = %s, status = %s, prioritaet = %s, "
            "bereich_id = %s, kategorie_id = %s, zugewiesen_an = %s, faellig_am = %s, "
            "geschlossen_am = %s, geschlossen_von = %s, "
            "updated_at = CURRENT_TIMESTAMP, updated_by = %s, version = version + 1 "
            "WHERE id = %s AND version = %s AND deleted_at IS NULL",
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
            "UPDATE tickets SET deleted_at = CURRENT_TIMESTAMP, deleted_by = %s, "
            "version = version + 1, updated_at = CURRENT_TIMESTAMP, updated_by = %s "
            "WHERE id = %s AND deleted_at IS NULL",
            (deleted_by, deleted_by, id)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def restore(self, id: int, restored_by: str) -> bool:
        """Hebt einen Soft-Delete wieder auf (Ticket erscheint wieder in der Liste)."""
        cursor = self.conn.execute(
            "UPDATE tickets SET deleted_at = NULL, deleted_by = NULL, "
            "version = version + 1, updated_at = CURRENT_TIMESTAMP, updated_by = %s "
            "WHERE id = %s AND deleted_at IS NOT NULL",
            (restored_by, id)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def get_history(self, ticket_id: int) -> list[dict]:
        cursor = self.conn.execute(
            "SELECT id, version, titel, status, prioritaet, bereich_id, kategorie_id, "
            "zugewiesen_an, faellig_am, geschlossen_am, geschlossen_von, "
            "deleted_at, deleted_by, created_at, updated_at "
            "FROM tickets_history WHERE id = %s ORDER BY version ASC",
            (ticket_id,)
        )
        cols = [
            'id', 'version', 'titel', 'status', 'prioritaet', 'bereich_id', 'kategorie_id',
            'zugewiesen_an', 'faellig_am', 'geschlossen_am', 'geschlossen_von',
            'deleted_at', 'deleted_by', 'created_at', 'updated_at'
        ]
        return [dict(row) for row in cursor.fetchall()]

    def list_all_with_counts(self, nur_geloeschte: bool = False) -> list[Ticket]:
        if nur_geloeschte:
            where_order = "WHERE t.deleted_at IS NOT NULL ORDER BY t.deleted_at DESC"
        else:
            where_order = "WHERE t.deleted_at IS NULL ORDER BY t.updated_at DESC"
        cursor = self.conn.execute(
            "SELECT t.id, t.titel, t.beschreibung, t.status, t.prioritaet, "
            "t.bereich_id, t.kategorie_id, t.gemeldet_von, t.zugewiesen_an, "
            "t.faellig_am, t.geschlossen_am, t.geschlossen_von, "
            "t.version, t.created_at, t.updated_at, t.deleted_at, t.deleted_by, "
            "(SELECT COUNT(*) FROM ticket_kommentare k "
            " WHERE k.ticket_id = t.id AND k.deleted_at IS NULL) AS kommentar_count, "
            "(SELECT COUNT(*) FROM ticket_anhaenge a "
            " WHERE a.ticket_id = t.id AND a.deleted_at IS NULL) AS anhang_count "
            "FROM tickets t " + where_order
        )
        return [self._map_ticket_with_counts(row) for row in cursor.fetchall()]

    def _map_ticket(self, row) -> Ticket:
        return Ticket(
            id=row['id'], titel=row['titel'], beschreibung=row['beschreibung'],
            status=row['status'], prioritaet=row['prioritaet'],
            bereich_id=row['bereich_id'], kategorie_id=row['kategorie_id'],
            gemeldet_von=row['gemeldet_von'], zugewiesen_an=row['zugewiesen_an'],
            faellig_am=row['faellig_am'], geschlossen_am=row['geschlossen_am'],
            geschlossen_von=row['geschlossen_von'],
            version=row['version'], created_at=row['created_at'], updated_at=row['updated_at'],
            deleted_at=row['deleted_at'], deleted_by=row['deleted_by']
        )

    def _map_ticket_with_counts(self, row) -> Ticket:
        return Ticket(
            id=row['id'], titel=row['titel'], beschreibung=row['beschreibung'],
            status=row['status'], prioritaet=row['prioritaet'],
            bereich_id=row['bereich_id'], kategorie_id=row['kategorie_id'],
            gemeldet_von=row['gemeldet_von'], zugewiesen_an=row['zugewiesen_an'],
            faellig_am=row['faellig_am'], geschlossen_am=row['geschlossen_am'],
            geschlossen_von=row['geschlossen_von'],
            version=row['version'], created_at=row['created_at'], updated_at=row['updated_at'],
            deleted_at=row['deleted_at'], deleted_by=row['deleted_by'],
            kommentar_count=row['kommentar_count'], anhang_count=row['anhang_count']
        )

    # ------------------------------------------------------------------
    # Bereiche
    # ------------------------------------------------------------------

    def get_bereich(self, id: int) -> Optional[TicketBereich]:
        cursor = self.conn.execute(
            "SELECT id, name, beschreibung, version, created_at, deleted_at, deleted_by "
            "FROM ticket_bereiche WHERE id = %s", (id,)
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
            "INSERT INTO ticket_bereiche (name, beschreibung, created_by, updated_by) VALUES (%s, %s, %s, %s) RETURNING id",
            (bereich.name, bereich.beschreibung, created_by, created_by)
        )
        self.conn.commit()
        return self.get_bereich(cursor.fetchone()['id'])

    def update_bereich(self, bereich: TicketBereich, updated_by: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE ticket_bereiche SET name = %s, beschreibung = %s, "
            "updated_at = CURRENT_TIMESTAMP, updated_by = %s, version = version + 1 "
            "WHERE id = %s AND version = %s AND deleted_at IS NULL",
            (bereich.name, bereich.beschreibung, updated_by, bereich.id, bereich.version)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def mark_bereich_deleted(self, id: int, deleted_by: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE ticket_bereiche SET deleted_at = CURRENT_TIMESTAMP, deleted_by = %s, "
            "version = version + 1, updated_at = CURRENT_TIMESTAMP, updated_by = %s "
            "WHERE id = %s AND deleted_at IS NULL",
            (deleted_by, deleted_by, id)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def _map_bereich(self, row) -> TicketBereich:
        return TicketBereich(
            id=row['id'], name=row['name'], beschreibung=row['beschreibung'],
            version=row['version'], created_at=row['created_at'],
            deleted_at=row['deleted_at'], deleted_by=row['deleted_by']
        )

    # ------------------------------------------------------------------
    # Kategorien
    # ------------------------------------------------------------------

    def get_kategorie(self, id: int) -> Optional[TicketKategorie]:
        cursor = self.conn.execute(
            "SELECT id, name, icon, version, deleted_at, deleted_by "
            "FROM ticket_kategorien WHERE id = %s", (id,)
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
            "INSERT INTO ticket_kategorien (name, icon, created_by, updated_by) VALUES (%s, %s, %s, %s) RETURNING id",
            (kategorie.name, kategorie.icon, created_by, created_by)
        )
        self.conn.commit()
        return self.get_kategorie(cursor.fetchone()['id'])

    def update_kategorie(self, kategorie: TicketKategorie, updated_by: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE ticket_kategorien SET name = %s, icon = %s, "
            "updated_at = CURRENT_TIMESTAMP, updated_by = %s, version = version + 1 "
            "WHERE id = %s AND version = %s AND deleted_at IS NULL",
            (kategorie.name, kategorie.icon, updated_by, kategorie.id, kategorie.version)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def mark_kategorie_deleted(self, id: int, deleted_by: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE ticket_kategorien SET deleted_at = CURRENT_TIMESTAMP, deleted_by = %s, "
            "version = version + 1, updated_at = CURRENT_TIMESTAMP, updated_by = %s "
            "WHERE id = %s AND deleted_at IS NULL",
            (deleted_by, deleted_by, id)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def _map_kategorie(self, row) -> TicketKategorie:
        return TicketKategorie(
            id=row['id'], name=row['name'], icon=row['icon'],
            version=row['version'], deleted_at=row['deleted_at'], deleted_by=row['deleted_by']
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
            self._SELECT_KOMMENTAR + " WHERE id = %s", (id,)
        )
        row = cursor.fetchone()
        return self._map_kommentar(row) if row else None

    def list_kommentare(self, ticket_id: int, nur_oeffentlich: bool = False) -> list[TicketKommentar]:
        if nur_oeffentlich:
            cursor = self.conn.execute(
                self._SELECT_KOMMENTAR +
                " WHERE ticket_id = %s AND sichtbarkeit = 'oeffentlich' AND deleted_at IS NULL ORDER BY created_at",
                (ticket_id,)
            )
        else:
            cursor = self.conn.execute(
                self._SELECT_KOMMENTAR +
                " WHERE ticket_id = %s AND deleted_at IS NULL ORDER BY created_at",
                (ticket_id,)
            )
        return [self._map_kommentar(row) for row in cursor.fetchall()]

    def create_kommentar(self, kommentar: TicketKommentar, created_by: str) -> TicketKommentar:
        cursor = self.conn.execute(
            "INSERT INTO ticket_kommentare "
            "(ticket_id, autor_id, inhalt, sichtbarkeit, created_by, updated_by) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (
                kommentar.ticket_id, kommentar.autor_id, kommentar.inhalt,
                kommentar.sichtbarkeit, created_by, created_by
            )
        )
        self.conn.commit()
        return self.get_kommentar(cursor.fetchone()['id'])

    def mark_kommentar_deleted(self, id: int, deleted_by: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE ticket_kommentare SET deleted_at = CURRENT_TIMESTAMP, deleted_by = %s, "
            "version = version + 1, updated_at = CURRENT_TIMESTAMP, updated_by = %s "
            "WHERE id = %s AND deleted_at IS NULL",
            (deleted_by, deleted_by, id)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def _map_kommentar(self, row) -> TicketKommentar:
        return TicketKommentar(
            id=row['id'], ticket_id=row['ticket_id'], autor_id=row['autor_id'],
            inhalt=row['inhalt'], sichtbarkeit=row['sichtbarkeit'],
            version=row['version'], created_at=row['created_at'],
            deleted_at=row['deleted_at'], deleted_by=row['deleted_by']
        )

    # ------------------------------------------------------------------
    # Anhänge
    # ------------------------------------------------------------------

    def list_anhaenge(self, ticket_id: int) -> list[TicketAnhang]:
        cursor = self.conn.execute(
            "SELECT id, ticket_id, kommentar_id, original_name, stored_name, "
            "mime_type, dateigroesse, hochgeladen_von, hochgeladen_am, deleted_at, deleted_by "
            "FROM ticket_anhaenge WHERE ticket_id = %s AND deleted_at IS NULL ORDER BY hochgeladen_am",
            (ticket_id,)
        )
        return [self._map_anhang(row) for row in cursor.fetchall()]

    def _map_anhang(self, row) -> TicketAnhang:
        return TicketAnhang(
            id=row['id'], ticket_id=row['ticket_id'], kommentar_id=row['kommentar_id'],
            original_name=row['original_name'], stored_name=row['stored_name'],
            mime_type=row['mime_type'], dateigroesse=row['dateigroesse'],
            hochgeladen_von=row['hochgeladen_von'], hochgeladen_am=row['hochgeladen_am'],
            deleted_at=row['deleted_at'], deleted_by=row['deleted_by']
        )

    # ------------------------------------------------------------------
    # Teilnehmer
    # ------------------------------------------------------------------

    def list_teilnehmer(self, ticket_id: int) -> list[TicketTeilnehmer]:
        cursor = self.conn.execute(
            "SELECT ticket_id, user_id, hinzugefuegt_von, hinzugefuegt_am "
            "FROM ticket_teilnehmer WHERE ticket_id = %s AND deleted_at IS NULL",
            (ticket_id,)
        )
        return [
            TicketTeilnehmer(
                ticket_id=row['ticket_id'], user_id=row['user_id'],
                hinzugefuegt_von=row['hinzugefuegt_von'], hinzugefuegt_am=row['hinzugefuegt_am']
            )
            for row in cursor.fetchall()
        ]

    def add_teilnehmer(self, ticket_id: int, user_id: int, hinzugefuegt_von: int, by: str) -> bool:
        try:
            self.conn.execute(
                "INSERT INTO ticket_teilnehmer "
                "(ticket_id, user_id, hinzugefuegt_von, created_by, updated_by) "
                "VALUES (%s, %s, %s, %s, %s)",
                (ticket_id, user_id, hinzugefuegt_von, by, by)
            )
            self.conn.commit()
            return True
        except Exception:
            self.conn.rollback()
            return False

    def remove_teilnehmer(self, ticket_id: int, user_id: int, by: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE ticket_teilnehmer "
            "SET deleted_at = CURRENT_TIMESTAMP, deleted_by = %s, "
            "    updated_at = CURRENT_TIMESTAMP, updated_by = %s, version = version + 1 "
            "WHERE ticket_id = %s AND user_id = %s AND deleted_at IS NULL",
            (by, by, ticket_id, user_id)
        )
        self.conn.commit()
        return cursor.rowcount > 0
