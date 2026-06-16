// IBAN-Validierung nach ISO 13616 (Struktur) + ISO 7064 mod 97-10 (Prüfziffer).
// Spiegelt den Backend-Kern (vtb_verein/app/services/iban.py). Das Backend bleibt
// die verbindliche Instanz; diese Util liefert sofortiges Inline-Feedback im Formular.

// Offizielle IBAN-Längen je Land (SWIFT IBAN Registry, kompakt – SEPA + Nachbarn).
const IBAN_LENGTHS = {
  AD: 24, AE: 23, AL: 28, AT: 20, AZ: 28, BA: 20, BE: 16, BG: 22, BH: 22,
  BR: 29, BY: 28, CH: 21, CR: 22, CY: 28, CZ: 24, DE: 22, DK: 18, DO: 28,
  EE: 20, EG: 29, ES: 24, FI: 18, FO: 18, FR: 27, GB: 22, GE: 22, GI: 23,
  GL: 18, GR: 27, GT: 28, HR: 21, HU: 28, IE: 22, IL: 23, IS: 26, IT: 27,
  JO: 30, KW: 30, KZ: 20, LB: 28, LC: 32, LI: 21, LT: 20, LU: 20, LV: 21,
  MC: 27, MD: 24, ME: 22, MK: 19, MR: 27, MT: 31, MU: 30, NL: 18, NO: 15,
  PK: 24, PL: 28, PS: 29, PT: 25, QA: 29, RO: 24, RS: 22, SA: 24, SC: 31,
  SE: 24, SI: 19, SK: 24, SM: 27, TN: 24, TR: 26, UA: 29, VA: 22, VG: 24,
  XK: 20,
}

const IBAN_RE = /^[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}$/

// Whitespace entfernen, Großbuchstaben; leer → null.
export function normalizeIban (value) {
  if (value == null) return null
  const cleaned = String(value).replace(/\s+/g, '').toUpperCase()
  return cleaned || null
}

// ISO 7064 mod 97-10 über BigInt (IBANs sind länger als Number sicher abbildet).
function mod97 (iban) {
  const rearranged = iban.slice(4) + iban.slice(0, 4)
  let digits = ''
  for (const ch of rearranged) digits += parseInt(ch, 36).toString()
  return Number(BigInt(digits) % 97n)
}

export function isValidIban (value) {
  const iban = normalizeIban(value)
  if (iban == null) return false
  if (!IBAN_RE.test(iban)) return false
  if (iban.length < 15 || iban.length > 34) return false
  const expected = IBAN_LENGTHS[iban.slice(0, 2)]
  if (expected != null && iban.length !== expected) return false
  return mod97(iban) === 1
}

// Quasar-Rule: leer erlaubt (Feld optional), sonst gültige IBAN verlangen.
export const ibanRule = (v) => !v || isValidIban(v) || 'Ungültige IBAN – bitte Format und Prüfziffer prüfen.'
