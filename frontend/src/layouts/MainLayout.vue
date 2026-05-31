<template>
  <q-layout view="lHh Lpr lFf">
    <q-header elevated>
      <q-toolbar>
        <q-btn flat dense round icon="menu" @click="drawer = !drawer" />
        <q-toolbar-title>Vereinsverwaltung</q-toolbar-title>
        <q-btn flat dense round icon="account_circle">
          <q-menu>
            <q-list style="min-width: 160px">
              <q-item>
                <q-item-section>
                  <q-item-label class="text-weight-bold">{{ auth.user?.username }}</q-item-label>
                  <q-item-label caption>{{ auth.user?.role }}</q-item-label>
                </q-item-section>
              </q-item>
              <q-separator />
              <q-item clickable v-close-popup :to="{ name: 'profile' }">
                <q-item-section avatar><q-icon name="person" /></q-item-section>
                <q-item-section>Mein Profil</q-item-section>
              </q-item>
              <q-item clickable v-close-popup @click="onLogout">
                <q-item-section avatar><q-icon name="logout" /></q-item-section>
                <q-item-section>Abmelden</q-item-section>
              </q-item>
            </q-list>
          </q-menu>
        </q-btn>
      </q-toolbar>
    </q-header>

    <q-drawer v-model="drawer" show-if-above bordered>
      <q-scroll-area class="fit">
        <q-list>
          <q-item-label header>Navigation</q-item-label>

          <q-item clickable :to="{ name: 'dashboard' }" active-class="bg-primary text-white">
            <q-item-section avatar><q-icon name="home" /></q-item-section>
            <q-item-section>Übersicht</q-item-section>
          </q-item>

          <q-item
            v-if="auth.hasPermission('abteilungen.read')"
            clickable
            :to="{ name: 'abteilungen' }"
            active-class="bg-primary text-white"
          >
            <q-item-section avatar><q-icon name="account_tree" /></q-item-section>
            <q-item-section>Abteilungen</q-item-section>
          </q-item>

          <q-item
            v-if="auth.hasPermission('mitglieder.read')"
            clickable
            :to="{ name: 'mitglieder' }"
            active-class="bg-primary text-white"
          >
            <q-item-section avatar><q-icon name="group" /></q-item-section>
            <q-item-section>Mitglieder</q-item-section>
          </q-item>

          <q-item
            clickable
            :to="{ name: 'kassenbuch' }"
            active-class="bg-primary text-white"
          >
            <q-item-section avatar><q-icon name="account_balance_wallet" /></q-item-section>
            <q-item-section>Kassenbuch</q-item-section>
          </q-item>

          <q-item
            clickable
            :to="{ name: 'tickets' }"
            active-class="bg-primary text-white"
          >
            <q-item-section avatar><q-icon name="confirmation_number" /></q-item-section>
            <q-item-section>Tickets</q-item-section>
          </q-item>

          <q-item
            v-if="auth.user?.role === 'admin' || auth.hasPermission('tickets.bereiche.verwalten')"
            clickable
            :to="{ name: 'ticket-verwaltung' }"
            active-class="bg-primary text-white"
          >
            <q-item-section avatar><q-icon name="settings" /></q-item-section>
            <q-item-section>Ticket-Verwaltung</q-item-section>
          </q-item>

          <q-item
            v-if="auth.user?.role === 'admin'"
            clickable
            :to="{ name: 'kassenverwaltung' }"
            active-class="bg-primary text-white"
          >
            <q-item-section avatar><q-icon name="manage_history" /></q-item-section>
            <q-item-section>Kassenverwaltung</q-item-section>
          </q-item>

          <q-item
            v-if="auth.hasPermission('users.manage')"
            clickable
            :to="{ name: 'users' }"
            active-class="bg-primary text-white"
          >
            <q-item-section avatar><q-icon name="manage_accounts" /></q-item-section>
            <q-item-section>Benutzerverwaltung</q-item-section>
          </q-item>
        </q-list>
      </q-scroll-area>
    </q-drawer>

    <q-page-container>
      <router-view />
    </q-page-container>
  </q-layout>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from 'src/stores/auth'
import { useQuasar } from 'quasar'

const router = useRouter()
const auth = useAuthStore()
const $q = useQuasar()
const drawer = ref(!$q.platform.is.mobile)

function onLogout() {
  auth.logout()
  router.push({ name: 'login' })
}
</script>
