"""RechnungExportService – Übergabe freigegebener Rechnungen an die Buchhaltung.

Seit v109 im hmd-FBASC-Format, wie Kassenbuch und Sollstellungen: Eine freigegebene
Rechnung ist eine Verbindlichkeit und wird als Kreditor-Buchung gerendert – Aufwand
(Kategorie-Sachkonto, Feld 01) im Soll gegen Kreditor (Feld 00) im Haben. Vorher lag
dem Zip nur ein Belegstapel plus `uebersicht.csv` bei und die Buchungszeile entstand
von Hand in der Fibu.

Das Zip ist flach (alles im Root):

    rechnungen-export-7.zip
    ├─ fbasc.hia
    ├─ R42 - Zahlung Aussteller - Fussball - Sportmaterial - Trikots - beleg.pdf
    ├─ R42 - Zahlung Aussteller - Fussball - Sportmaterial - Trikots - lieferschein.jpg
    ├─ R43 - Erstattung Tim Trainer - Verein - Reisekosten - Fahrt - tanken.pdf
    └─ uebersicht.csv

Der Dateiname trägt die erfassten Angaben mit (`_dateiname`): Wer nur den Ordner vor
sich hat, soll sehen, an wen gezahlt wird, aus welcher Abteilung und wofür. Die
Zeichen sind auf ASCII und Windows-taugliche Namen reduziert; führend steht die
Rechnungsnummer, damit Datei, Buchungszeile (Feld 39) und CSV-Zeile zusammenfinden.
Feld 39 fasst 255 Zeichen, die Namen bleiben deutlich darunter.

Die `uebersicht.csv` bleibt als Lesehilfe erhalten – sie bekommt bewusst KEINE
Buchungszeile: Sie ist kein Beleg, sondern die menschenlesbare Zusammenfassung
dessen, was in der `fbasc.hia` steht. (Beim Kassenbuch ist das anders: der
Kassenbericht dort ist ein aufbewahrungspflichtiger Beleg und bekommt eine
0,00-Zeile.)

Kreditor-Auflösung (Feld 00):
- Erstattung an ein Mitglied → Personenkonto = ul_kreditor_konto_basis +
  Mitgliedsnummer. Dieselbe Person hat nur EIN Kreditorkonto, gleich ob sie
  Übungsleiter-Honorar oder ausgelegtes Geld zurückbekommt.
- Externer Rechnungsaussteller → der Standard-Kreditor aus den Einstellungen des
  Rechnungs-Bereichs; einen Lieferantenstamm führt die App nicht. Name und
  Bankverbindung stehen, soweit erfasst, in den Personenfeldern der Zeile
  (22/40/70), damit die Fibu zahlen kann.

Mehrere Belege zu einer Rechnung: der erste steht in Feld 39 der Buchungszeile,
jeder weitere bekommt eine 0,00-Zeile auf denselben Konten (Muster Kassenbuch) –
sonst wäre er der Buchung nicht zugeordnet.

Delta-Semantik wie beim Fibu-/Kassenexport: exportiert wird, was freigegeben und
noch in keinem Lauf gestempelt ist. Ein Lauf lässt sich zurücknehmen (Un-Export),
solange er der jüngste ist – danach nur noch über einen neuen Lauf korrigieren.

Läufe aus der Zeit vor v109 tragen `format='zip'` und werden beim Re-Download
weiterhin im alten Aufbau gerendert (ohne `fbasc.hia`) – ein bereits übergebener
Lauf soll beim erneuten Herunterladen dieselbe Datei liefern wie damals.
"""
import csv
import io
import logging
import os
import re
import unicodedata
import zipfile
from dataclasses import replace
from datetime import date, timedelta

from app.models.fibu import FibuExportPosition
from app.services import fibu_formatter

logger = logging.getLogger(__name__)

# Zahlungsziel: Fälligkeit = Belegdatum + NETTOTAGE. Gleicher Wert wie im
# Sollstellungs-Export (FibuExportService.NETTOTAGE).
NETTOTAGE = 10

_UEBERSICHT_DATEINAME = "uebersicht.csv"

