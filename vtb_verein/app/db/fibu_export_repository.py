"""Repository für den Fibu-Delta-Export (Header + Positions-Ermittlung + Stamping).

Liefert die zu exportierenden Buchungs-Rohdaten (Forderungen = neue Posten,
Gegenbuchungen = Stornos/Löschungen bereits exportierter Posten) als dicts; die
Auflösung zu FBASC-Feldern macht der Service. Der Export-Lauf (Header anlegen +
Markieren der Quellzeilen) läuft atomar in einer Transaktion.
"""
from app.models.fibu import FibuExport
from app.db.base_repository import BaseRepository

# Gemeinsame Spaltenprojektion je Quelle. {cond} = WHERE-Fragment (fest, kein User-Input).
_SQL_BEITRAG = """
    SELECT 'beitrag' AS quelle_typ, s.id AS quelle_id,
           s.zeitraum AS periode, s.betrag_soll, s.created_at AS belegdatum,
           m.id AS mitglied_id, m.mitgliedsnummer, m.vorname, m.nachname,
           m.strasse, m.plz, m.ort, m.land, m.iban, m.bic, m.zahlungsart, m.kontoinhaber,
           m.sepa_mandatsref, m.sepa_mandatsdatum, m.eintrittsdatum,
           (SELECT k.wert FROM mitglied_kontakt k
            WHERE k.mitglied_id = m.id AND k.typ = 'email' AND k.ist_primaer
              AND k.deleted_at IS NULL LIMIT 1) AS email,
           r.name AS quelle_name, r.zahler_typ, r.gegenkonto, r.steuerschluessel,
           -- Getragene Beiträge (zahler_typ='abteilung'): hat die Regel keine eigene
           -- Abteilung (Vereinsbeitrag), wird die für die Gegenbuchung tragende Abteilung
           -- aus der Bedingung abgeleitet (bedingung_abteilung_ids). Genau eine Abteilung →
           -- eindeutig; mehrere verschiedene → mehrdeutig (der Service meldet das als Fehler).
           COALESCE(r.abteilung_id, bed.einzel_abteilung_id) AS abteilung_id,
           COALESCE(a.kostenstelle, abed.kostenstelle) AS abteilung_kostenstelle,
           COALESCE(bed.anzahl_abteilungen > 1, FALSE) AS abteilung_mehrdeutig,
           NULL::integer AS quelle_kostenstelle, NULL::integer AS quelle_kostentraeger
    FROM beitrag_sollstellung s
    JOIN mitglied m ON m.id = s.mitglied_id
    JOIN beitragsregel r ON r.id = s.beitragsregel_id
    LEFT JOIN abteilung a ON a.id = r.abteilung_id
    LEFT JOIN LATERAL (
        SELECT COUNT(DISTINCT x) AS anzahl_abteilungen,
               CASE WHEN COUNT(DISTINCT x) = 1 THEN MIN(x) END AS einzel_abteilung_id
        FROM unnest(r.bedingung_abteilung_ids) AS x WHERE x IS NOT NULL
    ) bed ON (r.zahler_typ = 'abteilung' AND r.abteilung_id IS NULL)
    LEFT JOIN abteilung abed ON abed.id = bed.einzel_abteilung_id
    WHERE {cond}
    ORDER BY m.nachname, m.vorname, s.id
"""

_SQL_GEBUEHR = """
    SELECT 'gebuehr' AS quelle_typ, f.id AS quelle_id,
           NULL AS periode, f.betrag_soll, f.datum AS belegdatum,
           m.id AS mitglied_id, m.mitgliedsnummer, m.vorname, m.nachname,
           m.strasse, m.plz, m.ort, m.land, m.iban, m.bic, m.zahlungsart, m.kontoinhaber,
           m.sepa_mandatsref, m.sepa_mandatsdatum, m.eintrittsdatum,
           (SELECT k.wert FROM mitglied_kontakt k
            WHERE k.mitglied_id = m.id AND k.typ = 'email' AND k.ist_primaer
              AND k.deleted_at IS NULL LIMIT 1) AS email,
           g.name AS quelle_name, g.zahler_typ, g.gegenkonto, g.steuerschluessel,
           g.abteilung_id, a.kostenstelle AS abteilung_kostenstelle,
           -- Gebühren haben keine Funktions-/Abteilungs-Bedingung → nie mehrdeutig.
           FALSE AS abteilung_mehrdeutig,
           g.kostenstelle AS quelle_kostenstelle, g.kostentraeger AS quelle_kostentraeger
    FROM gebuehr_forderung f
    JOIN mitglied m ON m.id = f.mitglied_id
    JOIN gebuehr g ON g.id = f.gebuehr_id
    LEFT JOIN abteilung a ON a.id = g.abteilung_id
    WHERE {cond}
    ORDER BY m.nachname, m.vorname, f.id
"""

