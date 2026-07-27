"""Repository für eingereichte Rechnungen (Header).

Statuswechsel laufen bewusst als UPDATE mit Status-Bedingung in der WHERE-Klausel
(`rowcount == 1`) statt als Read-Modify-Write: so kann ein zweiter Freigeber nicht
denselben Übergang doppelt ausführen. Muster wie ul_abrechnung_repository.
"""
from typing import Optional

from app.models.rechnung import Rechnung, STATUS_EXPORTIERT
from app.db.base_repository import BaseRepository


_SELECT = """
    SELECT r.id, r.abteilung_id, r.kategorie_id, r.ersteller_user_id, r.beschreibung,
           r.status, r.betrag_cent, r.rechnungsdatum, r.rechnungsnummer,
           r.empfaenger_typ, r.empfaenger_mitglied_id, r.empfaenger_name, r.empfaenger_iban,
           r.eingereicht_am, r.eingereicht_von, r.freigegeben_am, r.freigegeben_von,
           r.abgelehnt_grund, r.exportiert_in_export_id,
           k.name AS kategorie_name, k.sachkonto AS kategorie_sachkonto,
           ab.name AS abteilung_name, ab.kostenstelle AS abteilung_kostenstelle,
           u.username AS ersteller_name,
           TRIM(COALESCE(em.vorname, '') || ' ' || COALESCE(em.nachname, ''))
               AS empfaenger_mitglied_name,
           -- Bei Erstattung an ein Mitglied kommt die Bankverbindung aus dem
           -- Mitgliedsstamm; an der Rechnung wird sie nicht doppelt gepflegt.
           em.iban AS empfaenger_mitglied_iban,
           (SELECT COUNT(*) FROM rechnung_anhaenge a
             WHERE a.rechnung_id = r.id AND a.deleted_at IS NULL) AS anhang_count,
           r.version, r.created_at, r.created_by, r.updated_at, r.updated_by,
           r.deleted_at, r.deleted_by
    FROM rechnung r
    LEFT JOIN rechnung_kategorie k ON k.id = r.kategorie_id
    LEFT JOIN abteilung ab ON ab.id = r.abteilung_id
    LEFT JOIN users u ON u.id = r.ersteller_user_id
    LEFT JOIN mitglied em ON em.id = r.empfaenger_mitglied_id
"""

_ORDER = " ORDER BY r.id DESC"


def _map(row) -> Rechnung:
    return Rechnung(**dict(row))


