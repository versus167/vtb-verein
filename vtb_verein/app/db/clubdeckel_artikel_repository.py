"""Artikel-Katalog des Teamtresors (#98): clubdeckel_artikel.

Der „Deckelinhalt" — Getränke/Waren mit Preis, in Gruppen organisiert, gepflegt
von den Warten. Der Preis wird beim Konsum als Betrag eingefroren (Snapshot in
clubdeckel_buchung); spätere Preisänderungen wirken nur auf neue Buchungen.
Der Verkäufer kommt aus der Gruppe (Team oder Mitglied, siehe Gruppe-Repo).
"""
from decimal import Decimal
from typing import Optional

from app.models.clubdeckel import ClubdeckelArtikel
from app.db.base_repository import BaseRepository

_COLS = ("id, deckel_id, gruppe_id, name, preis, aktiv, sortierung, version, "
         "created_at, created_by, updated_at, updated_by, deleted_at, deleted_by")
_A_COLS = ", ".join("a." + s.strip() for s in _COLS.split(","))


def _map(row) -> ClubdeckelArtikel:
    return ClubdeckelArtikel(**dict(row))


class ClubdeckelArtikelRepository(BaseRepository):

    def list_for_deckel(self, deckel_id: int,
                        nur_aktive: bool = False) -> list[dict]:
        """Katalog mit Gruppen-/Verkäufer-Infos. nur_aktive filtert zusätzlich
        auf aktive Gruppen (Artikel ohne Gruppe verkauft das Team)."""
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_A_COLS},
                       g.name AS gruppe_name, g.aktiv AS gruppe_aktiv,
                       g.sortierung AS gruppe_sortierung,
                       g.verkaeufer_mitglied_id,
                       v.vorname || ' ' || v.nachname AS verkaeufer_name
                FROM clubdeckel_artikel a
                LEFT JOIN clubdeckel_gruppe g ON g.id = a.gruppe_id AND g.deleted_at IS NULL
                LEFT JOIN mitglied v ON v.id = g.verkaeufer_mitglied_id
                WHERE a.deckel_id = %s AND a.deleted_at IS NULL
                """ + ("AND a.aktiv = 1 AND COALESCE(g.aktiv, 1) = 1 "
                       if nur_aktive else "") + """
                ORDER BY COALESCE(g.sortierung, 0), lower(COALESCE(g.name, '')),
                         a.sortierung, lower(a.name), a.id
                """,
                (deckel_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def get(self, artikel_id: int) -> Optional[ClubdeckelArtikel]:
        with self.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM clubdeckel_artikel "
                "WHERE id = %s AND deleted_at IS NULL",
                (artikel_id,),
            )
            row = cur.fetchone()
            return _map(row) if row else None

    def get_mit_verkaeufer(self, artikel_id: int) -> Optional[dict]:
        """Artikel plus Verkäufer seiner Gruppe — Grundlage der Konsum-Buchung."""
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_A_COLS},
                       g.aktiv AS gruppe_aktiv, g.verkaeufer_mitglied_id
                FROM clubdeckel_artikel a
                LEFT JOIN clubdeckel_gruppe g ON g.id = a.gruppe_id AND g.deleted_at IS NULL
                WHERE a.id = %s AND a.deleted_at IS NULL
                """,
                (artikel_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def create(self, deckel_id: int, gruppe_id: Optional[int], name: str,
               preis: Decimal, aktiv: int, sortierung: int,
               created_by: str) -> ClubdeckelArtikel:
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO clubdeckel_artikel "
                "(deckel_id, gruppe_id, name, preis, aktiv, sortierung, "
                " created_by, updated_by) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (deckel_id, gruppe_id, name, preis, aktiv, sortierung,
                 created_by, created_by),
            )
            new_id = cur.fetchone()['id']
        return self.get(new_id)

    def update(self, artikel_id: int, gruppe_id: Optional[int], name: str,
               preis: Decimal, aktiv: int, sortierung: int,
               updated_by: str, expected_version: int) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE clubdeckel_artikel SET gruppe_id=%s, name=%s, preis=%s, "
                "aktiv=%s, sortierung=%s, updated_at=CURRENT_TIMESTAMP, updated_by=%s, "
                "version=version+1 "
                "WHERE id=%s AND deleted_at IS NULL AND version=%s",
                (gruppe_id, name, preis, aktiv, sortierung, updated_by,
                 artikel_id, expected_version),
            )
            return cur.rowcount > 0

    def mark_deleted(self, artikel_id: int, deleted_by: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE clubdeckel_artikel SET deleted_at=CURRENT_TIMESTAMP, "
                "deleted_by=%s, version=version+1 "
                "WHERE id=%s AND deleted_at IS NULL",
                (deleted_by, artikel_id),
            )
            return cur.rowcount > 0