# WHERE-Fragmente; {p} = Spaltenpräfix (s = Beitrag, f = Gebühr).
_COND_NEU = ("{p}.exportiert_in_export_id IS NULL AND {p}.deleted_at IS NULL "
             "AND {p}.status <> 'storniert'")
_COND_STORNO = ("{p}.exportiert_in_export_id IS NOT NULL "
                "AND {p}.storno_exportiert_in_export_id IS NULL "
                "AND ({p}.status = 'storniert' OR {p}.deleted_at IS NOT NULL)")

_EXPORT_COLS = """id, exportiert_am, exportiert_von, dateiname, format,
                  anzahl_positionen, summe_cent, storno_von_export_id,
                  version, created_at, created_by, deleted_at, deleted_by"""


def _map_export(row) -> FibuExport:
    return FibuExport(**dict(row))


class FibuExportRepository(BaseRepository):

    # ---- Positions-Ermittlung (Delta) -------------------------------------

    def list_neue_positionen(self) -> list[dict]:
        """Noch nicht exportierte, lebende Forderungen (Beitrag + Gebühr) → Soll-Buchungen."""
        with self.cursor() as cur:
            cur.execute(_SQL_BEITRAG.format(cond=_COND_NEU.format(p='s')))
            rows = [dict(r) for r in cur.fetchall()]
            cur.execute(_SQL_GEBUEHR.format(cond=_COND_NEU.format(p='f')))
            rows += [dict(r) for r in cur.fetchall()]
        return rows

    def list_gegenbuchungen(self) -> list[dict]:
        """Bereits exportierte, inzwischen stornierte/gelöschte Posten → Haben-Gegenbuchungen."""
        with self.cursor() as cur:
            cur.execute(_SQL_BEITRAG.format(cond=_COND_STORNO.format(p='s')))
            rows = [dict(r) for r in cur.fetchall()]
            cur.execute(_SQL_GEBUEHR.format(cond=_COND_STORNO.format(p='f')))
            rows += [dict(r) for r in cur.fetchall()]
        return rows

    def get_positionen_fuer_export(self, export_id: int) -> tuple[list[dict], list[dict]]:
        """Re-Download: Forderungen (Soll) und Gegenbuchungen (Haben) eines Laufs."""
        with self.cursor() as cur:
            cur.execute(_SQL_BEITRAG.format(cond="s.exportiert_in_export_id = %s"), (export_id,))
            neu = [dict(r) for r in cur.fetchall()]
            cur.execute(_SQL_GEBUEHR.format(cond="f.exportiert_in_export_id = %s"), (export_id,))
            neu += [dict(r) for r in cur.fetchall()]
            cur.execute(_SQL_BEITRAG.format(cond="s.storno_exportiert_in_export_id = %s"), (export_id,))
            storno = [dict(r) for r in cur.fetchall()]
            cur.execute(_SQL_GEBUEHR.format(cond="f.storno_exportiert_in_export_id = %s"), (export_id,))
            storno += [dict(r) for r in cur.fetchall()]
        return neu, storno

    # ---- Export-Lauf (atomar) ---------------------------------------------

    def create_export(self, *, exportiert_von: str, dateiname: str, format: str,
                       anzahl_positionen: int, summe_cent: int,
                       neu_ids: dict, storno_ids: dict) -> FibuExport:
        """Legt den Lauf-Header an und markiert die Quellzeilen – alles in einer Transaktion.

        neu_ids/storno_ids: {'beitrag': [...], 'gebuehr': [...]} der zu stempelnden IDs.
        """
        tables = {'beitrag': 'beitrag_sollstellung', 'gebuehr': 'gebuehr_forderung'}
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO fibu_exporte (exportiert_von, dateiname, format,
                                          anzahl_positionen, summe_cent, created_by)
                VALUES (%s,%s,%s,%s,%s,%s)
                RETURNING id
                """,
                (exportiert_von, dateiname, format, anzahl_positionen, summe_cent, exportiert_von),
            )
            export_id = cur.fetchone()['id']
            for quelle, ids in neu_ids.items():
                if ids:
                    cur.execute(
                        f"""
                        UPDATE {tables[quelle]}
                        SET exportiert_in_export_id=%s, version=version+1,
                            updated_at=CURRENT_TIMESTAMP, updated_by=%s
                        WHERE id = ANY(%s) AND exportiert_in_export_id IS NULL
                        """,
                        (export_id, exportiert_von, list(ids)),
                    )
            for quelle, ids in storno_ids.items():
                if ids:
                    cur.execute(
                        f"""
                        UPDATE {tables[quelle]}
                        SET storno_exportiert_in_export_id=%s, version=version+1,
                            updated_at=CURRENT_TIMESTAMP, updated_by=%s
                        WHERE id = ANY(%s) AND storno_exportiert_in_export_id IS NULL
                        """,
                        (export_id, exportiert_von, list(ids)),
                    )
            cur.execute(f"SELECT {_EXPORT_COLS} FROM fibu_exporte WHERE id = %s", (export_id,))
            return _map_export(cur.fetchone())

    def get_export(self, export_id: int) -> FibuExport:
        with self.cursor() as cur:
            cur.execute(f"SELECT {_EXPORT_COLS} FROM fibu_exporte WHERE id = %s AND deleted_at IS NULL",
                        (export_id,))
            row = cur.fetchone()
            if row is None:
                raise KeyError(f"FibuExport {export_id} nicht gefunden")
            return _map_export(row)

    def list_exporte(self) -> list[FibuExport]:
        with self.cursor() as cur:
            cur.execute(f"SELECT {_EXPORT_COLS} FROM fibu_exporte WHERE deleted_at IS NULL "
                        f"ORDER BY id DESC")
            return [_map_export(r) for r in cur.fetchall()]

    # ---- Storno eines ganzen Laufs ----------------------------------------

    def is_latest(self, export_id: int) -> bool:
        """True, wenn export_id der jüngste nicht gelöschte Lauf ist (Un-Export-Bedingung)."""
        with self.cursor() as cur:
            cur.execute("SELECT MAX(id) AS max_id FROM fibu_exporte WHERE deleted_at IS NULL")
            row = cur.fetchone()
            return row is not None and row['max_id'] == export_id

    def find_storno_lauf(self, original_id: int) -> FibuExport | None:
        """Liefert den (lebenden) Gegenbuchungs-Lauf zu einem Original – oder None."""
        with self.cursor() as cur:
            cur.execute(f"SELECT {_EXPORT_COLS} FROM fibu_exporte "
                        f"WHERE storno_von_export_id = %s AND deleted_at IS NULL "
                        f"ORDER BY id DESC LIMIT 1", (original_id,))
            row = cur.fetchone()
            return _map_export(row) if row else None

    def un_export(self, export_id: int, *, benutzer: str) -> int:
        """Nimmt den jüngsten, noch nicht in die Fibu eingelesenen Lauf zurück:
        löst die Export-Stempel der Quellzeilen wieder und soft-deletet den Header.
        Liefert die Anzahl wieder freigegebener Quellzeilen."""
        with self.cursor() as cur:
            geloest = 0
            for tbl in ('beitrag_sollstellung', 'gebuehr_forderung'):
                cur.execute(
                    f"""UPDATE {tbl}
                        SET exportiert_in_export_id = NULL, version = version+1,
                            updated_at = CURRENT_TIMESTAMP, updated_by = %s
                        WHERE exportiert_in_export_id = %s""",
                    (benutzer, export_id))
                geloest += cur.rowcount
                cur.execute(
                    f"""UPDATE {tbl}
                        SET storno_exportiert_in_export_id = NULL, version = version+1,
                            updated_at = CURRENT_TIMESTAMP, updated_by = %s
                        WHERE storno_exportiert_in_export_id = %s""",
                    (benutzer, export_id))
                geloest += cur.rowcount
            cur.execute(
                """UPDATE fibu_exporte
                   SET deleted_at = CURRENT_TIMESTAMP, deleted_by = %s, version = version+1
                   WHERE id = %s AND deleted_at IS NULL""",
                (benutzer, export_id))
            return geloest

    def create_storno_lauf(self, *, original_id: int, exportiert_von: str, dateiname: str,
                           anzahl_positionen: int, summe_cent: int) -> FibuExport:
        """Legt einen Gegenbuchungs-Lauf an, der `original_id` komplett gegenbucht (S↔H).
        Die Quellzeilen bleiben unangetastet, damit Original und Storno rekonstruierbar bleiben."""
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO fibu_exporte (exportiert_von, dateiname, format,
                                          anzahl_positionen, summe_cent,
                                          storno_von_export_id, created_by)
                VALUES (%s,%s,'fbasc',%s,%s,%s,%s)
                RETURNING id
                """,
                (exportiert_von, dateiname, anzahl_positionen, summe_cent,
                 original_id, exportiert_von),
            )
            new_id = cur.fetchone()['id']
            cur.execute(f"SELECT {_EXPORT_COLS} FROM fibu_exporte WHERE id = %s", (new_id,))
            return _map_export(cur.fetchone())
