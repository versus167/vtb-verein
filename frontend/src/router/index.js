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
        path: 'mitglieder',
        name: 'mitglieder',
        component: () => import('pages/MitgliederPage.vue'),
        meta: { permission: 'personen.read' },
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
        meta: { permission: 'personen.read' },
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
