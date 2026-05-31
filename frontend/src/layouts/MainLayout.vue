<template>
  <q-layout view="lHh Lpr lFf">
    <q-header elevated>
      <q-toolbar>
        <q-btn flat dense round icon="menu" @click="drawer = !drawer" />
        <q-toolbar-title>Vereinsverwaltung</q-toolbar-title>
        <q-btn flat dense round :icon="darkModeIcon" @click="toggleDarkMode">
          <q-tooltip>{{ darkModeLabel }}</q-tooltip>
        </q-btn>
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
              <q-item v-if="canInstall" clickable v-close-popup @click="triggerInstall">
                <q-item-section avatar><q-icon name="install_mobile" /></q-item-section>
                <q-item-section>App installieren</q-item-section>
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

    <!-- PWA-Installationsbanner (Android/Chrome) -->
    <q-banner
      v-if="showInstallBanner"
      dense
      class="bg-primary text-white fixed-bottom"
      style="z-index: 9999"
    >
      <template #avatar>
        <q-icon name="install_mobile" color="white" />
      </template>
      App auf dem Gerät installieren?
      <template #action>
        <q-btn flat dense label="Installieren" @click="installApp" />
        <q-btn flat dense label="Später" @click="dismissBanner" />
      </template>
    </q-banner>

    <!-- PWA-Hinweis für iOS (kein beforeinstallprompt) -->
    <q-banner
      v-if="showIosBanner"
      dense
      class="bg-primary text-white fixed-bottom"
      style="z-index: 9999"
    >
      <template #avatar>
        <q-icon name="ios_share" color="white" />
      </template>
      Zum Installieren: Teilen-Button → „Zum Home-Bildschirm"
      <template #action>
        <q-btn flat dense label="OK" @click="dismissBanner" />
      </template>
    </q-banner>
  </q-layout>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from 'src/stores/auth'
import { useQuasar } from 'quasar'

const router = useRouter()
const auth = useAuthStore()
const $q = useQuasar()
const drawer = ref(!$q.platform.is.mobile)

const darkModeIcon = computed(() => {
  const v = $q.dark.mode
  if (v === true) return 'dark_mode'
  if (v === false) return 'light_mode'
  return 'brightness_auto'
})

const darkModeLabel = computed(() => {
  const v = $q.dark.mode
  if (v === true) return 'Dunkel'
  if (v === false) return 'Hell'
  return 'Systemeinstellung'
})

function toggleDarkMode() {
  const v = $q.dark.mode
  let next
  if (v === 'auto') next = false
  else if (v === false) next = true
  else next = 'auto'
  $q.dark.set(next)
  localStorage.setItem('darkMode', next === 'auto' ? 'auto' : String(next))
}

function onLogout() {
  auth.logout()
  router.push({ name: 'login' })
}

// ── PWA-Installation ──
let deferredPrompt = null
const showInstallBanner = ref(false)
const showIosBanner = ref(false)
const isInstalled = ref(false)
const isIosPlatform = ref(false)

const canInstall = computed(() =>
  !isInstalled.value && (!!deferredPrompt || isIosPlatform.value)
)

function triggerInstall() {
  if (deferredPrompt) {
    installApp()
  } else if (isIosPlatform.value) {
    showIosBanner.value = true
  }
}

onMounted(() => {
  const isInStandaloneMode = window.matchMedia('(display-mode: standalone)').matches
    || window.navigator.standalone === true

  if (isInStandaloneMode) {
    isInstalled.value = true
    return
  }

  isIosPlatform.value = $q.platform.is.ios

  if (isIosPlatform.value) {
    if (!localStorage.getItem('pwaInstallDismissed')) showIosBanner.value = true
    return
  }

  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault()
    deferredPrompt = e
    if (!localStorage.getItem('pwaInstallDismissed')) showInstallBanner.value = true
  })
})

async function installApp() {
  if (!deferredPrompt) return
  deferredPrompt.prompt()
  const { outcome } = await deferredPrompt.userChoice
  deferredPrompt = null
  showInstallBanner.value = false
  if (outcome === 'accepted') {
    isInstalled.value = true
    localStorage.setItem('pwaInstallDismissed', '1')
  }
}

function dismissBanner() {
  showInstallBanner.value = false
  showIosBanner.value = false
  localStorage.setItem('pwaInstallDismissed', '1')
}
</script>
