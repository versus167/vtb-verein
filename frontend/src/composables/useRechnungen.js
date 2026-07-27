// Geteilte Helfer für die Rechnungs-Seiten (Meine, Freigabe, Export).
// Farben bewusst semantisch (blue-grey/orange/positive/negative) – kein Fremd-Blau.

export const STATUS_CHIPS = {
  entwurf: { label: 'Entwurf', color: 'blue-grey' },
  eingereicht: { label: 'Eingereicht', color: 'orange' },
  freigegeben: { label: 'Freigegeben', color: 'positive' },
  abgelehnt: { label: 'Abgelehnt', color: 'negative' },
  // Schloss-Symbol, weil dieser Status als einziger sagt „hier geht nichts mehr":
  // ab dem Export liegt der Beleg in der Fibu.
  exportiert: { label: 'In Fibu exportiert', color: 'primary', icon: 'lock' },
}

export function statusChip(status) {
  return STATUS_CHIPS[status] || { label: status, color: 'grey' }
}

// „Exportiert" steht nicht in der status-Spalte, sondern folgt aus dem
// Export-Stempel – und schlägt die Freigabe, weil ab da nichts mehr geht.
export function anzeigeStatus(r) {
  return statusChip(r.ist_exportiert ? 'exportiert' : r.status)
}

export const STATUS_FILTER_OPTIONEN = [
  { label: 'Alle', value: '' },
  { label: 'Entwurf', value: 'entwurf' },
  { label: 'Eingereicht', value: 'eingereicht' },
  { label: 'Freigegeben', value: 'freigegeben' },
  { label: 'Abgelehnt', value: 'abgelehnt' },
  { label: 'In Fibu exportiert', value: 'exportiert' },
]

// Freigabe-Sicht: fremde Entwürfe liefert das Backend nicht aus, also auch
// keinen Filter anbieten, der garantiert leer bleibt.
export const FREIGABE_FILTER_OPTIONEN = STATUS_FILTER_OPTIONEN.filter(
  (o) => o.value !== 'entwurf',
)

// Die eine Entscheidung, die der Einreicher treffen muss: fließt das Geld
// zurück an ihn oder raus an den Aussteller? Name/IBAN des Ausstellers stehen
// auf dem Beleg und werden (noch) nicht erfasst.
//
// Die Geschäftsstelle erfasst auch für Mitglieder ohne App-Zugang – für sie
// heißt „Erstattung" darum nicht „an mich", das Mitglied wählt sie darunter.
export function baueEmpfaengerOptionen(fuerAndereMoeglich = false) {
  return [
    {
      label: fuerAndereMoeglich
        ? 'Erstattung an ein Mitglied'
        : 'Erstattung an mich (ich habe ausgelegt)',
      value: 'mitglied',
    },
    { label: 'Zahlung an den Rechnungsaussteller', value: 'extern' },
  ]
}

export function empfaengerText(r) {
  if (r.empfaenger_typ === 'mitglied') {
    return `Erstattung an ${r.empfaenger_mitglied_name || 'Einreicher'}`
  }
  if (r.empfaenger_typ === 'extern') {
    return r.empfaenger_name
      ? `Zahlung an ${r.empfaenger_name}`
      : 'Zahlung an den Rechnungsaussteller'
  }
  return 'Empfänger nicht angegeben'
}

// An der Rechnung gepflegte IBAN hat Vorrang; bei Erstattung greift sonst die
// aus dem Mitgliedsstamm (dieselbe Regel wie im Export).
export function empfaengerIban(r) {
  return (r.empfaenger_iban || '').trim() || (r.empfaenger_mitglied_iban || '')
}

// Cent → „12,50 €“; ohne Betrag bleibt die Anzeige leer (Betrag ist optional).
export function fmtBetrag(cent) {
  if (cent === null || cent === undefined) return ''
  return (cent / 100).toLocaleString('de-DE', { style: 'currency', currency: 'EUR' })
}

// „12,50“ → 1250. Akzeptiert Komma und Punkt; leer → null.
export function parseBetrag(text) {
  const roh = String(text ?? '').trim().replace(/\./g, '').replace(',', '.')
  if (!roh) return null
  const zahl = Number(roh)
  return Number.isFinite(zahl) ? Math.round(zahl * 100) : null
}

export function fmtDatum(wert) {
  if (!wert) return ''
  const iso = String(wert).slice(0, 10)
  const d = new Date(`${iso}T12:00`)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('de-DE')
}

export function fehlertext(e, fallback) {
  return e?.response?.data?.detail || fallback
}

// Beleg-Auswahl: identisch zu AnhangPanel, damit die vorgehaltene Auswahl im
// Einreich-Dialog dieselben Dateien akzeptiert wie der spätere Upload.
export const BELEG_ACCEPT = 'image/jpeg,image/png,image/gif,image/webp,application/pdf'
export const BELEG_MAX_MB = 10
export const BELEG_HINWEIS = `max. ${BELEG_MAX_MB} MB · JPEG, PNG, GIF, WebP, PDF`

export function belegFehler(datei) {
  if (!BELEG_ACCEPT.split(',').includes(datei.type)) {
    return `„${datei.name}“ hat ein nicht unterstütztes Format.`
  }
  if (datei.size > BELEG_MAX_MB * 1024 * 1024) {
    return `„${datei.name}“ ist größer als ${BELEG_MAX_MB} MB.`
  }
  return null
}
