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
        meta: { title: 'Sonstiges', permission: ['system.config', 'fibu.export', 'system.protokoll'] },
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
        // Kein meta.permission: der Zugriff ist ACL-basiert (Kader-Zugehörigkeit
        // + Wart-ACL) wie bei den Terminen – die Seite/Backend setzen ihn je Team durch.
        path: 'teamtresor',
        name: 'teamtresor',
        component: () => import('pages/TeamtresorPage.vue'),
        meta: { title: 'Teamtresor' },
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

export default route(function () {
  return createRouter({
    scrollBehavior: () => ({ left: 0, top: 0 }),
    routes,
    history: createWebHistory(),
  })
})
