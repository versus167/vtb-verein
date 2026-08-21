"""Service für die Übungsleiter-Stundenerfassung.

Kapselt die Domänenlogik: Zeitraum-Validierung, Sperr-Wasserzeichen (nach
Einreichen/Bestätigen ist der Zeitraum bis zum letzten Tag gesperrt),
Satz-Auflösung beim Einreichen (Snapshot) sowie Summen/Monatsaggregate für
Anzeige und Beleg. Berechtigungs-/Eigentümer-Prüfungen liegen im API-Router.

Validierungsfehler werden als ValueError geworfen; der Router bildet sie auf
HTTP 400 ab (Muster GebuehrenService).
"""
from dataclasses import asdict
from datetime import date, timedelta
from typing import Optional

from app.models.ul_stunden import (
    ULAbrechnung, ULStunde, LIZENZ_MIT, LIZENZ_OHNE, STATUS_ENTWURF,
    VERGUETUNG_STUNDENSATZ, VERGUETUNG_MONATSPAUSCHALE, VERGUETUNG_OHNE,
)
from app.services.ul_stundennachweis_pdf_service import erstelle_stundennachweis_pdf


def _as_date(s: str) -> date:
    return date.fromisoformat(s[:10])


def monatsschluessel(von: str, bis: str) -> list[str]:
    """Angebrochene Kalendermonate zwischen von und bis (beide inkl.), als 'YYYY-MM'.

    Bemessungsgrundlage der Monatspauschale: Sep–Nov sind drei Monate, auch wenn im
    Oktober kein Termin stattfand. Der Festbetrag ist eine Vereinbarung über den
    Zeitraum, nicht über die geleisteten Einheiten – wer nur einzelne Monate
    abrechnen will, schneidet den Zeitraum entsprechend.

    Monate statt einer bloßen Anzahl, weil sie über Abrechnungen hinweg gegeneinander
    abgeglichen werden müssen (s. ULStundenService.verguetungs_monate).
    """
    v, b = _as_date(von), _as_date(bis)
    if b < v:
        return []
    out, jahr, monat = [], v.year, v.month
    while (jahr, monat) <= (b.year, b.month):
        out.append(f"{jahr:04d}-{monat:02d}")
        jahr, monat = (jahr + 1, 1) if monat == 12 else (jahr, monat + 1)
    return out


def monate_im_zeitraum(von: str, bis: str) -> int:
    """Anzahl angebrochener Kalendermonate – s. monatsschluessel."""
    return len(monatsschluessel(von, bis))


def berechne_betrag(verguetungsart: str, satz: Optional[float], summe_stunden: float,
                    anzahl_monate: int) -> Optional[float]:
    """Betrag einer Abrechnung – die einzige Stelle, an der die Art zu Geld wird.

    None heißt „kein Betrag": entweder gibt es keine Vereinbarung, oder sie sieht
    gar keine Auszahlung über die App vor. `anzahl_monate` sind die tatsächlich zu
    vergütenden Monate (bereits anderweitig vergütete abgezogen), nicht einfach die
    Monate im Zeitraum – die Abgrenzung macht ULStundenService.verguetungs_monate.

    Achtung: dieselbe Multiplikation steckt ein zweites Mal in SQL (`_SQL_UL` im
    fibu_export_repository), weil der Export über alle Abrechnungen aggregiert.
    Sie kommt dort aber mit dem eingefrorenen `verguetung_monate` aus – die
    Abgrenzungslogik selbst gibt es nur hier.
    """
    if verguetungsart == VERGUETUNG_OHNE or satz is None:
        return None
    if verguetungsart == VERGUETUNG_MONATSPAUSCHALE:
        return round(anzahl_monate * satz, 2)
    return round(summe_stunden * satz, 2)


