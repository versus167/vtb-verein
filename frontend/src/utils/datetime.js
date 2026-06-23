// Zentrale Datums-/Zeit-Formatierung fürs Frontend.
//
// Hintergrund: Das Backend speichert Zeitstempel als UTC (PostgreSQL-Session = UTC).
// Je nach Spaltentyp kommt der String mal Space-getrennt mit 2-stelligem Offset
// ("2026-06-23 09:12:34+00"), mal als ISO mit Offset an. formatDateTime() bringt ihn
// in eine browser-robuste ISO-Form und rendert in der lokalen Zeitzone (de-DE).
//
// Reine Datumsangaben (Geburtsdatum, Fälligkeit, …) NICHT durch formatDateTime() jagen,
// sondern formatDate() nutzen – die rechnet bewusst NICHT in Zeitzonen um, sonst würde
// ein reines Datum bei Zeitzonen-Offsets auf den Vortag/Folgetag kippen.

const DEFAULT_PLACEHOLDER = '–'

// Backend-Zeitstempel → Date (oder null bei leer/unparsbar).
function parseTimestamp(v) {
  if (!v) return null
  // "YYYY-MM-DD HH:MM:SS+00" → "YYYY-MM-DDTHH:MM:SS+00:00" (manche Browser parsen das
  // Space-Format / den 2-stelligen Offset sonst nicht).
  let s = String(v).trim().replace(' ', 'T')
  s = s.replace(/([+-]\d{2})$/, '$1:00')
  const d = new Date(s)
  return Number.isNaN(d.getTime()) ? null : d
}

// Zeitstempel (UTC) → lokale Datum-/Zeit-Anzeige, z. B. "23.06.2026, 11:12".
export function formatDateTime(v, { placeholder = DEFAULT_PLACEHOLDER } = {}) {
  const d = parseTimestamp(v)
  if (d) return d.toLocaleString('de-DE', { dateStyle: 'medium', timeStyle: 'short' })
  return v || placeholder
}

// Reine Datumsangabe "YYYY-MM-DD[…]" → "DD.MM.YYYY", ohne Zeitzonen-Umrechnung.
export function formatDate(v, { placeholder = DEFAULT_PLACEHOLDER } = {}) {
  if (!v) return placeholder
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(v))
  return m ? `${m[3]}.${m[2]}.${m[1]}` : v
}