_CSV_KOPF = (
    "Nr", "Belegdateien", "Kategorie", "Sachkonto", "Abteilung", "Kostenstelle",
    "Kostentraeger", "Betrag EUR", "Rechnungsdatum", "Rechnungsnummer",
    # „Zahlung an" trägt die Entscheidung des Einreichers (Erstattung vs.
    # Aussteller) – sie steuert, wohin das Geld fließt. Empfaenger/IBAN sind die
    # Details dazu und bleiben leer, solange sie nur auf dem Beleg stehen.
    "Zahlung an", "Empfaenger", "IBAN",
    "Beschreibung", "Eingereicht von", "Freigegeben von", "Freigegeben am",
)

_ZAHLUNG_AN = {
    "mitglied": "Erstattung an Einreicher",
    "extern": "Rechnungsaussteller",
}

# Dateinamen: " - " trennt die Bestandteile, deshalb darf es innerhalb eines
# Bestandteils nicht vorkommen (siehe _teil). Die Grenzen halten den Namen unter
# dem, was Windows beim Entpacken in tiefen Ordnern noch verkraftet.
_TRENNER = " - "
_MAX_TEIL = 40
_MAX_BASIS = 150

_UMLAUTE = str.maketrans({
    "ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss",
})


def _iso(wert) -> str:
    """Beliebiges Datum → ISO (YYYY-MM-DD); leer/ungültig → ''.

    Postgres liefert für DATE/TIMESTAMP-Spalten Objekte, für die als TEXT
    geführten Datumsfelder Strings – beides landet hier."""
    if not wert:
        return ""
    if isinstance(wert, date):  # datetime ist Subklasse von date
        return wert.isoformat()[:10]
    return str(wert)[:10]


def _plus_tage(iso: str, tage: int) -> str:
    """ISO-Datum + n Tage; leer/ungültig → ''."""
    if not iso:
        return ""
    try:
        return (date.fromisoformat(iso) + timedelta(days=tage)).isoformat()
    except ValueError:
        return ""


def _buchungstext(bezeichnung: str, beschreibung: str, person: str,
                  rechnungsnummer) -> str:
    """Feld 12: Kategorie, Notiz, Empfänger und – falls vorhanden – die Nummer des
    Ausstellers. Der Formatter kappt bei 250 Zeichen; die Reihenfolge sorgt dafür,
    dass dabei die Notiz und nicht die Kategorie verloren geht."""
    teile = [bezeichnung]
    if beschreibung:
        teile.append(beschreibung)
    if rechnungsnummer:
        teile.append(f"Rg. {rechnungsnummer}")
    if person:
        teile.append(person)
    return " – ".join(t for t in teile if t)


class KeineRechnungenError(Exception):
    """Es gibt nichts zu exportieren."""


class NichtJuengsterLaufError(Exception):
    """Un-Export ist nur für den jüngsten Lauf erlaubt."""


class FibuRechnungExportFehler(Exception):
    """Konten unvollständig konfiguriert – der Lauf wird gar nicht erst angelegt.

    Trägt die Einzelmeldungen, damit die Oberfläche zeigen kann, WAS fehlt, statt
    nur „Export fehlgeschlagen". Muster: FibuKassenExportFehler.
    """

    def __init__(self, fehler: list[str]):
        self.fehler = fehler
        super().__init__("; ".join(fehler))


