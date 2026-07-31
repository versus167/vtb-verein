"""
SepaService – eigener SEPA-Lastschrifteinzug (pain.008), Ticket #114.

Hintergrund: Das Lastschrift-Kennzeichen im FBASC-Export lässt sich in hmd nicht
zuverlässig zurücknehmen (leeres Feld = „keine Änderung"). Damit der Einzugs-Haken im
Profil die EINZIGE Wahrheit über den Einzug ist, erzeugt die App die Lastschriftdatei
selbst, statt hmd einziehen zu lassen.

Ablauf:
1. vorschau(...)   → einziehbare Posten + nicht einziehbare mit Grund (ohne Schreibzugriff)
2. erzeugen(...)   → Lauf anlegen (Header + Positions-Snapshot), XML rendern
3. re_download(id) → einen früheren Lauf erneut rendern (aus dem Snapshot, byte-stabil)
4. zuruecknehmen(id) → Lauf soft-löschen; die Posten sind wieder einziehbar

Einziehbar ist ein offener Posten, wenn das Mitglied den Einzugs-Haken hat
(zahlungsart='lastschrift'), eine gültige IBAN und Mandatsangaben vorliegen und der
Betrag > 0 ist. Fällig heißt: Fälligkeitsdatum ≤ Ausführungsdatum (Beiträge ohne
Fälligkeit gelten als fällig).

Mandatsangaben: wie im FBASC-Export wird ein fehlender Wert abgeleitet – Referenz aus der
Mitgliedsnummer, Datum aus dem Eintrittsdatum (so abgestimmt). Die Datei enthält damit
Mandatsangaben, die nicht zwingend so unterschrieben wurden; vor dem ersten echten Einzug
sind die Referenzen gegen die Papier-Mandate zu prüfen.

Was dieser Service NICHT tut (Etappe 2): die eingezogenen Posten auf „bezahlt" setzen und
die Verbuchung (Bank an Debitor) an die Fibu übergeben. Bis dahin bleibt ein Lauf ein
reines Zahlungsdokument.
"""
from datetime import date, datetime
from typing import Optional

from app.models.sepa import SepaKandidat, SepaLauf, SepaPosition
from app.services import sepa_formatter
from app.services.iban import is_valid_iban, normalize_iban


class SepaFehler(Exception):
    """Lauf nicht möglich – fehlende Gläubiger-Konfiguration oder keine Posten."""

    def __init__(self, fehler: list[str]):
        self.fehler = fehler
        super().__init__("; ".join(fehler))


def _cent(betrag) -> int:
    return int(round(float(betrag or 0) * 100))


def _iso(wert) -> Optional[str]:
    """Datumsanteil als ISO-String; leer → None (Postgres liefert date-Objekte)."""
    if not wert:
        return None
    if isinstance(wert, date):   # datetime ist Subklasse von date
        return wert.isoformat()[:10]
    return str(wert)[:10]


