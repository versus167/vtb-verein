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
      },
      {
        path: 'profile',
        name: 'profile',
        component: () => import('pages/ProfilePage.vue'),
      },
      {
        path: 'abteilungen',
        name: 'abteilungen',
        component: () => import('pages/AbteilungenPage.vue'),
        meta: { permission: 'abteilungen.read' },
      },
      {
        path: 'mannschaften',
        name: 'mannschaften',
        component: () => import('pages/MannschaftenPage.vue'),
        meta: { permission: 'mannschaften.read' },
      },
      {
        path: 'users',
        name: 'users',
        component: () => import('pages/UsersPage.vue'),
        meta: { permission: 'personen.permissions' },
      },
      {
        path: 'personen',
        name: 'personen',
        component: () => import('pages/PersonenPage.vue'),
        meta: { permission: 'personen.read' },
      },
      {
        path: 'users/:id/permissions',
        name: 'user-permissions',
        component: () => import('pages/UserPermissionsPage.vue'),
        meta: { permission: 'personen.read' },
      },
      {
        path: 'kassenbuch',
        name: 'kassenbuch',
        component: () => import('pages/KassenbuchPage.vue'),
      },
      {
        path: 'kassenbuch/:kasseId',
        name: 'kassenbuch-detail',
        component: () => import('pages/KassenbuchDetailPage.vue'),
      },
      {
        path: 'kassenverwaltung',
        name: 'kassenverwaltung',
        component: () => import('pages/KassenverwaltungPage.vue'),
        meta: { permission: 'kassen.verwalten' },
      },
      {
        path: 'beitraege',
        name: 'beitraege',
        component: () => import('pages/BeitragsverwaltungPage.vue'),
        meta: { permission: 'beitraege.read' },
      },
      {
        path: 'gebuehren',
        name: 'gebuehren',
        component: () => import('pages/GebuehrenPage.vue'),
        meta: { permission: 'gebuehren.read' },
      },
      {
        path: 'stundenerfassung',
        name: 'stundenerfassung',
        component: () => import('pages/UlStundenPage.vue'),
        meta: { permission: ['ulstunden.erfassen', 'ulstunden.erfassen_fremd'] },
      },
      {
        path: 'stunden-bestaetigung',
        name: 'stunden-bestaetigung',
        component: () => import('pages/UlBestaetigungPage.vue'),
        meta: { permission: 'ulstunden.bestaetigen' },
      },
      {
        path: 'verguetungssaetze',
        name: 'ul-saetze',
        component: () => import('pages/UlSaetzePage.vue'),
        meta: { permission: 'ulstunden.verwalten' },
      },
      {
        path: 'fibu-export',
        name: 'fibu-export',
        component: () => import('pages/FibuExportPage.vue'),
        meta: { permission: 'fibu.export' },
      },
      {
        path: 'berichte',
        name: 'berichte',
        component: () => import('pages/BerichtePage.vue'),
        meta: { permission: 'berichte.read' },
      },
      {
        path: 'protokoll',
        name: 'protokoll',
        component: () => import('pages/ProtokollPage.vue'),
        meta: { permission: 'system.protokoll' },
      },
      {
        path: 'tickets',
        name: 'tickets',
        component: () => import('pages/TicketsPage.vue'),
      },
      {
        path: 'ticket-verwaltung',
        name: 'ticket-verwaltung',
        component: () => import('pages/TicketVerwaltungPage.vue'),
        meta: { permission: 'tickets.bereiche_verwalten' },
      },
      {
        path: 'einstellungen',
        name: 'einstellungen',
        component: () => import('pages/EinstellungenPage.vue'),
        meta: { permission: 'funktionen.verwalten' },
      },
      {
        path: 'datenbereinigung',
        name: 'prune',
        component: () => import('pages/PrunePage.vue'),
        meta: { permission: 'system.config' },
      },
      {
        path: 'schliessanlage',
        name: 'schliessanlage',
        component: () => import('pages/SchliessanlagePage.vue'),
        meta: { permission: 'schliessanlage.read' },
      },
      {
        path: 'import',
        name: 'import',
        component: () => import('pages/ImportPage.vue'),
        meta: { adminOnly: true },
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
