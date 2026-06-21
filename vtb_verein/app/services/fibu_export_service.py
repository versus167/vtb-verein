"""
FibuExportService – Delta-/Inkrement-Export der Sollstellungen (Format hmd FBASC).

Ablauf:
1. vorschau()       → Forderungen (Soll) + Gegenbuchungen (Haben) + Validierungsfehler
2. exportieren(...) → Lauf anlegen, fbasc.hia rendern, Quellzeilen als „exportiert" stempeln
3. re_download(id)  → einen früheren Lauf erneut rendern

Buchungslogik:
- Forderung = noch nicht exportierte, lebende Sollstellung → Debitor im Soll (S).
- Gegenbuchung = bereits exportierte, danach stornierte/gelöschte Sollstellung → Haben (H),
  damit bereits an die Fibu übergebene Beträge nicht still verschwinden.

Konten-Auflösung:
- Debitor-Konto (Feld 00) = einstellungen.debitor_konto_basis + mitgliedsnummer
- Gegenkonto (Feld 01)    = Regel/Gebühr.gegenkonto, sonst default_gegenkonto
- Kostenstelle (Feld 07)  = Gebühr-Override → Abteilung → Verein-Default (12)
- Kostenträger (Feld 08)  = Gebühr-Override → default_kostentraeger (1)
- Mandatsreferenz (Feld 47) = mitglied.sepa_mandatsref (Altsystem-Import), sonst
  automatisch = Mitgliedsnummer; Mandatsdatum (Feld 48) sonst = Eintrittsdatum.
"""
from datetime import date

from app.models.fibu import FibuExport, FibuExportPosition, FibuEinstellungen
from app.services import fibu_formatter


class FibuExportFehler(Exception):
    """Export abgebrochen, weil Positionen unvollständig konfiguriert sind."""

    def __init__(self, fehler: list[dict]):
        self.fehler = fehler
        super().__init__(f"{len(fehler)} Position(en) nicht exportierbar")