class RechnungRepository(BaseRepository):

    # ---------------------------------------------------------------- Lesen
    def get(self, id: int) -> Optional[Rechnung]:
        with self.cursor() as cur:
            cur.execute(_SELECT + " WHERE r.id = %s AND r.deleted_at IS NULL", (id,))
            row = cur.fetchone()
            return _map(row) if row else None

    @staticmethod
    def _status_bedingung(status: Optional[str], params: list) -> str:
        """Statusfilter inkl. des abgeleiteten 'exportiert'.

        Exportierte Rechnungen tragen in der Spalte weiter 'freigegeben'; für die
        Oberfläche sind sie ein eigener Status. Damit beides zusammenpasst, holt
        der Filter 'freigegeben' nur die noch nicht gestempelten – sonst stünde
        eine Rechnung unter zwei Filtern und trüge nur ein Chip.
        """
        if not status:
            return ""
        if status == STATUS_EXPORTIERT:
            return " AND r.exportiert_in_export_id IS NOT NULL"
        params.append(status)
        return " AND r.status = %s AND r.exportiert_in_export_id IS NULL"

    def list_for_ersteller(self, user_id: int, status: Optional[str] = None) -> list[Rechnung]:
        where = " WHERE r.ersteller_user_id = %s AND r.deleted_at IS NULL"
        params: list = [user_id]
        where += self._status_bedingung(status, params)
        with self.cursor() as cur:
            cur.execute(_SELECT + where + _ORDER, params)
            return [_map(r) for r in cur.fetchall()]

    def _freigabe_where(self, abteilung_ids: Optional[set[int]],
                        status: Optional[str], include_vereinsrechnungen: bool,
                        ohne_entwuerfe: bool, params: list) -> Optional[str]:
        """WHERE der Freigeber-Sicht; ``None`` = die Auswahl ist per Definition leer.

        Bewusst geteilt zwischen Liste und COUNT: die Zahl am Nav-Punkt muss zu
        der Liste passen, die sich dahinter öffnet (#133).
        """
        where = " WHERE r.deleted_at IS NULL"
        if ohne_entwuerfe:
            where += " AND r.status <> 'entwurf'"
        if abteilung_ids is not None:
            if not abteilung_ids and not include_vereinsrechnungen:
                return None
            if abteilung_ids and include_vereinsrechnungen:
                where += " AND (r.abteilung_id = ANY(%s) OR r.abteilung_id IS NULL)"
                params.append(list(abteilung_ids))
            elif abteilung_ids:
                where += " AND r.abteilung_id = ANY(%s)"
                params.append(list(abteilung_ids))
            else:
                where += " AND r.abteilung_id IS NULL"
        return where + self._status_bedingung(status, params)

    def list_for_abteilungen(self, abteilung_ids: Optional[set[int]],
                             status: Optional[str] = None,
                             include_vereinsrechnungen: bool = False,
                             ohne_entwuerfe: bool = False) -> list[Rechnung]:
        """Freigeber-Sicht.

        abteilung_ids None = keine Einschränkung (global berechtigt / Verwaltung).
        include_vereinsrechnungen zieht zusätzlich Rechnungen ohne Abteilung
        (abteilung_id IS NULL) heran – die darf nur die Geschäftsstelle freigeben.
        ohne_entwuerfe blendet fremde Entwürfe aus: bis zum Einreichen ist die
        Rechnung die Werkbank des Einreichers und für den Freigeber nichts, woran
        er etwas tun könnte.
        """
        params: list = []
        where = self._freigabe_where(abteilung_ids, status,
                                     include_vereinsrechnungen, ohne_entwuerfe, params)
        if where is None:
            return []
        with self.cursor() as cur:
            cur.execute(_SELECT + where + _ORDER, params)
            return [_map(r) for r in cur.fetchall()]

    def count_for_abteilungen(self, abteilung_ids: Optional[set[int]],
                              status: Optional[str] = None,
                              include_vereinsrechnungen: bool = False,
                              ohne_entwuerfe: bool = False) -> int:
        """Nur die Anzahl – für den Aufgaben-Hinweis an Kachel und Nav (#133)."""
        params: list = []
        where = self._freigabe_where(abteilung_ids, status,
                                     include_vereinsrechnungen, ohne_entwuerfe, params)
        if where is None:
            return 0
        with self.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS anzahl FROM rechnung r" + where, params)
            return cur.fetchone()["anzahl"]

    def list_all(self, status: Optional[str] = None) -> list[Rechnung]:
        return self.list_for_abteilungen(None, status)

    def list_freigegeben_offen(self) -> list[Rechnung]:
        """Export-Delta: freigegeben und noch in keinem Lauf gestempelt."""
        with self.cursor() as cur:
            cur.execute(
                _SELECT + " WHERE r.deleted_at IS NULL AND r.status = 'freigegeben' "
                          " AND r.exportiert_in_export_id IS NULL ORDER BY r.id"
            )
            return [_map(r) for r in cur.fetchall()]

    def list_fuer_export(self, export_id: int) -> list[Rechnung]:
        """Re-Download: die in einem Lauf gestempelten Rechnungen."""
        with self.cursor() as cur:
            cur.execute(
                _SELECT + " WHERE r.exportiert_in_export_id = %s ORDER BY r.id",
                (export_id,),
            )
            return [_map(r) for r in cur.fetchall()]

    # -------------------------------------------------------------- Schreiben
    def create(self, r: Rechnung, created_by: str) -> Rechnung:
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO rechnung
                    (abteilung_id, kategorie_id, ersteller_user_id, beschreibung, status,
                     betrag_cent, rechnungsdatum, rechnungsnummer,
                     empfaenger_typ, empfaenger_mitglied_id, empfaenger_name, empfaenger_iban,
                     created_by, updated_at, updated_by)
                VALUES (%s,%s,%s,%s,'entwurf',%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP,%s)
                RETURNING id
                """,
                (r.abteilung_id, r.kategorie_id, r.ersteller_user_id, r.beschreibung,
                 r.betrag_cent, r.rechnungsdatum, r.rechnungsnummer,
                 r.empfaenger_typ, r.empfaenger_mitglied_id, r.empfaenger_name,
                 r.empfaenger_iban, created_by, created_by),
            )
            new_id = cur.fetchone()['id']
        return self.get(new_id)

    def update(self, r: Rechnung, updated_by: str, *, nur_entwurf: bool = True) -> bool:
        """Aktualisiert die Rechnung optimistisch über version.

        nur_entwurf=False lässt die Geschäftsstelle die Fibu-Felder auch nach der
        Freigabe nachtragen – solange die Rechnung noch nicht exportiert ist.
        """
        status_bed = " AND status = 'entwurf'" if nur_entwurf else \
                     " AND exportiert_in_export_id IS NULL"
        with self.cursor() as cur:
            cur.execute(
                f"""
                UPDATE rechnung
                SET abteilung_id=%s, kategorie_id=%s, beschreibung=%s,
                    betrag_cent=%s, rechnungsdatum=%s, rechnungsnummer=%s,
                    empfaenger_typ=%s, empfaenger_mitglied_id=%s,
                    empfaenger_name=%s, empfaenger_iban=%s,
                    version=version+1, updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id=%s AND version=%s AND deleted_at IS NULL{status_bed}
                """,
                (r.abteilung_id, r.kategorie_id, r.beschreibung,
                 r.betrag_cent, r.rechnungsdatum, r.rechnungsnummer,
                 r.empfaenger_typ, r.empfaenger_mitglied_id, r.empfaenger_name,
                 r.empfaenger_iban, updated_by, r.id, r.version),
            )
            return cur.rowcount == 1

    # ------------------------------------------------------------ Statuswechsel
    def einreichen(self, id: int, *, eingereicht_von: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE rechnung
                SET status='eingereicht',
                    eingereicht_am=CURRENT_TIMESTAMP, eingereicht_von=%s,
                    abgelehnt_grund=NULL,
                    version=version+1, updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id=%s AND status='entwurf' AND deleted_at IS NULL
                """,
                (eingereicht_von, eingereicht_von, id),
            )
            return cur.rowcount == 1

    def freigeben(self, id: int, *, freigegeben_von: str) -> bool:
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE rechnung
                SET status='freigegeben',
                    freigegeben_am=CURRENT_TIMESTAMP, freigegeben_von=%s,
                    abgelehnt_grund=NULL,
                    version=version+1, updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id=%s AND status='eingereicht' AND deleted_at IS NULL
                """,
                (freigegeben_von, freigegeben_von, id),
            )
            return cur.rowcount == 1

    def ablehnen(self, id: int, *, grund: Optional[str], abgelehnt_von: str) -> bool:
        """Ablehnen – auch aus 'freigegeben', solange nicht exportiert.

        Eine versehentliche Freigabe soll sich in einem Schritt korrigieren
        lassen und nicht erst über den Umweg 'zurücksetzen'. Mit dem Export ist
        Schluss: ab da liegt der Beleg in der Fibu.

        Die Freigabe-Spuren werden dabei gelöscht – eine abgelehnte Rechnung mit
        Freigeber im Feld wäre irreführend. Wer sie gegeben hat, steht weiter in
        der History.
        """
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE rechnung
                SET status='abgelehnt', abgelehnt_grund=%s,
                    freigegeben_am=NULL, freigegeben_von=NULL,
                    version=version+1, updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id=%s AND status IN ('eingereicht','freigegeben')
                  AND exportiert_in_export_id IS NULL AND deleted_at IS NULL
                """,
                (grund, abgelehnt_von, id),
            )
            return cur.rowcount == 1

    def zuruecksetzen(self, id: int, *, updated_by: str) -> bool:
        """Freigabe/Ablehnung rückgängig – solange nicht exportiert.

        freigegeben → 'eingereicht' (der Freigeber korrigiert sich),
        abgelehnt   → 'entwurf'     (der Einreicher soll nacharbeiten können).
        """
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE rechnung
                SET status = CASE WHEN status='abgelehnt' THEN 'entwurf' ELSE 'eingereicht' END,
                    freigegeben_am=NULL, freigegeben_von=NULL, abgelehnt_grund=NULL,
                    eingereicht_am = CASE WHEN status='abgelehnt' THEN NULL ELSE eingereicht_am END,
                    eingereicht_von = CASE WHEN status='abgelehnt' THEN NULL ELSE eingereicht_von END,
                    version=version+1, updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id=%s AND status IN ('freigegeben','abgelehnt')
                  AND exportiert_in_export_id IS NULL AND deleted_at IS NULL
                """,
                (updated_by, id),
            )
            return cur.rowcount == 1

    def soft_delete(self, id: int, deleted_by: str, *, nur_entwurf: bool = True) -> bool:
        """Löschen (soft). Standard: nur Entwürfe – die Geschäftsstelle darf auch
        später löschen, solange die Rechnung nicht exportiert wurde."""
        bed = " AND status='entwurf'" if nur_entwurf else \
              " AND exportiert_in_export_id IS NULL"
        with self.cursor() as cur:
            cur.execute(
                f"""
                UPDATE rechnung
                SET deleted_at=CURRENT_TIMESTAMP, deleted_by=%s,
                    version=version+1, updated_at=CURRENT_TIMESTAMP, updated_by=%s
                WHERE id=%s AND deleted_at IS NULL{bed}
                """,
                (deleted_by, deleted_by, id),
            )
            return cur.rowcount == 1

    def get_history(self, id: int) -> list[dict]:
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM rechnung_history WHERE id = %s ORDER BY version DESC
                """,
                (id,),
            )
            return [dict(r) for r in cur.fetchall()]
