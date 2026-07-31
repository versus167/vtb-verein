"""Repository für den SEPA-Lastschrifteinzug (Läufe + Positionen + Kandidaten-Ermittlung).

Liefert die einziehbaren offenen Posten als Rohdaten (Beitrag + Gebühr); die Auswahl der
tatsächlich einziehbaren und die Ausschlussgründe entscheidet der SepaService. Das Anlegen
eines Laufs (Header + Positions-Snapshot) läuft atomar in einer Transaktion.

Nicht einziehbar und daher hier schon ausgefiltert:
- bereits bezahlte/stornierte oder soft-gelöschte Posten (nur ``status='offen'``),
- Posten, die schon in einem lebenden Lauf stecken (kein Doppel-Einzug),
- abteilungs-getragene Posten (``zahler_typ='abteilung'``) – dort fließt kein Geld vom
  Mitglied, sie sind im FBASC-Export eine reine Kostenstellen-Umbuchung.
Alles Weitere (fehlende IBAN, fehlendes Mandat, Betrag 0) bleibt sichtbar und wird vom
Service mit Grund als „nicht einziehbar" ausgewiesen.
"""
from app.db.base_repository import BaseRepository
from app.models.sepa import SepaLauf, SepaPosition

# Gemeinsame Projektion je Quelle. {cond} = zusätzliches WHERE-Fragment (fest, kein User-Input).
_MITGLIED_COLS = """
           m.id AS mitglied_id, m.mitgliedsnummer, m.vorname, m.nachname,
           m.iban, m.bic, m.kontoinhaber, m.zahlungsart,
           m.sepa_mandatsref, m.sepa_mandatsdatum, m.eintrittsdatum
"""

# Ein Posten gilt als „noch nicht eingezogen", wenn keine LEBENDE Position auf ihn zeigt.
# Zurückgenommene Läufe (Lauf + Positionen soft-deleted) geben ihn damit wieder frei.
_NICHT_EINGEZOGEN = """
    NOT EXISTS (
        SELECT 1 FROM sepa_lauf_position p
        WHERE p.quelle_typ = %(typ)s AND p.quelle_id = {id_col}
          AND p.deleted_at IS NULL
    )
"""

_SQL_BEITRAG = f"""
    SELECT 'beitrag' AS quelle_typ, s.id AS quelle_id,
           s.betrag_soll, s.zeitraum AS periode, s.faelligkeitsdatum,
           r.name AS quelle_name,
           {_MITGLIED_COLS}
    FROM beitrag_sollstellung s
    JOIN mitglied m ON m.id = s.mitglied_id
    JOIN beitragsregel r ON r.id = s.beitragsregel_id
    WHERE s.deleted_at IS NULL AND s.status = 'offen'
      AND m.deleted_at IS NULL
      AND COALESCE(r.zahler_typ, 'mitglied') <> 'abteilung'
      AND (s.faelligkeitsdatum IS NULL OR s.faelligkeitsdatum <= %(bis)s)
      AND {_NICHT_EINGEZOGEN.format(id_col='s.id')}
    ORDER BY m.nachname, m.vorname, s.id
"""

_SQL_GEBUEHR = f"""
    SELECT 'gebuehr' AS quelle_typ, f.id AS quelle_id,
           f.betrag_soll, NULL AS periode, f.datum AS faelligkeitsdatum,
           g.name AS quelle_name,
           {_MITGLIED_COLS}
    FROM gebuehr_forderung f
    JOIN mitglied m ON m.id = f.mitglied_id
    JOIN gebuehr g ON g.id = f.gebuehr_id
    WHERE f.deleted_at IS NULL AND f.status = 'offen'
      AND m.deleted_at IS NULL
      AND COALESCE(g.zahler_typ, 'mitglied') <> 'abteilung'
      AND f.datum <= %(bis)s
      AND {_NICHT_EINGEZOGEN.format(id_col='f.id')}
    ORDER BY m.nachname, m.vorname, f.id
"""

_LAUF_COLS = """id, dateiname, message_id, ausfuehrungsdatum, sequenztyp,
                glaeubiger_id, glaeubiger_name, glaeubiger_iban, glaeubiger_bic,
                anzahl_positionen, summe_cent, version,
                created_at, created_by, updated_at, updated_by, deleted_at, deleted_by"""

_POSITION_COLS = """id, sepa_lauf_id, quelle_typ, quelle_id, mitglied_id, betrag_cent,
                    end_to_end_id, mandatsref, mandatsdatum, iban, bic, kontoinhaber,
                    verwendungszweck, version, created_at, created_by,
                    updated_at, updated_by, deleted_at, deleted_by"""


