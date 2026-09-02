import { route } from 'quasar/wrappers'
import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('pages/LoginPage.vue'),
  },
  {
    path: '/auth/magic-link',
    name: 'magic-link',
    component: () => import('pages/MagicLinkPage.vue'),
  },
  {
    path: '/',
    component: () => import('layouts/MainLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      {
        path: '',
        name: 'dashboard',
        component: () => import('pages/DashboardPage.vue'),
        meta: { title: 'Übersicht' },
      },
      {
        path: 'profile',
        name: 'profile',
        component: () => import('pages/ProfilePage.vue'),
        meta: { title: 'Mein Profil' },
      },
      {
        path: 'abteilungen',
        name: 'abteilungen',
        component: () => import('pages/AbteilungenPage.vue'),
        meta: { title: 'Abteilungen', permission: 'abteilungen.read' },
      },
      {
        path: 'mannschaften',
        name: 'mannschaften',
        component: () => import('pages/MannschaftenPage.vue'),
        // ACL-basiert (wie tresor/kassenbuch): kein meta.permission, sonst
        // wirft der Guard Kader-ÜL/Betreuer ohne globales mannschaften.read
        // aufs Dashboard zurück (#124). Zugriff regeln Nav-Probe + Backend-Filter.
        meta: { title: 'Mannschaften' },
      },
      {
        path: 'users',
        name: 'users',
        component: () => import('pages/UsersPage.vue'),
        meta: { title: 'Benutzer', permission: 'personen.permissions' },
      },
      {
        path: 'personen',
        name: 'personen',
        component: () => import('pages/PersonenPage.vue'),
        meta: { title: 'Personen', permission: 'personen.read' },
      },
      {
        // Eigene Seite statt Tab in PersonenPage: die hängt komplett hinter
        // personen.read, Freischalter sollen aber gerade keine Stammdaten sehen.
        // ODER-Array – personen.permissions ist Obermenge (durfte das schon immer).
        path: 'zugaenge',
        name: 'zugaenge',
        component: () => import('pages/ZugaengePage.vue'),
        meta: {
          title: 'Zugänge',
          permission: ['personen.freischalten', 'personen.permissions'],
        },
      },
      {
        path: 'users/:id/permissions',
        name: 'user-permissions',
        component: () => import('pages/UserPermissionsPage.vue'),
        meta: { title: 'Berechtigungen', permission: 'personen.read' },
      },
      {
        path: 'kassenbuch',
        name: 'kassenbuch',
        component: () => import('pages/KassenbuchPage.vue'),
        meta: { title: 'Kassenbuch' },
      },
      {
        path: 'kassenbuch/:kasseId',
        name: 'kassenbuch-detail',
        component: () => import('pages/KassenbuchDetailPage.vue'),
        meta: { title: 'Kassenbuch' },
      },
      {
        path: 'kassenverwaltung',
        name: 'kassenverwaltung',
        component: () => import('pages/KassenverwaltungPage.vue'),
        meta: { title: 'Kassenverwaltung', permission: 'kassen.verwalten' },
      },
      {
        path: 'beitraege',
        name: 'beitraege',
        component: () => import('pages/BeitragsverwaltungPage.vue'),
        meta: { title: 'Beiträge', permission: 'beitraege.read' },
      },
      {
        path: 'gebuehren',
        name: 'gebuehren',
        component: () => import('pages/GebuehrenPage.vue'),
        meta: { title: 'Gebühren', permission: 'gebuehren.read' },
      },
      {
        path: 'uebungsleiter',
        name: 'uebungsleiter',
        component: () => import('pages/UebungsleiterPage.vue'),
        meta: {
          title: 'Übungsleiter',
          permission: [
            'ulstunden.erfassen',
            'ulstunden.erfassen_fremd',
            'ulstunden.bestaetigen',
            'ulstunden.verwalten',
          ],
        },
      },
      {
        // ODER-Array: `permissions` ist die lenient Key-Menge, enthält also auch
        // rein abteilungs-scoped geerbte Rechte (Abteilungsleiter → freigeben).
        path: 'rechnungen',
        name: 'rechnungen',
        component: () => import('pages/RechnungenPage.vue'),
        meta: {
          title: 'Rechnungen',
          permission: [
            'rechnungen.einreichen',
            'rechnungen.freigeben',
            'rechnungen.verwalten',
          ],
        },
      },
      {
        path: 'fibu-export',
        name: 'fibu-export',
        component: () => import('pages/FibuExportPage.vue'),
        meta: { title: 'Fibu-Export', permission: 'fibu.export' },
      },
      {
        path: 'berichte',
        name: 'berichte',
        component: () => import('pages/BerichtePage.vue'),
        meta: { title: 'Berichte', permission: 'berichte.read' },
      },
      {
        path: 'protokoll',
        name: 'protokoll',
        component: () => import('pages/ProtokollPage.vue'),
        meta: { title: 'Protokoll', permission: 'system.protokoll' },
      },
      {
        path: 'tickets',
        name: 'tickets',
        component: () => import('pages/TicketsPage.vue'),
        meta: { title: 'Tickets' },
      },
      {
        path: 'ticket-verwaltung',
        name: 'ticket-verwaltung',
        component: () => import('pages/TicketVerwaltungPage.vue'),
        meta: { title: 'Ticket-Verwaltung', permission: 'tickets.bereiche_verwalten' },
      },
      {
        path: 'einstellungen',
        name: 'einstellungen',
        component: () => import('pages/EinstellungenAllgemeinPage.vue'),
        meta: { title: 'Einstellungen', permission: ['funktionen.verwalten', 'abteilungen.read'] },
      },
      {
        path: 'sonstiges',
        name: 'sonstiges',
        component: () => import('pages/EinstellungenSonstigesPage.vue'),
        // Import ist adminOnly → Admins umgehen den Guard ohnehin
        meta: { title: 'Sonstiges',
                permission: ['system.config', 'fibu.export', 'system.protokoll',
                             'termine.verwalten', 'spielstaetten.verwalten'] },
      },
      {
        path: 'spielplan-import',
        name: 'spielplan-import',
        component: () => import('pages/SpielplanImportPage.vue'),
        meta: { title: 'Spielplan-Import', permission: 'termine.verwalten' },
      },
      {
        path: 'spielstaetten',
        name: 'spielstaetten',
        component: () => import('pages/SpielstaettenPage.vue'),
        // ODER-Array: `system.config` bleibt als Obermenge gültig (siehe
        // backend/api/spielstaetten.py::_require_verwalten).
        meta: { title: 'Spielstätten',
                permission: ['spielstaetten.verwalten', 'system.config'] },
      },
      {
        path: 'funktionen',
        name: 'funktionen',
        component: () => import('pages/FunktionenPage.vue'),
        meta: { title: 'Funktionen', permission: 'funktionen.verwalten' },
      },
      {
        path: 'datenbereinigung',
        name: 'prune',
        component: () => import('pages/PrunePage.vue'),
        meta: { title: 'Datenbereinigung', permission: 'system.config' },
      },
      {
        path: 'konsistenz',
        name: 'konsistenz',
        component: () => import('pages/KonsistenzPage.vue'),
        meta: { title: 'Konsistenz', adminOnly: true },
      },
      {
        path: 'schliessanlage',
        name: 'schliessanlage',
        component: () => import('pages/SchliessanlagePage.vue'),
        meta: { title: 'Schließanlage', permission: 'schliessanlage.read' },
      },
      {
        // Kein meta.permission: der Zugriff ist ACL-basiert (tresor_freigabe) wie
        // beim Kassenbuch – die Seite/Backend setzen ihn je Tresor durch.
        path: 'tresor',
        name: 'tresor',
        component: () => import('pages/TresorPage.vue'),
        meta: { title: 'Passwörter/Kontakte' },
      },
      {
        // Kein meta.permission: der Zugriff ist ACL-basiert (Kader-Zugehörigkeit)
        // wie bei Kassenbuch/Tresor – die Seite/Backend setzen ihn je Mannschaft durch.
        path: 'termine',
        name: 'termine',
        component: () => import('pages/TerminePage.vue'),
        meta: { title: 'Termine' },
      },
      {
        path: 'platzbelegung',
        name: 'platzbelegung',
        component: () => import('pages/PlatzbelegungPage.vue'),
        // ODER-Liste: `spielstaetten.belegung` ist das gemeinte Recht, die beiden
        // anderen schließen es ein (backend/api/spielstaetten.py::_require_belegung).
        meta: { title: 'Platzbelegung',
                permission: ['spielstaetten.belegung', 'spielstaetten.verwalten',
                             'termine.verwalten'] },
      },
      {
        // Kein meta.permission: der Zugriff ist ACL-basiert (Kader-Zugehörigkeit
        // + Wart-ACL) wie bei den Terminen – die Seite/Backend setzen ihn je Team durch.
        path: 'teamkasse',
        // Alter Pfad aus der Zeit als „Teamtresor" – gesetzte Lesezeichen sollen
        // nicht ins Leere laufen.
        alias: 'teamtresor',
        name: 'teamkasse',
        component: () => import('pages/TeamkassePage.vue'),
        meta: { title: 'Teamkasse' },
      },
      {
        path: 'import',
        name: 'import',
        component: () => import('pages/ImportPage.vue'),
        meta: { title: 'Import', adminOnly: true },
      },
    ],
  },
  {
    path: '/:catchAll(.*)*',
    component: () => import('pages/ErrorNotFound.vue'),
  },
]

