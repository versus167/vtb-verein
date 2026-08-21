"""Repository für den read-only Credential-Mirror je Schloss.

Spiegelt die am Schloss eingerichteten Credentials (Fingerprints, Passcodes, App-/eKeys,
IC-Karten) 1:1 aus den TTLock-`*/list`-Endpunkten. Reiner Cloud-Spiegel: kein
Soft-Delete/History/Version. Pro Schloss+Typ wird die Cloud-Liste autoritativ ersetzt
(`replace_for_schloss_typ`), damit am Schloss entfernte Credentials auch lokal verschwinden.

Dazwischen zieht der Mirror nach, was wir selbst ans Schloss geschrieben haben
(`ic_karte_gesetzt`/`ic_karte_entfernt`) – sonst behauptete der Soll-Ist-Abgleich bis
zum nächsten Sync eine Abweichung, die längst erledigt ist.
"""
from psycopg.types.json import Json

from app.models.schliessanlage import CRED_IC, TuerCredential
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

    def list_fuer_abgleich(self, typ: str) -> list[TuerCredential]:
        """Der gespiegelte Ist-Stand eines Credential-Typs über alle aktiven
        Cloud-Schlösser – Grundlage des Soll-Ist-Abgleichs (kein Cloud-Aufruf)."""
        with self.cursor() as cur:
            cur.execute(
                _SELECT + " WHERE c.typ = %s AND s.deleted_at IS NULL "
                          "AND s.aktiv AND s.ttlock_lock_id IS NOT NULL "
                          "ORDER BY s.name, c.ttlock_credential_id",
                (typ,),
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

    # --- Nachziehen, was wir selbst ans Schloss geschrieben haben -----------
    # Der Mirror ist das Ist, gegen das der Soll-Ist-Abgleich prüft. Bliebe er nach
    # einem erfolgreichen Cloud-Write bis zum nächsten Sync stehen, behauptete der
    # Abgleich stundenlang eine Abweichung, die wir gerade beseitigt haben — beim
    # Sperren sogar die kritische „öffnet noch" für eine Karte, die längst gelöscht
    # ist. Autoritativ bleibt der Sync: Er ersetzt die Liste je Schloss und Typ und
    # findet jede Abweichung wieder, die wirklich besteht.
    #
    # `gesehen_am` erbt dabei den Stand DIESES Schlosses, statt auf „jetzt" zu
    # springen: Geschrieben ist nicht gelesen — wir wissen weiterhin nur, was der
    # letzte Sync von diesem Schloss geholt hat. Ein frischer Zeitstempel machte
    # jedes andere Schloss zum veralteten Spiegel und entwertete dort echte Befunde.

    def ic_karte_gesetzt(self, schloss_id: int, *, credential_id: int,
                         name: str | None, kartennummer: str | None,
                         gueltig_von: str | None, gueltig_bis: str | None) -> None:
        """Selbst angelernte/umdatierte IC-Karte im Mirror führen (anlegen oder Fenster
        nachziehen). `raw` bleibt unberührt – das ist der wörtliche Cloud-Payload des
        letzten Syncs und bei einer selbst geschriebenen Karte schlicht leer."""
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tuer_credential
                    (schloss_id, typ, ttlock_credential_id, name, detail,
                     gueltig_von, gueltig_bis, gesehen_am)
                VALUES (%s,%s,%s,%s,%s,%s,%s,
                        (SELECT MAX(gesehen_am) FROM tuer_credential
                          WHERE schloss_id = %s AND typ = %s))
                ON CONFLICT (schloss_id, typ, ttlock_credential_id) DO UPDATE
                   SET name        = EXCLUDED.name,
                       detail      = EXCLUDED.detail,
                       gueltig_von = EXCLUDED.gueltig_von,
                       gueltig_bis = EXCLUDED.gueltig_bis
                """,
                (schloss_id, CRED_IC, credential_id, name, kartennummer,
                 gueltig_von, gueltig_bis, schloss_id, CRED_IC),
            )

    def ic_karte_entfernt(self, schloss_id: int, credential_id: int) -> None:
        """Selbst gelöschte IC-Karte aus dem Mirror nehmen (am Schloss liegt sie nicht mehr)."""
        with self.cursor() as cur:
            cur.execute(
                "DELETE FROM tuer_credential "
                " WHERE schloss_id = %s AND typ = %s AND ttlock_credential_id = %s",
                (schloss_id, CRED_IC, credential_id),
            )
