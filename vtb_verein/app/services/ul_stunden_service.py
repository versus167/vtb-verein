"""Service für die Übungsleiter-Stundenerfassung.

Kapselt die Domänenlogik: Zeitraum-Validierung, Sperr-Wasserzeichen (nach
Einreichen/Bestätigen ist der Zeitraum bis zum letzten Tag gesperrt),
Satz-Auflösung beim Einreichen (Snapshot) sowie Summen/Monatsaggregate für
Anzeige und Beleg. Berechtigungs-/Eigentümer-Prüfungen liegen im API-Router.

Validierungsfehler werden als ValueError geworfen; der Router bildet sie auf
HTTP 400 ab (Muster GebuehrenService).
"""
from datetime import date, timedelta
from typing import Optional

from app.models.ul_stunden import (
    ULAbrechnung, ULStunde, LIZENZ_KLASSIFIKATIONEN, STATUS_ENTWURF,
)


def _as_date(s: str) -> date:
    return date.fromisoformat(s[:10])


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

    # ----------------------------------------------------------- Kopf / CRUD
    def create_abrechnung(self, *, mitglied_id: int, abteilung_id: int, von: str, bis: str,
                          lizenz_klassifikation: str, foerder_klassifikation: Optional[str],
                          erstellt_von: str) -> ULAbrechnung:
        self._validiere_zeitraum(von, bis)
        if lizenz_klassifikation not in LIZENZ_KLASSIFIKATIONEN:
            raise ValueError("Ungültige Lizenz-Klassifikation")
        self._pruefe_sperre(mitglied_id, abteilung_id, von)
        if self.db.ul_abrechnungen.has_overlap(mitglied_id, abteilung_id, von, bis):
            raise ValueError("Zeitraum überschneidet sich mit einer bestehenden Abrechnung")
        a = ULAbrechnung(
            mitglied_id=mitglied_id, abteilung_id=abteilung_id,
            zeitraum_von=von, zeitraum_bis=bis,
            lizenz_klassifikation=lizenz_klassifikation,
            foerder_klassifikation=(foerder_klassifikation or None),
        )
        return self.db.ul_abrechnungen.create(a, created_by=erstellt_von)

    def update_kopf(self, abrechnung: ULAbrechnung, *, von: str, bis: str,
                    lizenz_klassifikation: str, foerder_klassifikation: Optional[str],
                    expected_version: int, updated_by: str) -> bool:
        if abrechnung.status != STATUS_ENTWURF:
            raise ValueError("Nur Entwürfe können bearbeitet werden")
        self._validiere_zeitraum(von, bis)
        if lizenz_klassifikation not in LIZENZ_KLASSIFIKATIONEN:
            raise ValueError("Ungültige Lizenz-Klassifikation")
        self._pruefe_sperre(abrechnung.mitglied_id, abrechnung.abteilung_id, von)
        if self.db.ul_abrechnungen.has_overlap(
            abrechnung.mitglied_id, abrechnung.abteilung_id, von, bis, exclude_id=abrechnung.id
        ):
            raise ValueError("Zeitraum überschneidet sich mit einer bestehenden Abrechnung")
        abrechnung.zeitraum_von = von
        abrechnung.zeitraum_bis = bis
        abrechnung.lizenz_klassifikation = lizenz_klassifikation
        abrechnung.foerder_klassifikation = (foerder_klassifikation or None)
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

    # ------------------------------------------------------------- Workflow
    def einreichen(self, abrechnung: ULAbrechnung, *, eingereicht_von: str) -> ULAbrechnung:
        if abrechnung.status != STATUS_ENTWURF:
            raise ValueError("Nur Entwürfe können eingereicht werden")
        stunden = self.db.ul_abrechnungen.list_stunden(abrechnung.id)
        if not stunden:
            raise ValueError("Mindestens ein Termin muss erfasst sein")
        # Erneut prüfen: ein anderer Vorgang könnte den Zeitraum zwischenzeitlich gesperrt haben.
        self._pruefe_sperre(abrechnung.mitglied_id, abrechnung.abteilung_id, abrechnung.zeitraum_von)
        satz = self.db.ul_saetze.resolve(
            abrechnung.mitglied_id, abrechnung.abteilung_id, abrechnung.lizenz_klassifikation
        )
        ok = self.db.ul_abrechnungen.einreichen(
            abrechnung.id, verguetung_pro_stunde=satz, eingereicht_von=eingereicht_von
        )
        if not ok:
            raise ValueError("Einreichen fehlgeschlagen (Status geändert?)")
        return self.db.ul_abrechnungen.get(abrechnung.id)

    # --------------------------------------------------------------- Summen
    def summen(self, abrechnung: ULAbrechnung) -> dict:
        stunden = self.db.ul_abrechnungen.list_stunden(abrechnung.id)
        total = round(sum(s.stunden for s in stunden), 2)
        satz = abrechnung.verguetung_pro_stunde
        gesamt = round(total * satz, 2) if satz is not None else None
        monat: dict[str, float] = {}
        for s in stunden:
            key = s.datum[:7]  # YYYY-MM
            monat[key] = round(monat.get(key, 0.0) + s.stunden, 2)
        return {
            'summe_stunden': total,
            'verguetung_pro_stunde': satz,
            'gesamtbetrag': gesamt,
            'monatssummen': monat,
            'anzahl_termine': len(stunden),
        }