class RechnungExportService:

    def __init__(self, rechnung_repo, anhang_repo, export_repo, anhang_service=None,
                 fibu_einstellungen_repo=None):
        self._rechnung = rechnung_repo
        self._anhang_repo = anhang_repo
        self._export = export_repo
        self._anhang_service = anhang_service
        self._fibu_einstellungen = fibu_einstellungen_repo

    # ------------------------------------------------------------------
    # Öffentliche API
    # ------------------------------------------------------------------

    def vorschau(self) -> dict:
        """Was der nächste Lauf mitnehmen würde – ohne Schreibzugriff.

        `hinweise` sind Warnungen (fehlender Beleg), `fehler` sind Gründe, aus
        denen der Lauf abbrechen WÜRDE (fehlende Konten). Beide vorab zu zeigen
        ist der Sinn der Vorschau: Ein Konto, das erst beim Klick auffällt, kostet
        den Anwender den Weg in die Fibu-Einstellungen und zurück.
        """
        rechnungen = self._rechnung.list_freigegeben_offen()
        hinweise: list[str] = []
        for r in rechnungen:
            anhaenge = self._anhang_repo.list_by_rechnung(r.id)
            if not anhaenge:
                hinweise.append(f"Rechnung #{r.id}: kein Beleg vorhanden.")
                continue
            for a in anhaenge:
                if not self._datei_vorhanden(a):
                    hinweise.append(
                        f"Rechnung #{r.id}: Beleg „{a.original_name}“ fehlt auf dem Server.")
        return {
            "rechnungen": rechnungen,
            "anzahl": len(rechnungen),
            "summe_cent": self._summe_cent(rechnungen),
            "hinweise": hinweise,
            "fehler": self._konten_fehler(self._rechnung.list_fbasc_offen()),
        }

    def exportieren(self, exportiert_von: str) -> tuple[str, bytes]:
        """Legt den Lauf an, baut das Zip und stempelt die Rechnungen.

        Die Konten werden VOR dem Anlegen des Laufs geprüft: Ein Lauf, dessen
        `fbasc.hia` die Fibu nicht einlesen kann, hätte die Rechnungen gestempelt
        und müsste erst zurückgenommen werden.

        Raises:
            KeineRechnungenError: nichts freigegeben und offen.
            FibuRechnungExportFehler: Konten unvollständig konfiguriert.

        Returns:
            (dateiname, zip_bytes)
        """
        rechnungen = self._rechnung.list_freigegeben_offen()
        if not rechnungen:
            raise KeineRechnungenError(
                "Keine freigegebenen Rechnungen offen – es gibt nichts zu exportieren.")

        zeilen = self._rechnung.list_fbasc_offen()
        fehler = self._konten_fehler(zeilen)
        if fehler:
            raise FibuRechnungExportFehler(fehler)

        export = self._export.create_export(
            exportiert_von=exportiert_von,
            dateiname="pending",              # trägt gleich die echte Lauf-ID
            anzahl_rechnungen=len(rechnungen),
            summe_cent=self._summe_cent(rechnungen),
            rechnung_ids=[r.id for r in rechnungen],
            format="fbasc",
        )
        dateiname = f"rechnungen-export-{export.id}.zip"
        self._export.update_dateiname(export.id, dateiname)
        return dateiname, self._baue_fbasc_zip(rechnungen, zeilen)

    def re_download(self, export_id: int) -> tuple[str, bytes]:
        """Baut das Zip eines abgeschlossenen Laufs erneut – kein neuer Lauf.

        Läufe von vor v109 tragen `format='zip'` und werden im alten Aufbau
        gerendert: Ein erneuter Download soll liefern, was damals übergeben wurde,
        und nicht nachträglich eine Buchungsdatei erfinden.
        """
        export = self._export.get(export_id)
        if export is None:
            raise KeyError(f"Export {export_id} nicht gefunden")
        rechnungen = self._rechnung.list_fuer_export(export_id)
        if export.format != "fbasc":
            return export.dateiname, self._baue_zip(rechnungen)
        zeilen = self._rechnung.list_fbasc_fuer_export(export_id)
        return export.dateiname, self._baue_fbasc_zip(rechnungen, zeilen)

    def zuruecknehmen(self, export_id: int, benutzer: str) -> dict:
        """Un-Export des jüngsten Laufs: Stempel lösen, Header soft-deleten.

        Die Rechnungen erscheinen danach wieder in der Vorschau.
        """
        export = self._export.get(export_id)
        if export is None:
            raise KeyError(f"Export {export_id} nicht gefunden")
        if not self._export.is_latest(export_id):
            raise NichtJuengsterLaufError(
                "Nur der jüngste Lauf kann zurückgenommen werden – ältere bitte über "
                "einen neuen Lauf korrigieren.")
        anzahl = self._export.un_export(export_id, benutzer=benutzer)
        return {"zurueckgenommen": export_id, "rechnungen_wieder_offen": anzahl}

    def list_exporte(self) -> list:
        return self._export.list_exporte()

    # ------------------------------------------------------------------
    # FBASC
    # ------------------------------------------------------------------

    def _einstellungen(self):
        if self._fibu_einstellungen is None:
            raise FibuRechnungExportFehler(
                ["Fibu-Einstellungen nicht verfügbar – Export nicht möglich."])
        return self._fibu_einstellungen.get()

    def _konten_fehler(self, zeilen: list[dict]) -> list[str]:
        """Sammelt, was den Lauf scheitern ließe – ein Eintrag je Ursache.

        Bewusst je Ursache und nicht je Rechnung: Fehlt das Sachkonto einer
        Kategorie, betrifft das alle Rechnungen dieser Kategorie, und zwanzig
        gleichlautende Zeilen helfen niemandem. Der Empfänger ist die Ausnahme –
        der hängt an der einzelnen Rechnung.
        """
        if not zeilen:
            return []
        try:
            einst = self._einstellungen()
        except FibuRechnungExportFehler as exc:
            return list(exc.fehler)

        fehler: list[str] = []
        ohne_sachkonto = sorted({
            (z.get("kategorie_name") or "ohne Kategorie")
            for z in zeilen if not z.get("kategorie_sachkonto")
        })
        for name in ohne_sachkonto:
            fehler.append(f"Kategorie „{name}“ hat kein Sachkonto (Feld 01).")

        braucht_sammelkonto = any(z.get("empfaenger_typ") != "mitglied"
                                  or z.get("mitgliedsnummer") is None for z in zeilen)
        if braucht_sammelkonto and not einst.rechnung_kreditor_konto:
            fehler.append("Kein Standard-Kreditor gesetzt (Rechnungen → "
                          "Einstellungen) – nötig, wenn nicht an den Einreicher "
                          "gezahlt wird.")
        if any(z.get("empfaenger_typ") == "mitglied" and z.get("mitgliedsnummer") is not None
               for z in zeilen) and einst.ul_kreditor_konto_basis is None:
            fehler.append("ÜL-Kreditor-Konto-Basis nicht gesetzt (Finanzen → "
                          "Fibu-Export) – nötig für Erstattungen an Mitglieder.")
        for z in zeilen:
            if not z.get("betrag_cent"):
                fehler.append(f"Rechnung #{z['id']}: kein Betrag erfasst.")
        return fehler

    def _kostenstelle(self, z: dict, einst):
        """Kostenstelle (Feld 07): Kategorie → Abteilung → Verein-Default.

        Dieselbe Reihenfolge wie im Sollstellungs-Export: Die Kategorie ist die
        speziellste Angabe, die Abteilung die naheliegende, der Verein die
        Auffanglinie."""
        if z.get("kategorie_kostenstelle") is not None:
            return z["kategorie_kostenstelle"]
        if z.get("abteilung_kostenstelle") is not None:
            return z["abteilung_kostenstelle"]
        return einst.verein_kostenstelle

    @staticmethod
    def _belegdatum(z: dict) -> str:
        """Belegdatum (Feld 10): Rechnungsdatum, sonst der Tag der Freigabe.

        Das Rechnungsdatum ist optional – die Geschäftsstelle trägt es bei Bedarf
        nach. Fehlt es, ist der Freigabetag der einzige Zeitpunkt, den die App
        sicher kennt; ein leeres Feld 10 wäre bei belegtem Betrag unzulässig."""
        return _iso(z.get("rechnungsdatum")) or _iso(z.get("freigegeben_am")) or ""

    def _fbasc_position(self, z: dict, einst, dokument) -> FibuExportPosition:
        """Eine freigegebene Rechnung → Kreditor-Zeile (Aufwand S gegen Kreditor H)."""
        ist_mitglied = (z.get("empfaenger_typ") == "mitglied"
                        and z.get("mitgliedsnummer") is not None)
        if ist_mitglied:
            konto = (einst.ul_kreditor_konto_basis or 0) + z["mitgliedsnummer"]
            nachname = z.get("nachname") or ""
            vorname = z.get("vorname")
            iban = (z.get("empfaenger_iban") or "").strip() or z.get("mitglied_iban")
            suchname = str(z["mitgliedsnummer"])
        else:
            konto = einst.rechnung_kreditor_konto
            # Der Aussteller hat keinen Stammsatz: Sein Name steht komplett im
            # Namensfeld (22), einen Vornamen gibt es nicht zu trennen. Ist an der
            # Rechnung kein Name erfasst, bleibt es beim Platzhalter – der
            # Zahlungsempfänger steht dann nur auf dem beiliegenden Beleg.
            nachname = (z.get("empfaenger_name") or "").strip() or "Unbekannter Aussteller"
            vorname = None
            iban = (z.get("empfaenger_iban") or "").strip() or None
            suchname = ""

        belegdatum = self._belegdatum(z)
        person = f"{nachname}, {vorname}" if vorname else nachname
        bezeichnung = z.get("kategorie_name") or "Rechnung"
        beschreibung = (z.get("beschreibung") or "").strip()

        # Abweichender Kontoinhaber (Feld 70) nur, wenn er wirklich abweicht –
        # sonst meldet die Fibu einen Abweichler, den es nicht gibt.
        voller_name = f"{vorname or ''} {nachname}".strip()
        kontoinhaber = (z.get("kontoinhaber") or "").strip() if ist_mitglied else ""
        abw_kontoinhaber = (kontoinhaber if kontoinhaber
                            and kontoinhaber.casefold() != voller_name.casefold() else None)

        return FibuExportPosition(
            quelle_typ="rechnung", quelle_id=z["id"], art="forderung",
            mitglied_id=z.get("empfaenger_mitglied_id") or 0,
            mitglied_name=person,
            bezeichnung=bezeichnung,
            konto=konto,
            gegenkonto=z.get("kategorie_sachkonto"),
            betrag=(z.get("betrag_cent") or 0) / 100,
            # Die freigegebene Rechnung ist eine Verbindlichkeit: Kreditor im Haben.
            soll_haben="H",
            belegnummer=f"R{z['id']}",
            kontenart="K",
            kostenstelle=self._kostenstelle(z, einst),
            kostentraeger=(z.get("kategorie_kostentraeger")
                           if z.get("kategorie_kostentraeger") is not None
                           else einst.default_kostentraeger),
            belegdatum=belegdatum,
            faelligkeitsdatum=_plus_tage(belegdatum, NETTOTAGE),
            buchungstext=_buchungstext(bezeichnung, beschreibung, person,
                                       z.get("rechnungsnummer")),
            dokument=dokument,
            lastschrifteinzug=None,   # der Verein zahlt, er zieht nicht ein
            suchname=suchname,
            nachname=nachname,
            vorname=vorname,
            strasse=z.get("strasse") if ist_mitglied else None,
            plz=z.get("plz") if ist_mitglied else None,
            ort=z.get("ort") if ist_mitglied else None,
            land=z.get("land") if ist_mitglied else None,
            iban=iban,
            bic=z.get("bic") if ist_mitglied else None,
            mailadresse=z.get("email") if ist_mitglied else None,
            kontoinhaber=abw_kontoinhaber,
        )

    def _baue_fbasc_zip(self, rechnungen: list, zeilen: list[dict]) -> bytes:
        """fbasc.hia + Belege + uebersicht.csv, alles flach im Root."""
        einst = self._einstellungen()
        nach_id = {z["id"]: z for z in zeilen}
        positionen: list[FibuExportPosition] = []
        dateien: dict[str, bytes] = {}
        csv_zeilen: list[list] = []
        verwendet: set[str] = set()

        for r in rechnungen:
            namen: list[str] = []
            for a in self._anhang_repo.list_by_rechnung(r.id):
                inhalt = self._lese(a)
                if inhalt is None:
                    continue
                name = self._eindeutig(self._dateiname(r, a), self._ext(a), verwendet)
                dateien[name] = inhalt
                namen.append(name)
            csv_zeilen.append(self._csv_zeile(r, namen))

            z = nach_id.get(r.id)
            if z is None:      # Re-Download eines Laufs, dessen Zeile inzwischen fehlt
                continue
            hauptzeile = self._fbasc_position(z, einst, namen[0] if namen else None)
            positionen.append(hauptzeile)
            # Jeder weitere Beleg als 0,00-Zeile auf denselben Konten – sonst hinge
            # er ohne Bezug zur Buchung im Zip (Muster Kassenbuch-Export).
            for nr, name in enumerate(namen[1:], start=2):
                positionen.append(replace(
                    hauptzeile, betrag=0.0, dokument=name,
                    buchungstext=f"{hauptzeile.buchungstext} (Beleg {nr})"))

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(fibu_formatter.FBASC_DATEINAME, fibu_formatter.render(positionen))
            zf.writestr(_UEBERSICHT_DATEINAME, self._uebersicht_csv(csv_zeilen))
            for name, inhalt in dateien.items():
                zf.writestr(name, inhalt)
        return buf.getvalue()

    # ------------------------------------------------------------------
    # Zip-Bau (Altläufe vor v109 – ohne fbasc.hia)
    # ------------------------------------------------------------------

    def _baue_zip(self, rechnungen: list) -> bytes:
        dateien: dict[str, bytes] = {}
        zeilen: list[list] = []
        verwendet: set[str] = set()

        for r in rechnungen:
            namen: list[str] = []
            for a in self._anhang_repo.list_by_rechnung(r.id):
                inhalt = self._lese(a)
                if inhalt is None:
                    continue
                name = self._eindeutig(self._dateiname(r, a), self._ext(a), verwendet)
                dateien[name] = inhalt
                namen.append(name)
            zeilen.append(self._csv_zeile(r, namen))

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(_UEBERSICHT_DATEINAME, self._uebersicht_csv(zeilen))
            for name, inhalt in dateien.items():
                zf.writestr(name, inhalt)
        return buf.getvalue()

    @staticmethod
    def _uebersicht_csv(zeilen: list[list]) -> bytes:
        """Semikolon-getrennt und mit BOM – so öffnet Excel die Datei ohne Nachfrage."""
        out = io.StringIO()
        writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
        writer.writerow(_CSV_KOPF)
        writer.writerows(zeilen)
        return out.getvalue().encode("utf-8-sig")

    def _csv_zeile(self, r, dateinamen: list[str]) -> list:
        return [
            f"R{r.id}",
            # Die Namen enthalten selbst Leerzeichen – als Trenner taugt hier nur
            # ein Zeichen, das in keinem Dateinamen vorkommen kann.
            " | ".join(dateinamen),
            r.kategorie_name or "",
            r.kategorie_sachkonto or "",
            r.abteilung_name or "",
            r.abteilung_kostenstelle if r.abteilung_kostenstelle is not None else "",
            "",  # Kostenträger: kommt aus der Kategorie, sobald die Konten gepflegt sind
            self._betrag(r),
            r.rechnungsdatum or "",
            r.rechnungsnummer or "",
            _ZAHLUNG_AN.get(r.empfaenger_typ, ""),
            self._empfaenger(r),
            self._iban(r),
            r.beschreibung or "",
            r.created_by or "",
            r.freigegeben_von or "",
            self._datum(r.freigegeben_am),
        ]

    @staticmethod
    def _betrag(r) -> str:
        """Betrag mit Dezimalkomma – die Fibu erwartet deutsches Format."""
        if r.betrag_cent is None:
            return ""
        return f"{r.betrag_cent / 100:.2f}".replace(".", ",")

    @staticmethod
    def _empfaenger(r) -> str:
        return (r.empfaenger_mitglied_name or "").strip() or (r.empfaenger_name or "")

    @staticmethod
    def _iban(r) -> str:
        """An der Rechnung gepflegte IBAN hat Vorrang; bei Erstattung an ein
        Mitglied greift sonst die aus dem Mitgliedsstamm."""
        return (r.empfaenger_iban or "").strip() or (r.empfaenger_mitglied_iban or "")

    @staticmethod
    def _datum(wert) -> str:
        if not wert:
            return ""
        if isinstance(wert, date):  # datetime ist Subklasse von date
            return wert.isoformat()[:10]
        return str(wert)[:10]

    @staticmethod
    def _summe_cent(rechnungen: list) -> int:
        return sum(r.betrag_cent or 0 for r in rechnungen)

    @staticmethod
    def _teil(roh, grenze: int = _MAX_TEIL) -> str:
        """Ein Namensbestandteil: ASCII, ohne Zeichen, die Windows/Zip stören.

        Umlaute werden umschrieben statt weggeworfen ('Fußball' → 'Fussball'),
        und Bindestriche verlieren ihre umgebenden Leerzeichen – sonst wäre
        „Getränke - Meier“ vom Trenner nicht zu unterscheiden.
        """
        s = str(roh or "").translate(_UMLAUTE)
        s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
        s = re.sub(r"[^A-Za-z0-9 _.()+&-]+", " ", s)
        s = re.sub(r"\s*-\s*", "-", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s[:grenze].strip(" .-")

    @staticmethod
    def _zahlung_an_kurz(r) -> str:
        """Wohin das Geld fließt – die wichtigste Angabe, deshalb ganz vorn."""
        if r.empfaenger_typ == "mitglied":
            return f"Erstattung {r.empfaenger_mitglied_name or 'Einreicher'}"
        if r.empfaenger_typ == "extern":
            return (f"Zahlung {r.empfaenger_name}" if r.empfaenger_name
                    else "Zahlung Aussteller")
        return "Empfaenger offen"

    def _dateiname(self, r, anhang) -> str:
        """Basisname (ohne Endung) aus den erfassten Angaben.

        Die Rechnungsnummer steht vorn: sie ist der einzige Bestandteil, der die
        Datei wieder ihrer Zeile in `uebersicht.csv` zuordnet, und sie sortiert
        den Ordner in Einreichungsreihenfolge.
        """
        teile = [
            f"R{r.id}",
            self._teil(self._zahlung_an_kurz(r)),
            self._teil(r.abteilung_name or "Verein"),
            self._teil(r.kategorie_name),
            self._teil(r.beschreibung),                  # Notiz, oft leer
            self._teil(os.path.splitext(anhang.original_name or "")[0]),
        ]
        basis = _TRENNER.join(t for t in teile if t)[:_MAX_BASIS].strip(" .-")
        return basis or f"R{r.id}"

    @staticmethod
    def _eindeutig(basis: str, ext: str, verwendet: set[str]) -> str:
        """Kollisionen durchzählen – case-insensitiv, weil Windows beim Entpacken
        sonst zwei Dateien übereinanderschreibt, die sich nur in der Groß-/
        Kleinschreibung unterscheiden."""
        kandidat, n = f"{basis}{ext}", 1
        while kandidat.lower() in verwendet:
            n += 1
            kandidat = f"{basis} ({n}){ext}"
        verwendet.add(kandidat.lower())
        return kandidat

    @staticmethod
    def _ext(anhang) -> str:
        ext = (os.path.splitext(anhang.stored_name)[1]
               or os.path.splitext(anhang.original_name)[1])
        return ext.lower()

    def _datei_vorhanden(self, anhang) -> bool:
        if self._anhang_service is None:
            return False
        return self._anhang_service.existiert(anhang.stored_name)

    def _lese(self, anhang) -> bytes | None:
        """Beleg vom Datenträger lesen; fehlt die Datei, wird sie übersprungen.

        Ein fehlender Beleg darf den ganzen Lauf nicht kippen – die Vorschau warnt
        vorher, und die Übersicht zeigt die Rechnung dann eben ohne Dateinamen.
        """
        if self._anhang_service is None:
            return None
        try:
            return (self._anhang_service.upload_path / anhang.stored_name).read_bytes()
        except OSError:
            logger.warning("Beleg-Datei fehlt beim Rechnungsexport: %s", anhang.stored_name)
            return None
