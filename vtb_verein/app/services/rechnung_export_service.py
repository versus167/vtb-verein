"""RechnungExportService – Übergabe freigegebener Rechnungen an die Buchhaltung.

Bewusst NICHT über FBASC: die Buchungszeile entsteht in der Fibu, die App liefert
den Belegstapel plus eine Übersicht. Das Zip ist flach (alles im Root):

    rechnungen-export-7.zip
    ├─ R42 - Zahlung Aussteller - Fussball - Sportmaterial - Trikots - beleg.pdf
    ├─ R42 - Zahlung Aussteller - Fussball - Sportmaterial - Trikots - lieferschein.jpg
    ├─ R43 - Erstattung Tim Trainer - Verein - Reisekosten - Fahrt - tanken.pdf
    └─ uebersicht.csv

Der Dateiname trägt die erfassten Angaben mit (`_dateiname`), weil der Import auf
der Fibu-Seite die `uebersicht.csv` derzeit nicht mitliest: wer nur den Ordner vor
sich hat, muss trotzdem sehen, an wen gezahlt wird, aus welcher Abteilung und
wofür. Die Zeichen sind auf ASCII und Windows-taugliche Namen reduziert; führend
steht die Rechnungsnummer, damit Datei und CSV-Zeile zusammenfinden. Sobald die
Fibu die Übersicht auswerten kann, darf das wieder schrumpfen.

Delta-Semantik wie beim Fibu-/Kassenexport: exportiert wird, was freigegeben und
noch in keinem Lauf gestempelt ist. Ein Lauf lässt sich zurücknehmen (Un-Export),
solange er der jüngste ist – danach nur noch über einen neuen Lauf korrigieren.

Andockpunkt für einen späteren FBASC-Export: die Rechnung trägt bereits Betrag,
Empfänger und (über die Kategorie) das Aufwandskonto; es fehlt dann nur die
Kreditor-Auflösung analog FibuExportService._position_ul.
"""
import csv
import io
import logging
import os
import re
import unicodedata
import zipfile
from datetime import date

logger = logging.getLogger(__name__)

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


class KeineRechnungenError(Exception):
    """Es gibt nichts zu exportieren."""


class NichtJuengsterLaufError(Exception):
    """Un-Export ist nur für den jüngsten Lauf erlaubt."""


class RechnungExportService:

    def __init__(self, rechnung_repo, anhang_repo, export_repo, anhang_service=None):
        self._rechnung = rechnung_repo
        self._anhang_repo = anhang_repo
        self._export = export_repo
        self._anhang_service = anhang_service

    # ------------------------------------------------------------------
    # Öffentliche API
    # ------------------------------------------------------------------

    def vorschau(self) -> dict:
        """Was der nächste Lauf mitnehmen würde – ohne Schreibzugriff."""
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
        }

    def exportieren(self, exportiert_von: str) -> tuple[str, bytes]:
        """Legt den Lauf an, baut das Zip und stempelt die Rechnungen.

        Returns:
            (dateiname, zip_bytes)
        """
        rechnungen = self._rechnung.list_freigegeben_offen()
        if not rechnungen:
            raise KeineRechnungenError(
                "Keine freigegebenen Rechnungen offen – es gibt nichts zu exportieren.")

        export = self._export.create_export(
            exportiert_von=exportiert_von,
            dateiname="pending",              # trägt gleich die echte Lauf-ID
            anzahl_rechnungen=len(rechnungen),
            summe_cent=self._summe_cent(rechnungen),
            rechnung_ids=[r.id for r in rechnungen],
        )
        dateiname = f"rechnungen-export-{export.id}.zip"
        self._export.update_dateiname(export.id, dateiname)
        return dateiname, self._baue_zip(rechnungen)

    def re_download(self, export_id: int) -> tuple[str, bytes]:
        """Baut das Zip eines abgeschlossenen Laufs erneut – kein neuer Lauf."""
        export = self._export.get(export_id)
        if export is None:
            raise KeyError(f"Export {export_id} nicht gefunden")
        rechnungen = self._rechnung.list_fuer_export(export_id)
        return export.dateiname, self._baue_zip(rechnungen)

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
    # Zip-Bau
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
