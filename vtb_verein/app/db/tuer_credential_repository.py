"""Repository für den read-only Credential-Mirror je Schloss.

Spiegelt die am Schloss eingerichteten Credentials (Fingerprints, Passcodes, App-/eKeys,
IC-Karten) 1:1 aus den TTLock-`*/list`-Endpunkten. Reiner Cloud-Spiegel: kein
Soft-Delete/History/Version. Pro Schloss+Typ wird die Cloud-Liste autoritativ ersetzt
(`replace_for_schloss_typ`), damit am Schloss entfernte Credentials auch lokal verschwinden.
"""
from psycopg.types.json import Json

from app.models.schliessanlage import TuerCredential
from app.db.base_repository import BaseRepository

_SELECT = """
    SELECT c.id, c.schloss_id, c.typ, c.ttlock_credential_id, c.name, c.detail,
           c.gueltig_von, c.gueltig_bis, c.gesehen_am, c.raw, c.created_at,
           s.name AS schloss_name
    FROM tuer_credential c
    LEFT JOIN tuer_schloss s ON s.id = c.schloss_id
"""


def _map(row) -> TuerCredential:
    return TuerCredential(**dict(row))


class TuerCredentialRepository(BaseRepository):

    def list_for_schloss(self, schloss_id: int) -> list[TuerCredential]:
        with self.cursor() as cur:
            cur.execute(
                _SELECT + " WHERE c.schloss_id = %s "
                          "ORDER BY c.typ, c.name NULLS LAST, c.ttlock_credential_id",
                (schloss_id,),
            )
            return [_map(r) for r in cur.fetchall()]

    def replace_for_schloss_typ(self, schloss_id: int, typ: str,
                                rows: list[TuerCredential]) -> int:
        """Ersetzt den Mirror für (Schloss, Typ) atomar: alte Zeilen löschen, frische
        einfügen. Gibt die Zahl eingefügter Zeilen zurück. Nur aufrufen, wenn die
        Cloud-Liste erfolgreich geholt wurde (sonst würde das Inventar fälschlich geleert)."""
        with self.cursor() as cur:
            cur.execute(
                "DELETE FROM tuer_credential WHERE schloss_id = %s AND typ = %s",
                (schloss_id, typ),
            )
            for c in rows:
                cur.execute(
                    """
                    INSERT INTO tuer_credential
                        (schloss_id, typ, ttlock_credential_id, name, detail,
                         gueltig_von, gueltig_bis, gesehen_am, raw)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (schloss_id, typ, c.ttlock_credential_id, c.name, c.detail,
                     c.gueltig_von, c.gueltig_bis, c.gesehen_am,
                     Json(c.raw) if c.raw is not None else None),
                )
            return len(rows)
