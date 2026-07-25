// Geteilte Helfer für die Rechnungs-Seiten (Meine, Freigabe, Export).
// Farben bewusst semantisch (blue-grey/orange/positive/negative) – kein Fremd-Blau.

export const STATUS_CHIPS = {
  entwurf: { label: 'Entwurf', color: 'blue-grey' },
  eingereicht: { label: 'Eingereicht', color: 'orange' },
  freigegeben: { label: 'Freigegeben', color: 'positive' },
  abgelehnt: { label: 'Abgelehnt', color: 'negative' },
}

export function statusChip(status) {
  return STATUS_CHIPS[status] || { label: status, color: 'grey' }
}

export const STATUS_FILTER_OPTIONEN = [
  { label: 'Alle', value: '' },
  { label: 'Entwurf', value: 'entwurf' },
  { label: 'Eingereicht', value: 'eingereicht' },
  { label: 'Freigegeben', value: 'freigegeben' },
  { label: 'Abgelehnt', value: 'abgelehnt' },
]

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
