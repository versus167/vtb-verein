import { api } from 'src/boot/axios'

// base64url (VAPID applicationServerKey) → Uint8Array, wie von PushManager verlangt.
function urlBase64ToUint8Array (base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(base64)
  const output = new Uint8Array(raw.length)
  for (let i = 0; i < raw.length; ++i) output[i] = raw.charCodeAt(i)
  return output
}

/**
 * Web-Push-Verwaltung fürs aktuelle Gerät (Ticket #96).
 *
 * Kapselt Feature-Detection, das An-/Abmelden über den Service Worker und die
 * Synchronisation der Subscription mit dem Backend (/api/push/*).
 */
export function usePush () {
  const isSupported = () =>
    'serviceWorker' in navigator &&
    'PushManager' in window &&
    'Notification' in window

  async function currentSubscription () {
    if (!isSupported()) return null
    const reg = await navigator.serviceWorker.ready
    return reg.pushManager.getSubscription()
  }

  async function isSubscribed () {
    return !!(await currentSubscription())
  }

  /** Serverseitige VAPID-Konfiguration + ob dieser Nutzer schon ein Gerät hat. */
  async function serverStatus () {
    const { data } = await api.get('/api/push/vapid-key')
    return data // { publicKey, configured, subscribed }
  }

  /** Meldet das aktuelle Gerät für Push an. Wirft mit sprechender Meldung. */
  async function subscribe () {
    if (!isSupported()) {
      throw new Error('Push wird von diesem Browser/Gerät nicht unterstützt.')
    }
    const status = await serverStatus()
    if (!status.configured || !status.publicKey) {
      throw new Error('Push ist serverseitig (noch) nicht konfiguriert.')
    }
    const permission = await Notification.requestPermission()
    if (permission !== 'granted') {
      throw new Error('Benachrichtigungen wurden im Browser nicht erlaubt.')
    }
    const reg = await navigator.serviceWorker.ready
    let sub = await reg.pushManager.getSubscription()
    if (!sub) {
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(status.publicKey)
      })
    }
    const json = sub.toJSON()
    await api.post('/api/push/subscribe', { endpoint: sub.endpoint, keys: json.keys })
    return true
  }

  /** Meldet das aktuelle Gerät wieder ab (Backend-Revoke + lokale Subscription). */
  async function unsubscribe () {
    const sub = await currentSubscription()
    if (sub) {
      try {
        await api.post('/api/push/unsubscribe', { endpoint: sub.endpoint })
      } finally {
        await sub.unsubscribe()
      }
    }
    return true
  }

  return { isSupported, isSubscribed, serverStatus, subscribe, unsubscribe }
}