class SepaService:

    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------------------
    # Öffentliche API
    # ------------------------------------------------------------------

    def vorschau(self, ausfuehrung: Optional[str] = None, heute: Optional[date] = None) -> dict:
        """Einziehbare und nicht einziehbare Posten zum (frühest möglichen) Ausführungsdatum."""
        einst = self.db.fibu_einstellungen.get()
        termin = ausfuehrung or self.fruehestes_ausfuehrungsdatum(einst, heute)
        kandidaten = [self._kandidat(r) for r in self.db.sepa.list_kandidaten(termin)]
        einziehbar = [k for k in kandidaten if k.ausschluss is None]
        return {
            'ausfuehrungsdatum': termin,
            'einziehbar': einziehbar,
            'nicht_einziehbar': [k for k in kandidaten if k.ausschluss is not None],
            'anzahl': len(einziehbar),
            'summe_cent': sum(k.betrag_cent for k in einziehbar),
            'konfiguration_fehler': self._konfiguration_fehler(einst),
        }

    def erzeugen(self, erstellt_von: str, ausfuehrung: Optional[str] = None,
                 heute: Optional[date] = None) -> tuple[SepaLauf, bytes]:
        """Legt einen Einzugslauf an und rendert die pain.008.

        Nicht einziehbare Posten werden übersprungen (nicht als Fehler behandelt) – sie
        stehen in der Vorschau mit Grund und sollen den Lauf für alle anderen nicht
        blockieren.
        """
        einst = self.db.fibu_einstellungen.get()
        fehler = self._konfiguration_fehler(einst)
        if fehler:
            raise SepaFehler(fehler)

        v = self.vorschau(ausfuehrung=ausfuehrung, heute=heute)
        if not v['einziehbar']:
            raise SepaFehler(["Keine einziehbaren Posten vorhanden."])

        erzeugt_am = datetime.now()
        lauf = SepaLauf(
            dateiname=f"sepa_{v['ausfuehrungsdatum']}.xml",
            message_id=sepa_formatter.message_id(erzeugt_am),
            ausfuehrungsdatum=v['ausfuehrungsdatum'],
            sequenztyp=sepa_formatter.SEQUENZTYP,
            glaeubiger_id=einst.sepa_glaeubiger_id,
            glaeubiger_name=einst.sepa_glaeubiger_name,
            glaeubiger_iban=normalize_iban(einst.sepa_iban),
            glaeubiger_bic=(einst.sepa_bic or None),
        )
        positionen = [self._position(k) for k in v['einziehbar']]
        gespeichert = self.db.sepa.create_lauf(lauf, positionen, erstellt_von=erstellt_von)
        return gespeichert, sepa_formatter.render(gespeichert, erzeugt_am=erzeugt_am)

    def re_download(self, lauf_id: int) -> bytes:
        """Rendert einen früheren Lauf erneut – aus dem gespeicherten Snapshot."""
        lauf = self.db.sepa.get_lauf(lauf_id)   # KeyError → 404
        if lauf.deleted_at:
            raise ValueError("Dieser Lauf wurde zurückgenommen.")
        return sepa_formatter.render(lauf, erzeugt_am=self._erzeugt_am(lauf))

    def zuruecknehmen(self, lauf_id: int, benutzer: str) -> dict:
        """Lauf zurücknehmen: die Posten sind danach wieder einziehbar.

        Gedacht für „Datei doch nicht eingereicht". Ist die Datei schon bei der Bank,
        darf sie NICHT zurückgenommen werden – dann läuft die Korrektur über die Bank
        (Rückgabe/Rücklastschrift), nicht über die App.
        """
        lauf = self.db.sepa.get_lauf(lauf_id)   # KeyError → 404
        if lauf.deleted_at:
            raise ValueError("Dieser Lauf ist bereits zurückgenommen.")
        anzahl = self.db.sepa.zuruecknehmen(lauf_id, benutzer=benutzer)
        return {'zurueckgenommen': lauf_id, 'posten_wieder_offen': anzahl}

    def laeufe(self) -> list[SepaLauf]:
        return self.db.sepa.list_laeufe()

    # ------------------------------------------------------------------
    # Interne Hilfsmethoden
    # ------------------------------------------------------------------

    @staticmethod
    def fruehestes_ausfuehrungsdatum(einst, heute: Optional[date] = None) -> str:
        """Erster TARGET2-Tag, der die eingestellte Vorlauffrist einhält (ISO)."""
        vorlauf = einst.sepa_vorlauftage if einst.sepa_vorlauftage is not None else 2
        return sepa_formatter.ausfuehrungsdatum(heute or date.today(), vorlauf).isoformat()

    @staticmethod
    def _konfiguration_fehler(einst) -> list[str]:
        """Prüft die Gläubiger-Angaben, ohne die keine gültige pain.008 entsteht."""
        fehler = []
        if not (einst.sepa_glaeubiger_id or '').strip():
            fehler.append("Gläubiger-ID (Creditor Identifier) nicht gesetzt")
        if not (einst.sepa_glaeubiger_name or '').strip():
            fehler.append("Gläubiger-Name nicht gesetzt")
        iban = normalize_iban(einst.sepa_iban)
        if not iban:
            fehler.append("IBAN des Vereinskontos nicht gesetzt")
        elif not is_valid_iban(iban):
            fehler.append("IBAN des Vereinskontos ist ungültig")
        return fehler

    @staticmethod
    def _erzeugt_am(lauf: SepaLauf) -> datetime:
        """CreDtTm eines Re-Downloads: der ursprüngliche Erstellzeitpunkt."""
        if isinstance(lauf.created_at, datetime):
            return lauf.created_at
        try:
            return datetime.fromisoformat(str(lauf.created_at))
        except (TypeError, ValueError):
            return datetime.now()

    def _kandidat(self, row: dict) -> SepaKandidat:
        """Rohzeile → Vorschau-Eintrag, inkl. Prüfung auf Einziehbarkeit."""
        nummer = row.get('mitgliedsnummer')
        vorname, nachname = row.get('vorname'), row.get('nachname') or ''
        name = f"{nachname}, {vorname}" if vorname else nachname
        bezeichnung = " ".join(x for x in (row.get('quelle_name'), row.get('periode')) if x)
        iban = normalize_iban(row.get('iban'))
        betrag_cent = _cent(row.get('betrag_soll'))
        # Mandats-Fallback wie im FBASC-Export: gespeicherter Wert hat Vorrang.
        mandatsref = row.get('sepa_mandatsref') or (str(nummer) if nummer is not None else None)
        mandatsdatum = _iso(row.get('sepa_mandatsdatum')) or _iso(row.get('eintrittsdatum'))
        kontoinhaber = (row.get('kontoinhaber') or '').strip() or f"{vorname or ''} {nachname}".strip()

        return SepaKandidat(
            quelle_typ=row['quelle_typ'],
            quelle_id=row['quelle_id'],
            mitglied_id=row.get('mitglied_id') or 0,
            mitglied_name=name,
            mitgliedsnummer=nummer,
            bezeichnung=bezeichnung,
            betrag_cent=betrag_cent,
            faelligkeitsdatum=_iso(row.get('faelligkeitsdatum')),
            iban=iban,
            bic=row.get('bic') or None,
            kontoinhaber=kontoinhaber,
            mandatsref=mandatsref,
            mandatsdatum=mandatsdatum,
            ausschluss=self._ausschluss(row, iban, betrag_cent, mandatsref, mandatsdatum),
        )

    @staticmethod
    def _ausschluss(row: dict, iban: Optional[str], betrag_cent: int,
                    mandatsref: Optional[str], mandatsdatum: Optional[str]) -> Optional[str]:
        """Grund, warum ein Posten NICHT eingezogen werden kann – None = einziehbar."""
        gruende = []
        if row.get('zahlungsart') != 'lastschrift':
            gruende.append("kein Einzugs-Haken im Profil (Zahlungsart)")
        if not iban:
            gruende.append("keine IBAN hinterlegt")
        elif not is_valid_iban(iban):
            gruende.append("IBAN ungültig")
        if not mandatsref:
            gruende.append("keine Mandatsreferenz (und keine Mitgliedsnummer zum Ableiten)")
        if not mandatsdatum:
            gruende.append("kein Mandatsdatum (und kein Eintrittsdatum zum Ableiten)")
        if betrag_cent <= 0:
            gruende.append("Betrag ist 0")
        return "; ".join(gruende) or None

    @staticmethod
    def _position(k: SepaKandidat) -> SepaPosition:
        return SepaPosition(
            quelle_typ=k.quelle_typ,
            quelle_id=k.quelle_id,
            mitglied_id=k.mitglied_id,
            betrag_cent=k.betrag_cent,
            end_to_end_id=sepa_formatter.end_to_end_id(k.quelle_typ, k.quelle_id),
            mandatsref=k.mandatsref,
            mandatsdatum=k.mandatsdatum,
            iban=k.iban,
            bic=k.bic,
            kontoinhaber=k.kontoinhaber,
            verwendungszweck=k.bezeichnung or None,
        )
