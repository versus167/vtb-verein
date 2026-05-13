import { route } from 'quasar/wrappers'
import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('pages/LoginPage.vue'),
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
