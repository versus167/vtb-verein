/*
 * This file (which will be your service worker)
 * is picked up by the build system ONLY if
 * quasar.config file > pwa > workboxMode is set to "InjectManifest"
 */

import { clientsClaim } from 'workbox-core'
import { precacheAndRoute, cleanupOutdatedCaches, createHandlerBoundToURL } from 'workbox-precaching'
import { registerRoute, NavigationRoute } from 'workbox-routing'

self.skipWaiting()
clientsClaim()

// Use with precache injection
precacheAndRoute(self.__WB_MANIFEST)

cleanupOutdatedCaches()

// Non-SSR fallbacks to index.html
// Production SSR fallbacks to offline.html (except for dev)
//
// ACHTUNG bei der denylist: NavigationRoute fängt JEDE Navigation ab, und eine
// iframe-Navigation ist eine. Alles, was hier nicht ausgenommen ist, bekommt
// die precachte index.html — samt der Header, mit denen sie im Cache liegt.
//
// Genau daran ist der Beleg-Scanner (#197) gescheitert: Er ist eine
// eigenständige Seite unter public/ und keine SPA-Route. Die App bettet ihn in
// einem iframe ein, der Fallback beantwortete diese Navigation mit index.html,
// und deren `frame-ancestors 'none'` / `X-Frame-Options: DENY` ließen Chrome
// den Rahmen blockieren — der Nutzer sah nur eine leere Fehlerseite.
//
// Unsichtbar war das, weil es nur im gebauten PROD-Stand mit registriertem
// Service Worker auftritt: Im Dev-Build greift der Block hier gar nicht, und
// jeder Abruf mit curl geht am Service Worker vorbei und liefert die richtige
// Datei mit den richtigen Headern.
//
// Das Muster steht bewusst ohne `$`: NavigationRoute prüft die denylist gegen
// `pathname + search`, und die App hängt ein `?v=<Version>` an die Adresse.
const NICHT_UEBER_DIE_SPA = [
  new RegExp(process.env.PWA_SERVICE_WORKER_REGEX),
  /workbox-(.)*\.js$/,
  /^\/beleg-scanner\.html/,
]

if (process.env.PROD) {
  registerRoute(
    new NavigationRoute(
      createHandlerBoundToURL(process.env.PWA_FALLBACK_HTML),
      { denylist: NICHT_UEBER_DIE_SPA }
    )
  )
}

// --- Zahl am App-Symbol (Ticket #133) --------------------------------------
// Eine geschlossene PWA rechnet nichts – nur der Service Worker kann das Badge
// setzen, und der läuft nur, wenn ihn eine Push-Nachricht aufweckt.
//
// Die Zahl steht bewusst NICHT im Push-Payload, sondern wird hier frisch
// geholt: so stimmt sie auch dann, wenn mehrere Nachrichten aufgelaufen sind
// oder jemand anderes die Aufgabe zwischenzeitlich erledigt hat. Ein fetch()
// aus dem Service Worker heraus löst dessen eigenen fetch-Handler nicht aus,
// geht also direkt ans Netz.
//
// Best effort: Firefox kennt die API nicht, ohne Netz oder mit abgelaufener
// Session bleibt die alte Zahl stehen. Beim nächsten Öffnen der App korrigiert
// der Aufgaben-Store sie ohnehin.
async function aktualisiereAppBadge() {
  if (!('setAppBadge' in self.navigator)) return
  try {
    const antwort = await fetch('/api/aufgaben/offen', { credentials: 'include' })
    if (!antwort.ok) return
    const { gesamt } = await antwort.json()
    await (gesamt > 0 ? self.navigator.setAppBadge(gesamt) : self.navigator.clearAppBadge())
  } catch (e) {
    /* offline oder nicht (mehr) angemeldet – Badge unverändert lassen */
  }
}

// --- Web-Push (Ticket #96) -------------------------------------------------
// Eingehende Push-Nachricht anzeigen. Payload: { title, body, url }.
self.addEventListener('push', (event) => {
  let payload = {}
  try {
    payload = event.data ? event.data.json() : {}
  } catch (e) {
    payload = { body: event.data ? event.data.text() : '' }
  }
  const title = payload.title || 'VTB Vereinsverwaltung'
  const options = {
    body: payload.body || '',
    icon: 'icons/icon-192x192.png',
    badge: 'icons/favicon-128x128.png',
    data: { url: payload.url || '/' },
    tag: payload.tag || undefined
  }
  // Benachrichtigung und Badge zusammen – die Zahl am Symbol soll auch dann
  // stimmen, wenn die Meldung selbst weggewischt wird.
  event.waitUntil(Promise.all([
    self.registration.showNotification(title, options),
    aktualisiereAppBadge(),
  ]))
})

// Klick auf die Notification: bestehendes App-Fenster fokussieren oder öffnen.
self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const targetUrl = (event.notification.data && event.notification.data.url) || '/'
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if ('focus' in client) {
          if ('navigate' in client) client.navigate(targetUrl)
          return client.focus()
        }
      }
      if (self.clients.openWindow) return self.clients.openWindow(targetUrl)
    })
  )
})
