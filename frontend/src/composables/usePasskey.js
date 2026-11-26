// Anmeldung per Passkey (Fingerabdruck/Face ID über WebAuthn).
//
// Das Handy prüft Finger/Gesicht (oder die Geräte-PIN) selbst und signiert damit
// eine Challenge des Servers – Biometrie verlässt das Gerät nie. Angeboten wird
// das nur am Handy: Der Server würde auch Laptops mit Windows Hello/Touch ID
// akzeptieren, die Oberfläche beschränkt sich aber bewusst aufs Handy.
//
// Der Passkey liegt im Schlüsselbund des Systems (iCloud/Google), nicht im
// Cookie-Speicher des Browsers. Deshalb gilt er im Browser UND in der installierten
// App – anders als der Login-Link, der am Handy im Browser aufgeht (#208).
import { Platform } from 'quasar'
import {
  browserSupportsWebAuthn,
  platformAuthenticatorIsAvailable,
  startAuthentication,
  startRegistration,
} from '@simplewebauthn/browser'
import { api } from 'src/boot/axios'

// Merker je Gerät: Hier wurde schon ein Passkey eingerichtet → auf der Login-Seite
// steht der Passkey-Knopf obenan. Nur Bequemlichkeit, keine Sicherheitsfunktion –
// fehlt der Speicher, steht der Knopf eben weiter unten.
const EINGERICHTET_KEY = 'vtb_passkey_eingerichtet'

export function passkeyHierEingerichtet () {
  try { return localStorage.getItem(EINGERICHTET_KEY) === '1' } catch { return false }
}

function merkeEingerichtet (ja) {
  try {
    if (ja) localStorage.setItem(EINGERICHTET_KEY, '1')
    else localStorage.removeItem(EINGERICHTET_KEY)
  } catch { /* egal */ }
}

// Nur am Handy und nur, wenn es einen eingebauten Sensor mit Biometrie/PIN gibt.
export async function passkeyMoeglich () {
  if (!Platform.is.mobile || !browserSupportsWebAuthn()) return false
  try {
    return await platformAuthenticatorIsAvailable()
  } catch {
    return false
  }
}

// Verständliche Meldung statt Browser-Fehlertext. `null` = abgebrochen, kein Hinweis nötig.
function meldung (err, fallback) {
  const name = err?.cause?.name || err?.name
  if (name === 'NotAllowedError' || name === 'AbortError' || err?.code === 'ERROR_CEREMONY_ABORTED') {
    return null
  }
  if (err?.code === 'ERROR_AUTHENTICATOR_PREVIOUSLY_REGISTERED') {
    return 'Dieses Handy ist schon eingerichtet.'
  }
  if (err?.code === 'ERROR_INVALID_DOMAIN' || err?.code === 'ERROR_INVALID_RP_ID') {
    return 'Passkeys sind für diese Adresse nicht eingerichtet. Bitte wende dich an den Vorstand.'
  }
  const detail = err?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail?.message) return detail.message
  return fallback
}

export class PasskeyFehler extends Error {
  constructor (text, code) {
    super(text || '')
    this.abgebrochen = text === null
    this.code = code
  }
}

export async function passkeyEinrichten (name) {
  try {
    const { data: optionsJSON } = await api.post('/api/auth/passkey/register/options')
    const credential = await startRegistration({ optionsJSON })
    const { data } = await api.post('/api/auth/passkey/register/verify', { credential, name: name || null })
    merkeEingerichtet(true)
    return data
  } catch (err) {
    throw new PasskeyFehler(
      meldung(err, 'Einrichten hat nicht geklappt.'),
      err?.response?.data?.detail?.code,
    )
  }
}

// Liefert die Login-Antwort (SessionUser) – übernommen wird sie im Auth-Store.
export async function passkeyAnmelden (remember) {
  try {
    const { data: optionsJSON } = await api.post('/api/auth/passkey/login/options')
    const credential = await startAuthentication({ optionsJSON })
    const { data } = await api.post('/api/auth/passkey/login/verify', { credential, remember })
    merkeEingerichtet(true)
    return data
  } catch (err) {
    // Passkey am Server entfernt, im Handy aber noch da → Merker zurücksetzen.
    if (err?.response?.status === 401) merkeEingerichtet(false)
    throw new PasskeyFehler(meldung(err, 'Anmeldung mit Fingerabdruck hat nicht geklappt.'))
  }
}
