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
            v-if="auth.hasPermission('mitglieder.read')"
            clickable
            :to="{ name: 'mitglieder' }"
            active-class="bg-primary text-white"
          >
            <q-item-section avatar><q-icon name="group" /></q-item-section>
            <q-item-section>Mitglieder</q-item-section>
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

const router = useRouter()
const auth = useAuthStore()
const drawer = ref(true)

function onLogout() {
  auth.logout()
  router.push({ name: 'login' })
}
</script>
