"""
FibuExportService – Delta-/Inkrement-Export der Sollstellungen (Format hmd FBASC).

Ablauf:
1. vorschau()       → Forderungen (Soll) + Gegenbuchungen (Haben) + Validierungsfehler
2. exportieren(...) → Lauf anlegen, fbasc.hia rendern, Quellzeilen als „exportiert" stempeln
3. re_download(id)  → einen früheren Lauf erneut rendern

Lauf-Storno (zwei Wege, weil die App nicht weiß, ob die Datei schon in die Fibu
eingelesen wurde):
- zuruecknehmen(id) → Un-Export des JÜNGSTEN, noch nicht eingelesenen Laufs: Stempel der
  Quellzeilen lösen, Header soft-deleten → Positionen erscheinen wieder in der Vorschau.
- stornieren(id)    → Gegenbuchungs-Lauf für einen bereits eingelesenen Lauf: neuer Lauf,
  der das Original komplett gegenbucht (S↔H). Original + Storno bleiben rekonstruierbar.

Buchungslogik:
- Forderung = noch nicht exportierte, lebende Sollstellung → Debitor im Soll (S).
- Gegenbuchung = bereits exportierte, danach stornierte/gelöschte Sollstellung → Haben (H),
  damit bereits an die Fibu übergebene Beträge nicht still verschwinden.
- Abteilungs-getragene Posten (zahler_typ='abteilung', z.B. Schiedsrichter-Beiträge):
  erzeugen ZWEI Zeilen mit demselben Erlöskonto, getauschter Kostenstelle und gleicher
  Belegnummer (sich ausgleichendes OPOS-Paar auf dem Debitor → kein SEPA-Einzug):
    1. Einbuchung  – Debitor S gegen Erlöskonto, Kostenstelle = Verein  → Verein bekommt Beitrag.
    2. Gegenbuchung – Debitor H gegen Erlöskonto, Kostenstelle = Abteilung → Abteilung zahlt Beitrag.
  Netto fließt kein Geld; der Beitrag wird per Kostenstelle vom Verein auf die Abteilung
  umgebucht. Im Storno-Pfad dreht der S↔H-Tausch beide Zeilen des Paars um.
  Die tragende Abteilung stammt von der Regel/Gebühr selbst; bei Vereinsbeiträgen ohne
  eigene Abteilung (z.B. „Schiedsrichter-Beitrag", der per Bedingung Funktion+Abteilung
  greift) wird sie aus der Bedingung der Regel abgeleitet (bedingung_abteilung_ids, vom
  Repository nach abteilung_id/abteilung_kostenstelle aufgelöst). Nennt die Bedingung
  mehrere verschiedene Abteilungen, ist die Zuordnung nicht eindeutig → Validierungsfehler.

Konten-Auflösung:
- Debitor-Konto (Feld 00) = einstellungen.debitor_konto_basis + mitgliedsnummer
- Gegenkonto (Feld 01)    = Regel/Gebühr.gegenkonto, sonst default_gegenkonto
- Kostenstelle (Feld 07)  = Gebühr-Override → Abteilung → Verein-Default (12)
- Kostenträger (Feld 08)  = Gebühr-Override → default_kostentraeger (1)
- Lastschrift-Kennzeichen (Feld 36) + Mandatsdaten nur bei zahlungsart='lastschrift'.
  Mandatsreferenz (Feld 47) = mitglied.sepa_mandatsref (Altsystem-Import), sonst
  automatisch = Mitgliedsnummer; Mandatsdatum (Feld 48) sonst = Eintrittsdatum.
- Belegdatum (Feld 10) = Abrechnungsdatum (Beitrag: created_at der Sollstellung,
  Gebühr: forderung.datum); Fälligkeit (Feld 11) = Belegdatum + NETTOTAGE (10).
"""
import dataclasses
from datetime import date, timedelta

from app.models.fibu import FibuExport, FibuExportPosition, FibuEinstellungen
from app.services import fibu_formatter

# Zahlungsziel: Fälligkeit = Belegdatum + NETTOTAGE.
NETTOTAGE = 10