// ── Seiten-Chunk nicht ladbar (#157) ────────────────────────────────────────
//
// Die Seiten oben werden einzeln nachgeladen (`() => import(...)`). Schlägt das
// fehl, bricht vue-router die Navigation ab und verwirft die push()-Promise —
// für den Nutzer passiert schlicht NICHTS. Genau das war der Login, der „hängen
// bleibt": Die Anmeldung lief durch (F5 führte sofort in die App), nur Layout-
// und Dashboard-Chunk kamen nicht an.
//
// Zwei Lagen führen dahin, beide selten und darum kaum reproduzierbar:
//   * Erster Besuch auf einem Gerät — der Service Worker installiert sich und
//     übernimmt die schon geladene Seite (skipWaiting + clientsClaim), während
//     sein Precache noch gefüllt wird.
//   * Ein Deploy zwischen Seitenaufruf und Klick: Die index.html im Browser
//     zeigt auf Chunk-Namen mit altem Hash, die es im neuen Build nicht gibt.
//
// Beides heilt ein vollständiger Seitenaufruf — dasselbe, was Nutzer heute per
// F5 von Hand tun. Also hart auf das Ziel navigieren statt still zu scheitern.
// Die Meldungen der Browser unterscheiden sich im Wortlaut („Failed to fetch…"
// in Chrome, „error loading…" in Firefox, „Importing a module script failed."
// in Safari), teilen sich aber den Kern.
const NACHLADEFEHLER = /dynamically imported module|Importing a module script failed|ChunkLoadError|Loading chunk/i
const marke = (pfad) => `vtb_nachladen:${pfad}`

export default route(function () {
  const router = createRouter({
    scrollBehavior: () => ({ left: 0, top: 0 }),
    routes,
    history: createWebHistory(),
  })

  router.onError((fehler, to) => {
    if (!NACHLADEFEHLER.test(fehler?.message ?? '')) return
    // Höchstens ein Versuch je Ziel: Fehlt die Datei wirklich (kaputter Build),
    // soll sich die Seite nicht in einer Schleife neu laden.
    if (sessionStorage.getItem(marke(to.fullPath))) return
    sessionStorage.setItem(marke(to.fullPath), '1')
    window.location.assign(to.fullPath)
  })

  // Kam die Seite an, ist die Sperre verbraucht — ein späterer Fehlschlag auf
  // derselben Route (nächster Deploy) darf wieder neu laden.
  router.afterEach((to) => {
    sessionStorage.removeItem(marke(to.fullPath))
  })

  return router
})
