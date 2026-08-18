// Prüfung des Aufbaus einer E-Mail-Adresse (nicht der Erreichbarkeit).
// Spiegelt den Backend-Kern (vtb_verein/app/services/mailadresse.py) inklusive der
// Meldungstexte. Das Backend bleibt die verbindliche Instanz; diese Util liefert
// sofortiges Inline-Feedback im Formular – so wie utils/iban.js für die IBAN.

// Obergrenzen nach RFC 5321.
export const MAX_LAENGE = 254
export const MAX_LOKALTEIL = 64

const LOKALTEIL_RE = /^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*$/
const LABEL_RE = /^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$/
const TLD_RE = /^[A-Za-z]{2,}$/

// Außenliegenden Whitespace entfernen; leer → null. Die Groß-/Kleinschreibung
// bleibt stehen (siehe Backend: der Bestand wird so verglichen, wie er gespeichert ist).
export function normalizeMailadresse (value) {
  if (value == null) return null
  const cleaned = String(value).trim()
  return cleaned || null
}

// Fehlerursache als Klartext – oder null, wenn der Aufbau passt.
export function pruefeMailadresse (adresse) {
  if (/\s/.test(adresse)) return 'E-Mail-Adresse darf keine Leerzeichen enthalten.'
  if (adresse.length > MAX_LAENGE) {
    return `E-Mail-Adresse ist zu lang (höchstens ${MAX_LAENGE} Zeichen).`
  }
  if ((adresse.match(/@/g) || []).length !== 1) {
    return 'E-Mail-Adresse braucht genau ein @ (z. B. name@verein.de).'
  }
  const [lokal, domain] = adresse.split('@')
  if (!lokal) return 'Vor dem @ fehlt der Name (z. B. name@verein.de).'
  if (lokal.length > MAX_LOKALTEIL) {
    return `Der Teil vor dem @ ist zu lang (höchstens ${MAX_LOKALTEIL} Zeichen).`
  }
  if (!LOKALTEIL_RE.test(lokal)) return 'Der Teil vor dem @ enthält unzulässige Zeichen.'
  if (!domain) return 'Nach dem @ fehlt die Domain (z. B. name@verein.de).'
  const labels = domain.split('.')
  if (labels.length < 2) return 'Nach dem @ fehlt die Endung (z. B. @verein.de statt @verein).'
  if (labels.some((teil) => !LABEL_RE.test(teil))) {
    return 'Die Domain nach dem @ ist nicht gültig (z. B. name@verein.de).'
  }
  if (!TLD_RE.test(labels[labels.length - 1])) {
    return 'Die Endung nach dem letzten Punkt muss aus mindestens zwei Buchstaben bestehen.'
  }
  return null
}

export function istMailadresse (value) {
  const adresse = normalizeMailadresse(value)
  return adresse != null && pruefeMailadresse(adresse) == null
}

// Quasar-Rule für optionale Felder: leer ist in Ordnung (Konto ohne Zugang),
// eine ausgefüllte Adresse muss aber stimmen.
export function mailRule (value) {
  const adresse = normalizeMailadresse(value)
  if (adresse == null) return true
  return pruefeMailadresse(adresse) || true
}

// Quasar-Rule für Pflichtfelder (Login-Adresse, Freischaltung).
export function mailRulePflicht (value) {
  const adresse = normalizeMailadresse(value)
  if (adresse == null) return 'E-Mail-Adresse ist erforderlich.'
  return pruefeMailadresse(adresse) || true
}
