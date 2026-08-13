"""Repository für den Stand des Spielplan-Imports (#171).

Einzeiliger Laufzeitstatus (Muster :class:`TTLockKontoRepository`): Es gibt genau
eine Zeile, die bei jedem übernommenen Import überschrieben wird. `datei_datum` ist
das Änderungsdatum der eingelesenen CSV — der Stand, den der Anwender meint; wann
jemand sie eingelesen hat, steht daneben. `zeitraum_von`/`_bis` nennen den ersten
und letzten Spieltag der Datei: Zwei gleich große Dateien können verschiedene
Quartale abdecken, und der Dateiname sagt dazu nichts.
"""
from typing import Optional

from app.db.base_repository import BaseRepository

_SELECT = """
    SELECT id, dateiname, datei_datum, importiert_am, importiert_von, anzahl_spiele,
           zeitraum_von, zeitraum_bis,
           version, created_at, created_by, updated_at, updated_by
    FROM dfbnet_import_stand
    ORDER BY id
    LIMIT 1
"""


class DfbnetImportStandRepository(BaseRepository):

    def get(self) -> Optional[dict]:
        """Der letzte Stand; ``None``, solange nie ein Spielplan übernommen wurde."""
        with self.cursor() as cur:
            cur.execute(_SELECT)
            row = cur.fetchone()
            return dict(row) if row else None

    def verlauf(self, limit: int = 20) -> list[dict]:
        """Die letzten Importe, jüngster zuerst – aus der History.

        Die kommt gratis: Jeder Import bumpt `version`, der Audit-Trigger schreibt
        den Stand fort. Damit ist nachvollziehbar, wer wie oft eingelesen hat."""
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT version, dateiname, datei_datum, importiert_am, importiert_von,
                       anzahl_spiele, zeitraum_von, zeitraum_bis
                FROM dfbnet_import_stand_history
                ORDER BY importiert_am DESC, version DESC
                LIMIT %s
                """,
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]

    def set(self, *, dateiname: Optional[str], datei_datum: Optional[str],
            anzahl_spiele: Optional[int], by: str,
            zeitraum_von: Optional[str] = None,
            zeitraum_bis: Optional[str] = None) -> dict:
        """Stand fortschreiben – legt die eine Zeile an oder überschreibt sie.

        Der `version`-Bump ist kein Beiwerk: Er löst den Audit-Trigger aus und legt
        damit den vorigen Stand in der History ab (siehe `verlauf`)."""
        with self.cursor() as cur:
            cur.execute("SELECT id FROM dfbnet_import_stand ORDER BY id LIMIT 1")
            row = cur.fetchone()
            if row:
                cur.execute(
                    """
                    UPDATE dfbnet_import_stand
                    SET dateiname=%s, datei_datum=%s, anzahl_spiele=%s,
                        zeitraum_von=%s, zeitraum_bis=%s,
                        importiert_am=CURRENT_TIMESTAMP, importiert_von=%s,
                        version=version+1, updated_at=CURRENT_TIMESTAMP, updated_by=%s
                    WHERE id=%s
                    """,
                    (dateiname, datei_datum, anzahl_spiele, zeitraum_von,
                     zeitraum_bis, by, by, row['id']),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO dfbnet_import_stand
                        (dateiname, datei_datum, anzahl_spiele, zeitraum_von,
                         zeitraum_bis, importiert_von, created_by, updated_by)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (dateiname, datei_datum, anzahl_spiele, zeitraum_von,
                     zeitraum_bis, by, by, by),
                )
        return self.get()
