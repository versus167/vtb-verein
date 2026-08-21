// Vergütungsarten der Übungsleiter-Abrechnung (#84) – geteilt zwischen Satz-Pflege,
// Erfassung und Bestätigung, damit ein Monatsfestbetrag überall gleich beschriftet ist.
//
// Die Erfassung selbst hängt NICHT an der Art: Stunden werden immer vollständig
// aufgezeichnet. Die Art bestimmt nur, wie (und ob) daraus ein Betrag wird.
const EURO = { style: 'currency', currency: 'EUR' }

export const VERGUETUNG_STUNDENSATZ = 'stundensatz'
export const VERGUETUNG_MONATSPAUSCHALE = 'monatspauschale'
export const VERGUETUNG_OHNE = 'ohne_verguetung'

export const verguetungsarten = [
  {
    value: VERGUETUNG_STUNDENSATZ,
    label: 'Stundensatz',
    beschreibung: 'Betrag = erfasste Stunden × Satz',
  },
  {
    value: VERGUETUNG_MONATSPAUSCHALE,
    label: 'Monatspauschale',
    beschreibung: 'Fester Betrag je angefangenem Monat; ein Monat wird nur einmal vergütet',
  },
  {
    value: VERGUETUNG_OHNE,
    label: 'Ohne Vergütung über die App',
    beschreibung: 'Nur Stundennachweis – Auszahlung läuft außerhalb (z. B. Honorarvertrag)',
  },
]

export function artLabel(art) {
  return verguetungsarten.find((a) => a.value === art)?.label || 'Stundensatz'
}

// Beschriftung des Satz-Eingabefelds bzw. der Einheit hinter dem Betrag.
export function einheit(art) {
  return art === VERGUETUNG_MONATSPAUSCHALE ? '/Monat' : '/h'
}

export function fmtEuro(v) {
  if (v == null) return ''
  return Number(v).toLocaleString('de-DE', EURO)
}

// Satzwert mit passender Einheit – bei 'ohne_verguetung' gibt es keinen.
export function fmtSatz(art, wert) {
  if (art === VERGUETUNG_OHNE) return 'ohne Vergütung'
  if (wert == null) return '–'
  return fmtEuro(wert) + einheit(art)
}

// Bemessung der Pauschale: „× 2 Mon." – und wenn ein Monat bereits über eine andere
// Abrechnung läuft, „× 1 von 2 Mon.", damit die gekürzte Summe erklärt ist.
function monatsTeil(art, summen) {
  if (art !== VERGUETUNG_MONATSPAUSCHALE) return ''
  const bezahlt = summen.anzahl_monate ?? 0
  const gesamt = summen.monate_im_zeitraum ?? bezahlt
  return bezahlt === gesamt ? ` × ${bezahlt} Mon.` : ` × ${bezahlt} von ${gesamt} Mon.`
}

// Zusammenfassungs-Zeile hinter den Gesamtstunden einer Abrechnung.
// Liefert { text, klasse } oder null, wenn nichts zu sagen ist.
export function verguetungsHinweis(summen, status) {
  if (!summen) return null
  const eingefroren = status !== 'entwurf'
  const art = summen.verguetungsart || VERGUETUNG_STUNDENSATZ
  if (art === VERGUETUNG_OHNE) {
    return { text: 'ohne Vergütung über die App', klasse: 'text-grey-7' }
  }
  if (summen.gesamtbetrag != null) {
    return {
      text: `${fmtEuro(summen.gesamtbetrag)} `
        + `(${fmtSatz(art, summen.verguetung_pro_stunde)}${monatsTeil(art, summen)})`,
      klasse: '',
    }
  }
  // Entwurf: Satz ist noch nicht eingefroren → voraussichtliche Vergütung.
  if (summen.vorschau_gesamtbetrag != null) {
    const vArt = summen.vorschau_verguetungsart || VERGUETUNG_STUNDENSATZ
    return {
      text: `voraussichtlich ${fmtEuro(summen.vorschau_gesamtbetrag)} `
        + `(${fmtSatz(vArt, summen.vorschau_pro_stunde)}${monatsTeil(vArt, summen)})`,
      klasse: 'text-grey-7',
    }
  }
  if (eingefroren) return { text: 'kein Vergütungssatz hinterlegt', klasse: 'text-orange' }
  return null
}