def _date_only(value):
    """Datumsanteil (YYYY-MM-DD) eines Werts; leer → None.

    Akzeptiert ISO-Strings ebenso wie date/datetime-Objekte: Postgres liefert für
    DATE/TIMESTAMP(TZ)-Spalten (z. B. created_at seit v51) date/datetime statt String.
    """
    if not value:
        return None
    if isinstance(value, date):  # datetime ist Subklasse von date
        return value.isoformat()[:10]
    return str(value)[:10]


def _plus_tage(iso, tage):
    """ISO-Datum + n Tage als ISO; leer/ungültig → None."""
    if not iso:
        return None
    try:
        return (date.fromisoformat(iso[:10]) + timedelta(days=tage)).isoformat()
    except (ValueError, TypeError):
        return None


def _summe_cent(positionen) -> int:
    """Vorzeichenbehaftete Summe in Cent: Soll positiv, Haben negativ."""
    return sum((1 if p.soll_haben == 'S' else -1) * round(p.betrag * 100) for p in positionen)


def _dedup_fehler(fehler: list[dict]) -> list[dict]:
    """Entfernt Duplikate (gleiche Quelle erzeugt über die zwei Abteilungs-Positionen
    sonst denselben Konto-/Gegenkonto-Fehler doppelt). Reihenfolge bleibt erhalten."""
    gesehen, eindeutig = set(), []
    for f in fehler:
        key = (f['quelle_typ'], f['quelle_id'], f['art'], f['problem'])
        if key not in gesehen:
            gesehen.add(key)
            eindeutig.append(f)
    return eindeutig


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
        neu_rows = self.db.fibu_exporte.list_neue_positionen()
        gegen_rows = self.db.fibu_exporte.list_gegenbuchungen()
        forderungen = [p for r in neu_rows
                       for p in self._positionen_fuer_row(r, 'forderung', einst)]
        gegenbuchungen = [p for r in gegen_rows
                          for p in self._positionen_fuer_row(r, 'gegenbuchung', einst)]
        fehler = self._validieren(forderungen + gegenbuchungen, einst)
        fehler += self._abteilung_fehler(neu_rows + gegen_rows)
        return {'forderungen': forderungen, 'gegenbuchungen': gegenbuchungen,
                'fehler': _dedup_fehler(fehler)}

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

        # Abteilungs-Posten liefern zwei Positionen mit gleicher quelle_id → deduplizieren,
        # die Quellzeile wird genau einmal als exportiert gestempelt.
        def _ids(positionen, quelle):
            return sorted({p.quelle_id for p in positionen if p.quelle_typ == quelle})

        neu_ids = {'beitrag': _ids(forderungen, 'beitrag'), 'gebuehr': _ids(forderungen, 'gebuehr')}
        storno_ids = {'beitrag': _ids(gegenbuchungen, 'beitrag'),
                      'gebuehr': _ids(gegenbuchungen, 'gebuehr')}
        dateiname = f"fbasc_{date.today().isoformat()}.hia"

        export = self.db.fibu_exporte.create_export(
            exportiert_von=erstellt_von, dateiname=dateiname, format='fbasc',
            anzahl_positionen=len(positionen), summe_cent=_summe_cent(positionen),
            neu_ids=neu_ids, storno_ids=storno_ids,
        )
        return export, content

    def zuruecknehmen(self, export_id: int, benutzer: str) -> dict:
        """Un-Export: den jüngsten, noch NICHT in die Fibu eingelesenen Lauf zurücknehmen.

        Die Quellzeilen werden wieder „offen" (erscheinen in der nächsten Vorschau),
        der Lauf-Header wird soft-deleted. Nur für den jüngsten Lauf erlaubt – ältere
        haben Folge-Abhängigkeiten."""
        self.db.fibu_exporte.get_export(export_id)  # KeyError → 404
        if not self.db.fibu_exporte.is_latest(export_id):
            raise ValueError("Nur der jüngste Lauf kann zurückgenommen werden "
                             "(ältere bitte über einen Storno-/Gegenbuchungs-Lauf korrigieren).")
        anzahl = self.db.fibu_exporte.un_export(export_id, benutzer=benutzer)
        return {'zurueckgenommen': export_id, 'positionen_wieder_offen': anzahl}

    def stornieren(self, export_id: int, benutzer: str) -> tuple[FibuExport, bytes]:
        """Gegenbuchungs-Lauf: bucht einen bereits in die Fibu eingelesenen Lauf komplett
        gegen (jede Soll-Buchung als Haben und umgekehrt). Original und Storno-Lauf bleiben
        in der Historie und rekonstruierbar; die Quellzeilen bleiben unverändert."""
        original = self.db.fibu_exporte.get_export(export_id)  # KeyError → 404
        if original.storno_von_export_id is not None:
            raise ValueError("Ein Gegenbuchungs-Lauf kann nicht selbst storniert werden.")
        if self.db.fibu_exporte.find_storno_lauf(export_id) is not None:
            raise ValueError("Dieser Lauf wurde bereits storniert.")

        positionen = self._storno_positionen(export_id)
        if not positionen:
            raise ValueError("Der Lauf enthält keine Positionen zum Gegenbuchen.")
        content = fibu_formatter.render(positionen)
        dateiname = f"fbasc_storno_{date.today().isoformat()}.hia"
        export = self.db.fibu_exporte.create_storno_lauf(
            original_id=export_id, exportiert_von=benutzer, dateiname=dateiname,
            anzahl_positionen=len(positionen), summe_cent=_summe_cent(positionen),
        )
        return export, content

    def re_download(self, export_id: int) -> bytes:
        """Rendert einen früheren Lauf erneut. Ein Gegenbuchungs-Lauf wird aus dem Original
        (S↔H getauscht) rekonstruiert, ein normaler Lauf aus seinen gestempelten Quellzeilen."""
        export = self.db.fibu_exporte.get_export(export_id)
        if export.storno_von_export_id is not None:
            positionen = self._storno_positionen(export.storno_von_export_id)
        else:
            einst = self.db.fibu_einstellungen.get()
            neu_rows, storno_rows = self.db.fibu_exporte.get_positionen_fuer_export(export_id)
            positionen = ([p for r in neu_rows
                           for p in self._positionen_fuer_row(r, 'forderung', einst)]
                          + [p for r in storno_rows
                             for p in self._positionen_fuer_row(r, 'gegenbuchung', einst)])
        return fibu_formatter.render(positionen)

    def _storno_positionen(self, original_id: int) -> list[FibuExportPosition]:
        """Positionen, die ein Original gegenbuchen: dessen Forderungen (S) werden zu
        Gegenbuchungen (H) und dessen Gegenbuchungen (H) zu Forderungen (S)."""
        einst = self.db.fibu_einstellungen.get()
        neu_rows, storno_rows = self.db.fibu_exporte.get_positionen_fuer_export(original_id)
        return ([p for r in neu_rows
                 for p in self._positionen_fuer_row(r, 'gegenbuchung', einst)]
                + [p for r in storno_rows
                   for p in self._positionen_fuer_row(r, 'forderung', einst)])

    # ------------------------------------------------------------------
    # Interne Hilfsmethoden
    # ------------------------------------------------------------------

    def _positionen_fuer_row(self, row: dict, art: str,
                             einst: FibuEinstellungen) -> list[FibuExportPosition]:
        """Expandiert eine Buchungs-Rohzeile zu FBASC-Positionen.

        Normalfall (zahler_typ='mitglied'): genau eine Position.
        Abteilungs-getragen (zahler_typ='abteilung'): zwei Positionen mit demselben
        Erlöskonto und gleicher Belegnummer (sich ausgleichendes Debitor-OPOS-Paar):
        Einbuchung (Kostenstelle Verein) und Gegenbuchung (S↔H, Kostenstelle Abteilung).
        Im Storno-Pfad (art='gegenbuchung') sind beide Zeilen bereits invertiert."""
        basis = self._position(row, art, einst)
        if row.get('zahler_typ') != 'abteilung':
            return [basis]
        # Beträge fließen nicht real (reine Kostenstellen-Umbuchung) → kein Lastschrifteinzug.
        einbuchung = dataclasses.replace(
            basis, kostenstelle=einst.verein_kostenstelle, lastschrifteinzug=None)
        gegenbuchung = dataclasses.replace(
            basis, soll_haben=('H' if basis.soll_haben == 'S' else 'S'),
            kostenstelle=row.get('abteilung_kostenstelle'), lastschrifteinzug=None)
        return [einbuchung, gegenbuchung]

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
        # SEPA-/Lastschrift-Daten nur für Mitglieder mit zahlungsart='lastschrift' –
        # ein Überweiser bekommt weder das Lastschrift-Kennzeichen (Feld 36) noch eine
        # (ggf. aus der Mitgliedsnummer abgeleitete) Mandatsreferenz.
        ist_lastschrift = row.get('zahlungsart') == 'lastschrift'
        # Mandatsreferenz: gespeicherter Wert (z.B. aus dem Altsystem-Import) hat Vorrang;
        # sonst – insb. für neu angelegte Lastschrift-Mitglieder – automatisch aus der
        # Mitgliedsnummer ableiten. Mandatsdatum fällt auf das Eintrittsdatum zurück.
        if ist_lastschrift:
            mandatsref = row.get('sepa_mandatsref') or (str(nummer) if nummer is not None else None)
            mandatsdatum = _date_only(row.get('sepa_mandatsdatum') or row.get('eintrittsdatum'))
        else:
            mandatsref = row.get('sepa_mandatsref')
            mandatsdatum = _date_only(row.get('sepa_mandatsdatum'))

        # Belegdatum = Abrechnungsdatum (Beitrag: created_at, Gebühr: forderung.datum),
        # Fälligkeit = Belegdatum + NETTOTAGE.
        belegdatum = _date_only(row.get('belegdatum'))
        faelligkeitsdatum = _plus_tage(belegdatum, NETTOTAGE)

        # Abweichender Kontoinhaber (Feld 70) nur, wenn er tatsächlich vom Mitgliedsnamen
        # abweicht – sonst meldet die Fibu einen Abweichler, den es nicht gibt.
        voller_name = f"{vorname or ''} {nachname}".strip()
        kontoinhaber = (row.get('kontoinhaber') or '').strip()
        abw_kontoinhaber = (kontoinhaber if kontoinhaber
                            and kontoinhaber.casefold() != voller_name.casefold() else None)

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
            belegdatum=belegdatum,
            faelligkeitsdatum=faelligkeitsdatum,
            buchungstext=bezeichnung,
            lastschrifteinzug=1 if (ist_lastschrift and iban and mandatsref) else None,
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
            mailadresse=row.get('email'),
            kontoinhaber=abw_kontoinhaber,
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

    @staticmethod
    def _abteilung_fehler(rows: list[dict]) -> list[dict]:
        """Prüft Abteilungs-getragene Posten (zahler_typ='abteilung'): sie brauchen GENAU EINE
        tragende Abteilung mit Kostenstelle, sonst lässt sich die Gegenbuchung nicht zuordnen.
        Die Abteilung stammt von der Regel/Gebühr selbst oder – bei Vereinsbeiträgen ohne eigene
        Abteilung – aus der Bedingung der Regel (vom Repository nach abteilung_id aufgelöst)."""
        fehler: list[dict] = []
        for r in rows:
            if r.get('zahler_typ') != 'abteilung':
                continue
            if r.get('abteilung_mehrdeutig'):
                problem = ("Zahler 'Abteilung', aber die Bedingung der Regel nennt mehrere "
                           "Abteilungen – nicht eindeutig zuordenbar (je Abteilung eine eigene Regel)")
            elif r.get('abteilung_id') is None:
                problem = ("Zahler 'Abteilung', aber weder die Regel noch ihre Bedingung nennt "
                           "eine Abteilung" if r['quelle_typ'] == 'beitrag'
                           else "Zahler 'Abteilung', aber die Gebühr hat keine Abteilung")
            elif r.get('abteilung_kostenstelle') is None:
                problem = "Abteilung ohne Kostenstelle (für die Gegenbuchung erforderlich)"
            else:
                continue
            nachname = r.get('nachname') or ''
            vorname = r.get('vorname')
            fehler.append({
                'quelle_typ': r['quelle_typ'],
                'quelle_id': r['quelle_id'],
                'mitglied_name': f"{nachname}, {vorname}" if vorname else nachname,
                'bezeichnung': r.get('quelle_name') or '',
                'art': 'forderung',
                'problem': problem,
            })
        return fehler
