"""Repository für Spielstätten (Schema v80, Ticket #95).

Stammdaten der Plätze und Hallen — bewusst nicht fußballspezifisch: Tennisplatz und
Turnhalle gehören genauso hinein. Die Tabelle trägt zwei Sonderzeilen (`platzhalter`),
ohne die `termine.spielstaette_id` nicht NOT NULL sein könnte:

* ``auswaerts``  — „Kein Vereinsgelände": bewusste Antwort für Waldlauf, fremde Halle
  und alles, was keine Stammdaten verdient. Auswählbar.
* ``unbekannt``  — „Nicht erfasst": trägt ausschließlich den Altbestand aus der
  Migration und ist NICHT auswählbar; beim nächsten Speichern muss eine echte
  Antwort her.

`ist_eigen` trennt die eigenen Plätze (zählen später in den Belegungsplan) von fremden
Spielstätten (Auswärtsspiel: sauberer Ort, aber keine Belegung).
"""
from typing import Optional

from app.models.spielstaette import Spielstaette
from app.db.base_repository import BaseRepository

# Platzhalter-Schlüssel (Spalte `platzhalter`) – identisch zu database.py.
PLATZHALTER_AUSWAERTS = 'auswaerts'
PLATZHALTER_UNBEKANNT = 'unbekannt'

_COLS = ("id, name, dfbnet_nr, strasse, plz, ort, ist_eigen, parallel_moeglich, "
         "platzhalter, untergrund, version, created_at, created_by, updated_at, "
         "updated_by, deleted_at, deleted_by")

# Reihenfolge ist bindend: create/update reichen die Werte positionsgetreu durch.
_EDIT_FIELDS = ('name', 'dfbnet_nr', 'strasse', 'plz', 'ort', 'ist_eigen',
                'parallel_moeglich', 'untergrund')


def _map(row) -> Spielstaette:
    return Spielstaette(
        id=row['id'], name=row['name'], dfbnet_nr=row['dfbnet_nr'],
        strasse=row['strasse'], plz=row['plz'], ort=row['ort'],
        ist_eigen=row['ist_eigen'], parallel_moeglich=row['parallel_moeglich'],
        platzhalter=row['platzhalter'], untergrund=row['untergrund'],
        version=row['version'],
        created_at=row['created_at'], created_by=row['created_by'],
        updated_at=row['updated_at'], updated_by=row['updated_by'],
        deleted_at=row['deleted_at'], deleted_by=row['deleted_by'],
    )


class SpielstaetteRepository(BaseRepository):

    # ------------------------------------------------------------------ lesen
    def get(self, spielstaette_id: int) -> Optional[Spielstaette]:
        with self.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM spielstaette WHERE id = %s AND deleted_at IS NULL",
                (spielstaette_id,),
            )
            row = cur.fetchone()
            return _map(row) if row else None

    def list_all(self, *, mit_unbekannt: bool = False) -> list[Spielstaette]:
        """Alle lebenden Spielstätten, echte zuerst, Platzhalter ans Ende.

        ``mit_unbekannt`` blendet „Nicht erfasst" ein – nur für Auswertungen und
        den Altbestands-Filter, nicht für Auswahllisten.
        """
        with self.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_COLS} FROM spielstaette
                WHERE deleted_at IS NULL
                  AND (%s OR platzhalter IS NULL OR platzhalter <> %s)
                ORDER BY (platzhalter IS NOT NULL), lower(name)
                """,
                (mit_unbekannt, PLATZHALTER_UNBEKANNT),
            )
            return [_map(r) for r in cur.fetchall()]

    def get_platzhalter(self, schluessel: str) -> Optional[Spielstaette]:
        with self.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM spielstaette "
                "WHERE platzhalter = %s AND deleted_at IS NULL",
                (schluessel,),
            )
            row = cur.fetchone()
            return _map(row) if row else None

    def get_by_dfbnet_nr(self, dfbnet_nr: str) -> Optional[Spielstaette]:
        """Zuordnung für den Spielplan-Import (Etappe 2)."""
        with self.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM spielstaette "
                "WHERE dfbnet_nr = %s AND deleted_at IS NULL",
                (dfbnet_nr,),
            )
            row = cur.fetchone()
            return _map(row) if row else None

    # ---------------------------------------------------------------- ändern
    def create(self, s: Spielstaette, created_by: str) -> Spielstaette:
        with self.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO spielstaette ({', '.join(_EDIT_FIELDS)}, created_by, updated_by)
                VALUES ({', '.join(['%s'] * (len(_EDIT_FIELDS) + 2))})
                RETURNING id
                """,
                (s.name, s.dfbnet_nr or None, s.strasse, s.plz, s.ort,
                 s.ist_eigen, s.parallel_moeglich, s.untergrund,
                 created_by, created_by),
            )
            new_id = cur.fetchone()['id']
        return self.get(new_id)

    def update(self, spielstaette_id: int, s: Spielstaette, updated_by: str,
               expected_version: int) -> bool:
        with self.cursor() as cur:
            cur.execute(
                f"""
                UPDATE spielstaette SET {', '.join(f'{f}=%s' for f in _EDIT_FIELDS)},
                       updated_at=CURRENT_TIMESTAMP, updated_by=%s, version=version+1
                WHERE id=%s AND deleted_at IS NULL AND version=%s
                  AND platzhalter IS NULL
                """,
                (s.name, s.dfbnet_nr or None, s.strasse, s.plz, s.ort,
                 s.ist_eigen, s.parallel_moeglich, s.untergrund, updated_by,
                 spielstaette_id, expected_version),
            )
            return cur.rowcount > 0

    def mark_deleted(self, spielstaette_id: int, deleted_by: str) -> bool:
        """Soft-Delete. Platzhalter sind ausgenommen – ohne sie bräche das
        Pflichtfeld am Termin."""
        with self.cursor() as cur:
            cur.execute(
                "UPDATE spielstaette SET deleted_at = CURRENT_TIMESTAMP, "
                "deleted_by = %s, version = version + 1 "
                "WHERE id = %s AND deleted_at IS NULL AND platzhalter IS NULL",
                (deleted_by, spielstaette_id),
            )
            return cur.rowcount > 0

    def zaehle_termine(self, spielstaette_id: int) -> int:
        """Wie viele lebende Termine/Serien hängen an der Spielstätte?

        Die API nutzt das, um das Löschen mit einer verständlichen Meldung zu
        verweigern, statt den Anwender in einen FK-Fehler laufen zu lassen.
        """
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT (SELECT COUNT(*) FROM termine
                        WHERE spielstaette_id = %(sid)s AND deleted_at IS NULL)
                     + (SELECT COUNT(*) FROM termin_serie
                        WHERE spielstaette_id = %(sid)s AND deleted_at IS NULL) AS anzahl
                """,
                {"sid": spielstaette_id},
            )
            return cur.fetchone()['anzahl']