class FibuExportService:

    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------------------
    # Öffentliche API
    # ------------------------------------------------------------------

    def vorschau(self) -> dict:
        """Liefert die zu exportierenden Positionen + Validierungsfehler (ohne DB-Schreibzugriff)."""
        einst = self.db.fibu_einstellungen.get()
        forderungen = [self._position(r, 'forderung', einst)
                       for r in self.db.fibu_exporte.list_neue_positionen()]
        gegenbuchungen = [self._position(r, 'gegenbuchung', einst)
                          for r in self.db.fibu_exporte.list_gegenbuchungen()]
        fehler = self._validieren(forderungen + gegenbuchungen, einst)
        return {'forderungen': forderungen, 'gegenbuchungen': gegenbuchungen, 'fehler': fehler}

    def exportieren(self, erstellt_von: str) -> tuple[FibuExport, bytes]:
        """Führt den Export-Lauf aus: validiert, rendert fbasc.hia, stempelt die Quellzeilen."""
        v = self.vorschau()
        if v['fehler']:
            raise FibuExportFehler(v['fehler'])
        forderungen, gegenbuchungen = v['forderungen'], v['gegenbuchungen']
        if not forderungen and not gegenbuchungen:
            raise ValueError("Keine zu exportierenden Positionen vorhanden.")

        positionen = forderungen + gegenbuchungen
        content = fibu_formatter.render(positionen)

        neu_ids = {
            'beitrag': [p.quelle_id for p in forderungen if p.quelle_typ == 'beitrag'],
            'gebuehr': [p.quelle_id for p in forderungen if p.quelle_typ == 'gebuehr'],
        }
        storno_ids = {
            'beitrag': [p.quelle_id for p in gegenbuchungen if p.quelle_typ == 'beitrag'],
            'gebuehr': [p.quelle_id for p in gegenbuchungen if p.quelle_typ == 'gebuehr'],
        }
        summe_cent = (sum(round(p.betrag * 100) for p in forderungen)
                      - sum(round(p.betrag * 100) for p in gegenbuchungen))
        dateiname = f"fbasc_{date.today().isoformat()}.hia"

        export = self.db.fibu_exporte.create_export(
            exportiert_von=erstellt_von, dateiname=dateiname, format='fbasc',
            anzahl_positionen=len(positionen), summe_cent=summe_cent,
            neu_ids=neu_ids, storno_ids=storno_ids,
        )
        return export, content

    def re_download(self, export_id: int) -> bytes:
        """Rendert einen früheren Lauf erneut aus den gestempelten Quellzeilen."""
        einst = self.db.fibu_einstellungen.get()
        neu_rows, storno_rows = self.db.fibu_exporte.get_positionen_fuer_export(export_id)
        positionen = ([self._position(r, 'forderung', einst) for r in neu_rows]
                      + [self._position(r, 'gegenbuchung', einst) for r in storno_rows])
        return fibu_formatter.render(positionen)

    # ------------------------------------------------------------------
    # Interne Hilfsmethoden
    # ------------------------------------------------------------------

    def _position(self, row: dict, art: str, einst: FibuEinstellungen) -> FibuExportPosition:
        """Baut aus einer Buchungs-Rohzeile eine FBASC-Position (Forderung=S / Gegenbuchung=H)."""
        nummer = row.get('mitgliedsnummer')
        konto = (einst.debitor_konto_basis + nummer) if (einst.debitor_konto_basis is not None
                                                          and nummer is not None) else None
        gegenkonto = row.get('gegenkonto') or einst.default_gegenkonto
        steuerschluessel = row.get('steuerschluessel') or einst.default_steuerschluessel
        kostenstelle = self._kostenstelle(row, einst)
        kostentraeger = (row.get('quelle_kostentraeger')
                         if row.get('quelle_kostentraeger') is not None
                         else einst.default_kostentraeger)

        prefix = 'B' if row['quelle_typ'] == 'beitrag' else 'G'
        periode = row.get('periode')
        bezeichnung = row.get('quelle_name') or ''
        if periode:
            bezeichnung = f"{bezeichnung} {periode}".strip()
        vorname = row.get('vorname')
        nachname = row.get('nachname') or ''
        iban = row.get('iban')
        # Mandatsreferenz: gespeicherter Wert (z.B. aus dem Altsystem-Import) hat Vorrang;
        # sonst – insb. für neu angelegte Mitglieder – automatisch aus der Mitgliedsnummer
        # ableiten. Mandatsdatum fällt auf das Eintrittsdatum zurück.
        mandatsref = row.get('sepa_mandatsref') or (str(nummer) if nummer is not None else None)
        mandatsdatum = row.get('sepa_mandatsdatum') or row.get('eintrittsdatum')

        return FibuExportPosition(
            quelle_typ=row['quelle_typ'],
            quelle_id=row['quelle_id'],
            art=art,
            mitglied_id=row.get('mitglied_id') or 0,
            mitglied_name=f"{nachname}, {vorname}" if vorname else nachname,
            bezeichnung=bezeichnung,
            konto=konto,
            gegenkonto=gegenkonto,
            betrag=row.get('betrag_soll') or 0.0,
            soll_haben='S' if art == 'forderung' else 'H',
            belegnummer=f"{prefix}{row['quelle_id']}",
            steuerschluessel=steuerschluessel,
            kostenstelle=kostenstelle,
            kostentraeger=kostentraeger,
            belegdatum=row.get('datum'),
            faelligkeitsdatum=row.get('datum'),
            buchungstext=bezeichnung,
            lastschrifteinzug=1 if (iban and mandatsref) else None,
            suchname=str(nummer) if nummer is not None else '',
            nachname=nachname,
            vorname=vorname,
            strasse=row.get('strasse'),
            plz=row.get('plz'),
            ort=row.get('ort'),
            land=row.get('land'),
            iban=iban,
            bic=row.get('bic'),
            mandatsref=mandatsref,
            mandatsdatum=mandatsdatum,
        )

    @staticmethod
    def _kostenstelle(row: dict, einst: FibuEinstellungen):
        """Kostenstelle: Gebühr-Override → Abteilung → Verein-Default (nur ohne Abteilung)."""
        if row.get('quelle_kostenstelle') is not None:
            return row['quelle_kostenstelle']
        if row.get('abteilung_kostenstelle') is not None:
            return row['abteilung_kostenstelle']
        if row.get('abteilung_id') is None:
            return einst.verein_kostenstelle
        return None

    @staticmethod
    def _validieren(positionen: list[FibuExportPosition], einst: FibuEinstellungen) -> list[dict]:
        """Sammelt Positionen, die nicht exportierbar sind (fehlendes Konto/Gegenkonto)."""
        fehler: list[dict] = []
        for p in positionen:
            probleme = []
            if p.konto is None:
                if einst.debitor_konto_basis is None:
                    probleme.append("Debitor-Konto-Basis nicht gesetzt (Fibu-Einstellungen)")
                else:
                    probleme.append("Mitglied ohne Mitgliedsnummer")
            if not p.gegenkonto:
                probleme.append("kein Gegenkonto (Regel/Gebühr oder Default)")
            if probleme:
                fehler.append({
                    'quelle_typ': p.quelle_typ,
                    'quelle_id': p.quelle_id,
                    'mitglied_name': p.mitglied_name,
                    'bezeichnung': p.bezeichnung,
                    'art': p.art,
                    'problem': "; ".join(probleme),
                })
        return fehler
