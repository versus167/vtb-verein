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
        meta: { permission: 'mitglieder.read' },
      },
      {
        path: 'abteilungen',
        name: 'abteilungen',
        component: () => import('pages/AbteilungenPage.vue'),
        meta: { permission: 'abteilungen.read' },
      },
      {
        path: 'users',
        name: 'users',
        component: () => import('pages/UsersPage.vue'),
        meta: { permission: 'users.manage' },
      },
      {
        path: 'users/:id/permissions',
        name: 'user-permissions',
        component: () => import('pages/UserPermissionsPage.vue'),
        meta: { permission: 'users.manage' },
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
        meta: { adminOnly: true },
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
        meta: { permission: 'tickets.bereiche.verwalten' },
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
