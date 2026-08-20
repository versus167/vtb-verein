/**
 * Zeitraum-Helfer für Zuordnungen (Abteilung/Funktion).
 *
 * Spiegel der Fachregeln aus `app/services/mitgliedschaft.py`: Ein Wechsel
 * schneidet eine laufende Zuordnung zum Stichtag, und der Stichtag ist immer ein
 * Monatserster. Die Oberfläche macht daraus eine Auswahl statt eines freien
 * Datumsfelds – so ist ein ungültiger Stichtag gar nicht erst eingebbar. Die
 * verbindliche Prüfung bleibt trotzdem im Backend (422).
 *
 * Alle Funktionen rechnen mit ISO-Datumstexten (YYYY-MM-DD) in *lokaler* Zeit;
 * `toISOString()` wird bewusst gemieden, weil es nach UTC schiebt und je nach
 * Uhrzeit einen Tag zurückspringt.
 */

function iso(jahr, monat, tag) {
  return `${jahr}-${String(monat + 1).padStart(2, '0')}-${String(tag).padStart(2, '0')}`
}

export function heuteIso() {
  const d = new Date()
  return iso(d.getFullYear(), d.getMonth(), d.getDate())
}

/** Erster des Monats, in dem `d` liegt – der vorgeschlagene Stichtag. */
export function monatsErster(d = new Date()) {
  return iso(d.getFullYear(), d.getMonth(), 1)
}

/** Der Tag davor – daran endet die bisherige Zeile. */
export function vortag(isoDatum) {
  if (!isoDatum) return null
  const [j, m, t] = isoDatum.slice(0, 10).split('-').map(Number)
  const d = new Date(j, m - 1, t - 1)
  return iso(d.getFullYear(), d.getMonth(), d.getDate())
}

const rein = (wert) => (wert || '').trim().slice(0, 10)

export function istBeendet(zeile, heute = heuteIso()) {
  const bis = rein(zeile?.bis)
  return !!bis && bis < heute
}

export function istKuenftig(zeile, heute = heuteIso()) {
  const von = rein(zeile?.von)
  return !!von && von > heute
}

export function istLaufend(zeile, heute = heuteIso()) {
  return !istBeendet(zeile, heute) && !istKuenftig(zeile, heute)
}

/** '2026-08-01' → '1. August 2026' */
const MONATE = ['Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 'Juli',
  'August', 'September', 'Oktober', 'November', 'Dezember']

export function datumLang(isoDatum) {
  const roh = rein(isoDatum)
  if (!roh) return ''
  const [j, m, t] = roh.split('-').map(Number)
  if (!j || !m || !t) return roh
  return `${t}. ${MONATE[m - 1]} ${j}`
}

/**
 * Wählbare Stichtage: Monatserste rund um heute, eingegrenzt auf das, was für
 * diese Zeile überhaupt ein Wechsel sein kann.
 *
 * - nach dem `von` der bisherigen Zeile (davor wäre es eine Korrektur),
 * - nicht hinter einem gesetzten `bis`,
 * - innerhalb der Vereinsmitgliedschaft (Eintritt/Austritt).
 *
 * Rückwirkende Stichtage sind ausdrücklich dabei: Sie sind erlaubt, verlangen
 * aber den Hinweis auf bereits abgerechnete Zeiträume.
 */
export function monatsErsteAuswahl({ von, bis, eintritt, austritt } = {},
                                   { zurueck = 18, vor = 6 } = {}) {
  const heute = new Date()
  const untergrenzen = [rein(von) && naechsterMonatsErster(rein(von)), rein(eintritt)].filter(Boolean)
  const obergrenzen = [rein(bis), rein(austritt)].filter(Boolean)
  const min = untergrenzen.length ? untergrenzen.sort().at(-1) : null
  const max = obergrenzen.length ? obergrenzen.sort()[0] : null

  const auswahl = []
  for (let i = -zurueck; i <= vor; i++) {
    const wert = monatsErster(new Date(heute.getFullYear(), heute.getMonth() + i, 1))
    if (min && wert < min) continue
    if (max && wert > max) continue
    auswahl.push({ label: datumLang(wert), value: wert })
  }
  return auswahl
}

/** Erster des Folgemonats – die früheste Stelle, an der ein Schnitt sitzen darf. */
function naechsterMonatsErster(isoDatum) {
  const [j, m] = isoDatum.split('-').map(Number)
  return monatsErster(new Date(j, m, 1))
}