class ULStundenService:
    def __init__(self, db):
        self.db = db

    # ----------------------------------------------------------- Sperr-Logik
    def erfassbar_ab(self, mitglied_id: int, abteilung_id: int) -> Optional[str]:
        """Frühestes erfassbares Datum (ISO) oder None, wenn nichts gesperrt ist.

        = letzter Tag der jüngsten eingereichten/bestätigten Abrechnung + 1 Tag.
        """
        bis = self.db.ul_abrechnungen.max_gesperrt_bis(mitglied_id, abteilung_id)
        if not bis:
            return None
        return (_as_date(bis) + timedelta(days=1)).isoformat()

    def _pruefe_sperre(self, mitglied_id: int, abteilung_id: int, von: str) -> None:
        sperr = self.erfassbar_ab(mitglied_id, abteilung_id)
        if sperr and _as_date(von) < _as_date(sperr):
            raise ValueError(
                f"Zeitraum bereits abgerechnet/eingereicht – frühestens ab {sperr} erfassbar"
            )

    def _validiere_zeitraum(self, von: str, bis: str) -> None:
        try:
            dv, db_ = _as_date(von), _as_date(bis)
        except (ValueError, TypeError):
            raise ValueError("Ungültiges Datum")
        if dv > db_:
            raise ValueError("'von' darf nicht nach 'bis' liegen")

    # ------------------------------------------------------ Monats-Abgrenzung
    def verguetungs_monate(self, abrechnung: ULAbrechnung) -> list[str]:
        """Kalendermonate, die diese Abrechnung als Monatspauschale vergütet.

        Jeder Monat wird höchstens einmal bezahlt: Ragen zwei aufeinanderfolgende
        Abrechnungen in denselben Monat (15.05.–15.06. und dann 16.06.–10.07.),
        gehört er der ersten – zusammen sind das drei Pauschalen, nicht vier. Das
        Sperr-Wasserzeichen allein verhindert das nicht; es rechnet tagegenau und
        lässt den direkten Anschluss ausdrücklich zu.

        Maßgeblich sind die Zeiträume der anderen Abrechnungen, nicht deren eigene
        Abgrenzung: Ein Monat, den eine frühere Abrechnung berührt, ist entweder von
        ihr oder von einer noch früheren vergütet – in beiden Fällen ist er vergeben.
        """
        eigene = monatsschluessel(abrechnung.zeitraum_von, abrechnung.zeitraum_bis)
        if not eigene:
            return []
        belegt: set[str] = set()
        for von, bis in self.db.ul_abrechnungen.monatspauschal_zeitraeume(
                abrechnung.mitglied_id, abrechnung.abteilung_id,
                exclude_id=abrechnung.id):
            belegt.update(monatsschluessel(von, bis))
        return [m for m in eigene if m not in belegt]

    # --------------------------------------------------------------- Lizenz
    def lizenz_fuer(self, mitglied_id: int, bis: str) -> str:
        """Leitet die Lizenz-Klassifikation aus den Mitglied-Stammdaten ab: 'mit_lizenz',
        wenn die Trainerlizenz am Ende des Abrechnungszeitraums (`bis`) im Gültigkeitsfenster
        [trainerlizenz_gueltig_von, trainerlizenz_gueltig_bis] liegt – sonst 'ohne_lizenz'.
        Maßstab ist das Zeitraum-Ende (eine Klassifikation je Abrechnung). Fehlt eines der
        beiden Datümer = ohne (die Kopplung erzwingt: nr + von + bis nur gemeinsam)."""
        try:
            m = self.db.get_mitglied(mitglied_id)
        except (KeyError, AttributeError):
            m = None
        von = getattr(m, 'trainerlizenz_gueltig_von', None) if m else None
        bis_lizenz = getattr(m, 'trainerlizenz_gueltig_bis', None) if m else None
        if von and bis_lizenz and _as_date(von) <= _as_date(bis) <= _as_date(bis_lizenz):
            return LIZENZ_MIT
        return LIZENZ_OHNE

    # ----------------------------------------------------------- Kopf / CRUD
    def create_abrechnung(self, *, mitglied_id: int, abteilung_id: int, von: str, bis: str,
                          erstellt_von: str) -> ULAbrechnung:
        self._validiere_zeitraum(von, bis)
        self._pruefe_sperre(mitglied_id, abteilung_id, von)
        if self.db.ul_abrechnungen.has_overlap(mitglied_id, abteilung_id, von, bis):
            raise ValueError("Zeitraum überschneidet sich mit einer bestehenden Abrechnung")
        a = ULAbrechnung(
            mitglied_id=mitglied_id, abteilung_id=abteilung_id,
            zeitraum_von=von, zeitraum_bis=bis,
            lizenz_klassifikation=self.lizenz_fuer(mitglied_id, bis),
            foerder_klassifikation=None,   # Buchungsdetail – nicht bei der Erfassung
        )
        return self.db.ul_abrechnungen.create(a, created_by=erstellt_von)

    def update_kopf(self, abrechnung: ULAbrechnung, *, von: str, bis: str,
                    expected_version: int, updated_by: str) -> bool:
        if abrechnung.status != STATUS_ENTWURF:
            raise ValueError("Nur Entwürfe können bearbeitet werden")
        self._validiere_zeitraum(von, bis)
        self._pruefe_sperre(abrechnung.mitglied_id, abrechnung.abteilung_id, von)
        if self.db.ul_abrechnungen.has_overlap(
            abrechnung.mitglied_id, abrechnung.abteilung_id, von, bis, exclude_id=abrechnung.id
        ):
            raise ValueError("Zeitraum überschneidet sich mit einer bestehenden Abrechnung")
        abrechnung.zeitraum_von = von
        abrechnung.zeitraum_bis = bis
        # Lizenz nach Zeitraumänderung aus den Stammdaten neu ableiten (Snapshot beim Einreichen).
        abrechnung.lizenz_klassifikation = self.lizenz_fuer(abrechnung.mitglied_id, bis)
        abrechnung.version = expected_version
        return self.db.ul_abrechnungen.update_kopf(abrechnung, updated_by=updated_by)

    # --------------------------------------------------------------- Stunden
    def add_stunde(self, abrechnung: ULAbrechnung, *, datum: str, stunden: float,
                   angebot: Optional[str], bemerkung: Optional[str],
                   erstellt_von: str) -> ULStunde:
        if abrechnung.status != STATUS_ENTWURF:
            raise ValueError("Termine können nur im Entwurf erfasst werden")
        self._pruefe_termin(abrechnung, datum, stunden)
        d = _as_date(datum)
        s = ULStunde(
            abrechnung_id=abrechnung.id, datum=datum, stunden=float(stunden),
            wochentag=d.isoweekday(), angebot=(angebot or None), bemerkung=(bemerkung or None),
        )
        return self.db.ul_abrechnungen.add_stunde(s, created_by=erstellt_von)

    def update_stunde(self, abrechnung: ULAbrechnung, stunde: ULStunde, *, datum: str,
                      stunden: float, angebot: Optional[str], bemerkung: Optional[str],
                      updated_by: str) -> bool:
        if abrechnung.status != STATUS_ENTWURF:
            raise ValueError("Termine können nur im Entwurf bearbeitet werden")
        self._pruefe_termin(abrechnung, datum, stunden)
        d = _as_date(datum)
        stunde.datum = datum
        stunde.stunden = float(stunden)
        stunde.wochentag = d.isoweekday()
        stunde.angebot = (angebot or None)
        stunde.bemerkung = (bemerkung or None)
        return self.db.ul_abrechnungen.update_stunde(stunde, updated_by=updated_by)

    def _pruefe_termin(self, abrechnung: ULAbrechnung, datum: str, stunden: float) -> None:
        try:
            d = _as_date(datum)
        except (ValueError, TypeError):
            raise ValueError("Ungültiges Datum")
        if d < _as_date(abrechnung.zeitraum_von) or d > _as_date(abrechnung.zeitraum_bis):
            raise ValueError("Datum liegt außerhalb des Abrechnungszeitraums")
        if stunden is None or float(stunden) <= 0:
            raise ValueError("Stunden müssen größer als 0 sein")

    def add_serie(self, abrechnung: ULAbrechnung, *, wochentage, stunden: float,
                  angebot: Optional[str], bemerkung: Optional[str], erstellt_von: str) -> int:
        """Wochenplan: erzeugt für jeden gewählten Wochentag (1=Mo … 7=So) einen Termin
        an jedem passenden Tag im Abrechnungszeitraum. Liefert die Anzahl angelegter."""
        if abrechnung.status != STATUS_ENTWURF:
            raise ValueError("Termine können nur im Entwurf erfasst werden")
        try:
            wt = sorted({int(w) for w in (wochentage or [])})
        except (ValueError, TypeError):
            raise ValueError("Ungültige Wochentage")
        if not wt or any(w < 1 or w > 7 for w in wt):
            raise ValueError("Mindestens ein gültiger Wochentag (1–7) ist erforderlich")
        d, bis = _as_date(abrechnung.zeitraum_von), _as_date(abrechnung.zeitraum_bis)
        datums = []
        while d <= bis:
            if d.isoweekday() in wt:
                datums.append(d.isoformat())
            d += timedelta(days=1)
        return self._insert_termine(abrechnung, datums=datums, stunden=stunden,
                                    angebot=angebot, bemerkung=bemerkung, erstellt_von=erstellt_von)

    def add_tage(self, abrechnung: ULAbrechnung, *, datums, stunden: float,
                 angebot: Optional[str], bemerkung: Optional[str], erstellt_von: str) -> int:
        """Einzeltage (Kalender-Mehrfachauswahl): erzeugt für jeden ausgewählten Tag
        einen Termin mit denselben Stunden/Angebot (z. B. Spieltage). Liefert die
        Anzahl angelegter."""
        if abrechnung.status != STATUS_ENTWURF:
            raise ValueError("Termine können nur im Entwurf erfasst werden")
        norm = [(x or '')[:10] for x in (datums or []) if x]
        if not norm:
            raise ValueError("Mindestens ein Tag ist erforderlich")
        return self._insert_termine(abrechnung, datums=norm, stunden=stunden,
                                    angebot=angebot, bemerkung=bemerkung, erstellt_von=erstellt_von)

    def _insert_termine(self, abrechnung: ULAbrechnung, *, datums, stunden: float,
                        angebot: Optional[str], bemerkung: Optional[str],
                        erstellt_von: str) -> int:
        """Legt für eine Datumsliste je einen Termin an. Tage außerhalb des Zeitraums,
        ungültige Daten und bereits erfasste Tage werden übersprungen (idempotent),
        sodass Serie und Einzeltage sich nicht doppeln. Validierung der Eingabeform
        (Wochentage/Tage) liegt beim Aufrufer; hier nur Stunden + Bereich + Dedup."""
        if stunden is None or float(stunden) <= 0:
            raise ValueError("Stunden müssen größer als 0 sein")
        von, bis = _as_date(abrechnung.zeitraum_von), _as_date(abrechnung.zeitraum_bis)
        vorhanden = {s.datum[:10] for s in self.db.ul_abrechnungen.list_stunden(abrechnung.id)}
        angelegt = 0
        for iso in sorted(set(datums)):
            try:
                d = _as_date(iso)
            except (ValueError, TypeError):
                continue
            if d < von or d > bis or iso in vorhanden:
                continue
            self.db.ul_abrechnungen.add_stunde(
                ULStunde(abrechnung_id=abrechnung.id, datum=iso, stunden=float(stunden),
                         wochentag=d.isoweekday(), angebot=(angebot or None),
                         bemerkung=(bemerkung or None)),
                created_by=erstellt_von,
            )
            vorhanden.add(iso)
            angelegt += 1
        return angelegt

    # --------------------------------------------------------------- Vorlage
    def letzte_vorlage(self, mitglied_id: int, abteilung_id: int,
                       exclude_id: Optional[int] = None) -> list[dict]:
        """Wochenmuster der jüngsten vorhergehenden Abrechnung desselben ÜL/derselben
        Abteilung – als Vorschlag für die Serien-Erfassung. Termine werden nach
        (Stunden, Angebot) gruppiert; je Gruppe die belegten Wochentage. Absteigend
        nach Häufigkeit, damit das dominante Muster zuerst kommt. [] wenn es keine gibt."""
        src_id = self.db.ul_abrechnungen.letzte_vorlage_quelle_id(
            mitglied_id, abteilung_id, exclude_id=exclude_id)
        if not src_id:
            return []
        groups: dict[tuple, dict] = {}
        for s in self.db.ul_abrechnungen.list_stunden(src_id):
            key = (s.stunden, s.angebot or '')
            g = groups.setdefault(key, {'wochentage': set(), 'stunden': s.stunden,
                                        'angebot': s.angebot, 'anzahl': 0})
            if s.wochentag:
                g['wochentage'].add(s.wochentag)
            g['anzahl'] += 1
        out = [{'wochentage': sorted(g['wochentage']), 'stunden': g['stunden'],
                'angebot': g['angebot'], 'anzahl': g['anzahl']} for g in groups.values()]
        out.sort(key=lambda g: (-g['anzahl'], g['stunden']))
        return out

    # ------------------------------------------------------------- Workflow
    def einreichen(self, abrechnung: ULAbrechnung, *, eingereicht_von: str) -> ULAbrechnung:
        if abrechnung.status != STATUS_ENTWURF:
            raise ValueError("Nur Entwürfe können eingereicht werden")
        stunden = self.db.ul_abrechnungen.list_stunden(abrechnung.id)
        if not stunden:
            raise ValueError("Mindestens ein Termin muss erfasst sein")
        # Erneut prüfen: ein anderer Vorgang könnte den Zeitraum zwischenzeitlich gesperrt haben.
        self._pruefe_sperre(abrechnung.mitglied_id, abrechnung.abteilung_id, abrechnung.zeitraum_von)
        vereinbarung = self.db.ul_saetze.resolve(
            abrechnung.mitglied_id, abrechnung.abteilung_id, abrechnung.lizenz_klassifikation
        )
        # Lizenz-Beleg-Stammdaten beim Einreichen einfrieren (analog Satz): ein später am
        # Mitglied geänderter Lizenz-Nr/Qualifikation darf den eingereichten Beleg nicht
        # rückwirkend verändern.
        try:
            m = self.db.get_mitglied(abrechnung.mitglied_id)
        except (KeyError, AttributeError):
            m = None
        art = vereinbarung.verguetungsart if vereinbarung else VERGUETUNG_STUNDENSATZ
        # Die Monats-Abgrenzung hängt an den Nachbar-Abrechnungen und wird deshalb
        # hier entschieden und eingefroren – sonst verschöbe eine später eingereichte
        # Nachbarabrechnung rückwirkend den Betrag dieser hier.
        monate = (len(self.verguetungs_monate(abrechnung))
                  if art == VERGUETUNG_MONATSPAUSCHALE else None)
        ok = self.db.ul_abrechnungen.einreichen(
            abrechnung.id,
            verguetungsart=art,
            verguetung_pro_stunde=(vereinbarung.satz if vereinbarung else None),
            verguetung_monate=monate,
            eingereicht_von=eingereicht_von,
            trainerlizenz_nr=(m.trainerlizenz_nr if m else None),
            qualifikation=(m.qualifikation if m else None),
        )
        if not ok:
            raise ValueError("Einreichen fehlgeschlagen (Status geändert?)")
        return self.db.ul_abrechnungen.get(abrechnung.id)

    # --------------------------------------------------------------- Summen
    def summen(self, abrechnung: ULAbrechnung) -> dict:
        """Stunden-, Monats- und Betragsaggregate für Anzeige und Beleg.

        `verguetung_pro_stunde` trägt je nach `verguetungsart` €/h oder €/Monat —
        die Spalte behielt ihren Namen, weil sie den Snapshot des Satzwerts meint.
        Anzeige und Beleg beschriften sie anhand der Art.
        """
        stunden = self.db.ul_abrechnungen.list_stunden(abrechnung.id)
        total = round(sum(s.stunden for s in stunden), 2)
        im_zeitraum = monate_im_zeitraum(abrechnung.zeitraum_von, abrechnung.zeitraum_bis)

        # Eingereicht/bestätigt/abgelehnt rechnet aus dem eingefrorenen Snapshot, der
        # Entwurf aus der aktuell gültigen Vereinbarung. Maßstab ist der Status und nicht
        # mehr der Satzwert: Bei 'ohne_verguetung' bleibt der Betrag auch im Snapshot
        # leer, „kein Betrag" heißt hier also nicht „noch nicht eingefroren".
        eingefroren = abrechnung.status != STATUS_ENTWURF
        if eingefroren:
            art, satz = abrechnung.verguetungsart, abrechnung.verguetung_pro_stunde
            monate = abrechnung.verguetung_monate or 0
        else:
            art, satz, monate = VERGUETUNG_STUNDENSATZ, None, 0
        gesamt = berechne_betrag(art, satz, total, monate)

        # Vorschau: solange nichts eingefroren ist, die aktuell gültige Vereinbarung
        # auflösen, damit der ÜL die voraussichtliche Vergütung sieht – inklusive der
        # Monats-Abgrenzung, sonst verspräche die Vorschau einen schon vergebenen Monat.
        vorschau_satz = None
        vorschau_gesamt = None
        vorschau_art = None
        if not eingefroren:
            vereinbarung = self.db.ul_saetze.resolve(
                abrechnung.mitglied_id, abrechnung.abteilung_id,
                abrechnung.lizenz_klassifikation,
            )
            if vereinbarung is not None:
                art = vorschau_art = vereinbarung.verguetungsart
                vorschau_satz = vereinbarung.satz
                if art == VERGUETUNG_MONATSPAUSCHALE:
                    monate = len(self.verguetungs_monate(abrechnung))
                vorschau_gesamt = berechne_betrag(art, vorschau_satz, total, monate)

        monat: dict[str, float] = {}
        for s in stunden:
            key = s.datum[:7]  # YYYY-MM
            monat[key] = round(monat.get(key, 0.0) + s.stunden, 2)
        return {
            'summe_stunden': total,
            # anzahl_monate = tatsächlich vergütet, monate_im_zeitraum = berührt.
            # Differenz > 0 heißt: ein Monat läuft schon über eine andere Abrechnung
            # (Muster wie bei der anteiligen Beitrags-Vorschau).
            'anzahl_monate': monate,
            'monate_im_zeitraum': im_zeitraum,
            'verguetungsart': art,
            'verguetung_pro_stunde': satz,
            'gesamtbetrag': gesamt,
            'vorschau_verguetungsart': vorschau_art,
            'vorschau_pro_stunde': vorschau_satz,
            'vorschau_gesamtbetrag': vorschau_gesamt,
            'monatssummen': monat,
            'anzahl_termine': len(stunden),
        }

    # ----------------------------------------------------------------- Beleg
    def _klarname(self, username: Optional[str]) -> Optional[str]:
        """Login → Klarname des verknüpften Mitglieds; Fallback auf den Usernamen."""
        if not username:
            return None
        u = self.db.get_user_by_username(username)
        if u is not None:
            m = self.db.get_mitglied_by_user_id(u.id)
            if m is not None and (m.vorname or m.nachname):
                return f"{m.vorname or ''} {m.nachname or ''}".strip()
        return username

    def beleg_pdf(self, abrechnung: ULAbrechnung, *, verein: dict,
                  erstellt_von: str = '') -> bytes:
        """Stundennachweis-Beleg (PDF) zu einer Abrechnung.

        Geteilt zwischen dem Einzeldownload in der App und dem Fibu-Export, der den
        Beleg der exportierten Abrechnung beilegt – beide Wege müssen dasselbe Papier
        erzeugen.

        :param verein: {'name','strasse','plz_ort','registrier_nr'} für den Beleg-Kopf;
            kommt aus der Instanz-Konfiguration und wird deshalb hereingereicht.
        """
        try:
            m = self.db.get_mitglied(abrechnung.mitglied_id)
        except (KeyError, AttributeError):
            m = None
        # Eingereichte/bestätigte Belege aus dem beim Einreichen eingefrorenen Snapshot,
        # Entwürfe live aus dem Mitglied – ein fertiger Beleg ändert sich so nicht mehr
        # rückwirkend, wenn die Lizenz-Stammdaten später angepasst werden (#63).
        if abrechnung.status == STATUS_ENTWURF:
            lizenz_nr = m.trainerlizenz_nr if m else None
            qualifikation = m.qualifikation if m else None
        else:
            lizenz_nr = abrechnung.trainerlizenz_nr
            qualifikation = abrechnung.qualifikation
        name = f"{abrechnung.mitglied_vorname or ''} {abrechnung.mitglied_nachname or ''}"
        return erstelle_stundennachweis_pdf(
            verein=verein,
            ul_name=name.strip(),
            sportart=abrechnung.abteilung_name or '',
            iban=abrechnung.mitglied_iban,
            trainerlizenz_nr=lizenz_nr,
            qualifikation=qualifikation,
            lizenz_klassifikation=abrechnung.lizenz_klassifikation,
            foerder_klassifikation=abrechnung.foerder_klassifikation,
            zeitraum_von=abrechnung.zeitraum_von,
            zeitraum_bis=abrechnung.zeitraum_bis,
            termine=[asdict(s) for s in self.db.ul_abrechnungen.list_stunden(abrechnung.id)],
            summen=self.summen(abrechnung),
            erstellt_von=erstellt_von,
            eingereicht_von=self._klarname(abrechnung.eingereicht_von),
            eingereicht_am=abrechnung.eingereicht_am,
            bestaetigt_von=self._klarname(abrechnung.bestaetigt_von),
            bestaetigt_am=abrechnung.bestaetigt_am,
        )