class SepaRepository(BaseRepository):

    # ---- Kandidaten -------------------------------------------------------

    def list_kandidaten(self, bis_datum: str) -> list[dict]:
        """Offene, noch nicht eingezogene Posten mit Fälligkeit bis ``bis_datum`` (ISO)."""
        with self.cursor() as cur:
            cur.execute(_SQL_BEITRAG, {'bis': bis_datum, 'typ': 'beitrag'})
            rows = [dict(r) for r in cur.fetchall()]
            cur.execute(_SQL_GEBUEHR, {'bis': bis_datum, 'typ': 'gebuehr'})
            rows += [dict(r) for r in cur.fetchall()]
        return rows

    # ---- Läufe ------------------------------------------------------------

    def create_lauf(self, lauf: SepaLauf, positionen: list[SepaPosition],
                    erstellt_von: str) -> SepaLauf:
        """Legt Header + Positionen in EINER Transaktion an.

        Der partielle Unique-Index auf (quelle_typ, quelle_id) verhindert dabei, dass ein
        Posten in zwei lebenden Läufen landet – bei parallelen Läufen bricht der INSERT ab
        und die ganze Transaktion rollt zurück (kein halb erzeugter Lauf).
        """
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sepa_lauf (dateiname, message_id, ausfuehrungsdatum, sequenztyp,
                                       glaeubiger_id, glaeubiger_name, glaeubiger_iban,
                                       glaeubiger_bic, anzahl_positionen, summe_cent,
                                       created_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id
                """,
                (lauf.dateiname, lauf.message_id, lauf.ausfuehrungsdatum, lauf.sequenztyp,
                 lauf.glaeubiger_id, lauf.glaeubiger_name, lauf.glaeubiger_iban,
                 lauf.glaeubiger_bic, len(positionen),
                 sum(p.betrag_cent for p in positionen), erstellt_von),
            )
            lauf_id = cur.fetchone()['id']
            for p in positionen:
                cur.execute(
                    """
                    INSERT INTO sepa_lauf_position (
                        sepa_lauf_id, quelle_typ, quelle_id, mitglied_id, betrag_cent,
                        end_to_end_id, mandatsref, mandatsdatum, iban, bic, kontoinhaber,
                        verwendungszweck, created_by)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (lauf_id, p.quelle_typ, p.quelle_id, p.mitglied_id, p.betrag_cent,
                     p.end_to_end_id, p.mandatsref, p.mandatsdatum, p.iban, p.bic,
                     p.kontoinhaber, p.verwendungszweck, erstellt_von),
                )
        return self.get_lauf(lauf_id)

    def get_lauf(self, lauf_id: int) -> SepaLauf:
        """Lauf inkl. Positionen. KeyError, wenn es ihn nicht (mehr) gibt."""
        with self.cursor() as cur:
            cur.execute(f"SELECT {_LAUF_COLS} FROM sepa_lauf WHERE id = %s", (lauf_id,))
            row = cur.fetchone()
            if row is None:
                raise KeyError(f"SEPA-Lauf {lauf_id} nicht gefunden")
            lauf = SepaLauf(**dict(row))
            cur.execute(
                f"SELECT {_POSITION_COLS} FROM sepa_lauf_position "
                f"WHERE sepa_lauf_id = %s AND deleted_at IS NULL ORDER BY id",
                (lauf_id,),
            )
            lauf.positionen = [SepaPosition(**dict(r)) for r in cur.fetchall()]
        return lauf

    def list_laeufe(self) -> list[SepaLauf]:
        """Lauf-Historie (ohne Positionen), jüngster zuerst; zurückgenommene ausgeblendet."""
        with self.cursor() as cur:
            cur.execute(f"SELECT {_LAUF_COLS} FROM sepa_lauf "
                        f"WHERE deleted_at IS NULL ORDER BY id DESC")
            return [SepaLauf(**dict(r)) for r in cur.fetchall()]

    def zuruecknehmen(self, lauf_id: int, benutzer: str) -> int:
        """Lauf + Positionen soft-löschen → die Posten sind wieder einziehbar.

        Gibt die Anzahl der wieder freigegebenen Positionen zurück.
        """
        with self.cursor() as cur:
            cur.execute(
                """
                UPDATE sepa_lauf_position
                SET deleted_at = CURRENT_TIMESTAMP, deleted_by = %s, version = version + 1,
                    updated_at = CURRENT_TIMESTAMP, updated_by = %s
                WHERE sepa_lauf_id = %s AND deleted_at IS NULL
                """,
                (benutzer, benutzer, lauf_id),
            )
            anzahl = cur.rowcount
            cur.execute(
                """
                UPDATE sepa_lauf
                SET deleted_at = CURRENT_TIMESTAMP, deleted_by = %s, version = version + 1,
                    updated_at = CURRENT_TIMESTAMP, updated_by = %s
                WHERE id = %s AND deleted_at IS NULL
                """,
                (benutzer, benutzer, lauf_id),
            )
        return anzahl
