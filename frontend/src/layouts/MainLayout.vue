<template>
  <q-layout view="lHh Lpr lFf">
    <q-header>
      <q-toolbar>
        <!-- Kopfzeilen-Buttons am Handy ohne dense (42 statt 34 px) – leichter treffbar. -->
        <q-btn flat :dense="$q.screen.gt.sm" round icon="menu" @click="drawer = !drawer" />
        <q-toolbar-title>
          VTB<span v-if="pageTitle"> – {{ pageTitle }}</span>
        </q-toolbar-title>
        <q-btn
          v-if="hasHandler"
          flat :dense="$q.screen.gt.sm" round icon="refresh"
          :loading="refreshing"
          @click="triggerRefresh"
        >
          <q-tooltip>Aktualisieren</q-tooltip>
        </q-btn>
        <FeedbackFab v-if="auth.hasPermission('tickets.access')" />
        <q-btn flat :dense="$q.screen.gt.sm" round :icon="darkModeIcon" @click="toggleDarkMode">
          <q-tooltip>{{ darkModeLabel }}</q-tooltip>
        </q-btn>
        <q-btn flat :dense="$q.screen.gt.sm" round icon="account_circle">
          <q-menu class="vtb-konto-menu">
            <div class="vtb-konto-kopf">
              <div class="vtb-konto-avatar">{{ kontoInitial }}</div>
              <div>
                <div class="text-weight-bold">{{ auth.user?.username }}</div>
                <div class="vtb-konto-rolle">{{ kontoRolle }}</div>
                <div v-if="appVersion && $q.screen.lt.sm" class="vtb-konto-version">{{ appVersion }}</div>
              </div>
            </div>
            <q-separator />
            <q-list style="min-width: 230px">
              <q-item clickable v-close-popup :to="{ name: 'profile' }">
                <q-item-section avatar><q-icon name="person" /></q-item-section>
                <q-item-section>Mein Profil</q-item-section>
              </q-item>
              <q-item v-if="canInstall" clickable v-close-popup @click="triggerInstall">
                <q-item-section avatar><q-icon name="install_mobile" /></q-item-section>
                <q-item-section>App installieren</q-item-section>
              </q-item>
              <q-item clickable v-close-popup @click="onReloadApp">
                <q-item-section avatar><q-icon name="refresh" /></q-item-section>
                <q-item-section>App neu laden</q-item-section>
              </q-item>
              <q-separator />
              <q-item clickable v-close-popup class="vtb-konto-abmelden" @click="onLogout">
                <q-item-section avatar><q-icon name="logout" /></q-item-section>
                <q-item-section>Abmelden</q-item-section>
              </q-item>
            </q-list>
          </q-menu>
        </q-btn>
      </q-toolbar>
    </q-header>

    <q-drawer v-model="drawer" show-if-above bordered>
      <q-scroll-area class="vtb-drawer-scroll">
        <q-list>
          <!-- Wappen als Home-Button: gleiche Höhe wie die Header-Leiste daneben -->
          <q-item clickable :to="{ name: 'dashboard' }" exact active-class="vtb-nav-active" class="vtb-drawer-home">
            <q-item-section avatar>
              <img src="/icons/vtb-wappen-512.png" alt="VTB-Wappen" class="vtb-drawer-home__logo" />
            </q-item-section>
            <q-item-section>Home</q-item-section>
          </q-item>

          <q-item
            v-if="auth.hasPermission('mannschaften.read')"
            clickable
            :to="{ name: 'mannschaften' }"
            active-class="vtb-nav-active"
          >
            <q-item-section avatar><q-icon name="sports_soccer" /></q-item-section>
            <q-item-section>Mannschaften</q-item-section>
          </q-item>

          <q-item
            v-if="hatTermineZugriff || auth.hasPermission('termine.verwalten')"
            clickable
            :to="{ name: 'termine' }"
            active-class="vtb-nav-active"
          >
            <q-item-section avatar><q-icon name="event" /></q-item-section>
            <q-item-section>Termine</q-item-section>
          </q-item>

          <q-item
            v-if="auth.hasPermission('personen.read')"
            clickable
            :to="{ name: 'personen' }"
            active-class="vtb-nav-active"
          >
            <q-item-section avatar><q-icon name="people" /></q-item-section>
            <q-item-section>Personen</q-item-section>
          </q-item>

          <q-item
            v-if="hatKassenZugriff || auth.hasPermission('kassen.verwalten')"
            clickable
            :to="{ name: auth.hasPermission('kassen.verwalten') ? 'kassenverwaltung' : 'kassenbuch' }"
            active-class="vtb-nav-active"
          >
            <q-item-section avatar><q-icon name="account_balance_wallet" /></q-item-section>
            <q-item-section>Kassenbuch</q-item-section>
          </q-item>

          <q-item
            v-if="auth.hasPermission('schliessanlage.read')"
            clickable
            :to="{ name: 'schliessanlage' }"
            active-class="vtb-nav-active"
          >
            <q-item-section avatar><q-icon name="lock" /></q-item-section>
            <q-item-section>Schließanlage</q-item-section>
          </q-item>

          <q-item
            v-if="hatTresorZugriff || auth.hasPermission('tresor.verwalten')"
            clickable
            :to="{ name: 'tresor' }"
            active-class="vtb-nav-active"
          >
            <q-item-section avatar><q-icon name="vpn_key" /></q-item-section>
            <q-item-section>Passwörter</q-item-section>
          </q-item>

          <q-item
            v-if="auth.hasPermission('berichte.read')"
            clickable
            :to="{ name: 'berichte' }"
            active-class="vtb-nav-active"
          >
            <q-item-section avatar><q-icon name="insights" /></q-item-section>
            <q-item-section>Berichte</q-item-section>
          </q-item>

          <q-item
            clickable
            :to="{ name: 'tickets' }"
            active-class="vtb-nav-active"
          >
            <q-item-section avatar><q-icon name="confirmation_number" /></q-item-section>
            <q-item-section>Tickets</q-item-section>
          </q-item>

          <q-item
            v-if="auth.hasPermission('beitraege.read')"
            clickable
            :to="{ name: 'beitraege' }"
            active-class="vtb-nav-active"
          >
            <q-item-section avatar><q-icon name="euro" /></q-item-section>
            <q-item-section>Beiträge</q-item-section>
          </q-item>

          <q-item
            v-if="auth.hasPermission('gebuehren.read')"
            clickable
            :to="{ name: 'gebuehren' }"
            active-class="vtb-nav-active"
          >
            <q-item-section avatar><q-icon name="receipt_long" /></q-item-section>
            <q-item-section>Gebühren</q-item-section>
          </q-item>

          <q-item
            v-if="auth.hasPermission('ulstunden.erfassen') || auth.hasPermission('ulstunden.erfassen_fremd') || auth.hasPermission('ulstunden.bestaetigen') || auth.hasPermission('ulstunden.verwalten')"
            clickable
            :to="{ name: 'uebungsleiter' }"
            active-class="vtb-nav-active"
          >
            <q-item-section avatar><q-icon name="sports" /></q-item-section>
            <q-item-section>Übungsleiter</q-item-section>
          </q-item>

          <q-item
            v-if="hatEinstellungenZugriff"
            clickable
            :to="{ name: 'einstellungen' }"
            active-class="vtb-nav-active"
          >
            <q-item-section avatar><q-icon name="tune" /></q-item-section>
            <q-item-section>Einstellungen</q-item-section>
          </q-item>

          <q-item
            v-if="hatSonstigesZugriff"
            clickable
            :to="{ name: 'sonstiges' }"
            active-class="vtb-nav-active"
          >
            <q-item-section avatar><q-icon name="more_horiz" /></q-item-section>
            <q-item-section>Sonstiges</q-item-section>
          </q-item>

          <q-item
            v-if="false"
            clickable
            :to="{ name: 'users' }"
            active-class="vtb-nav-active"
          >
            <q-item-section avatar><q-icon name="manage_accounts" /></q-item-section>
            <q-item-section>Benutzerverwaltung</q-item-section>
          </q-item>
        </q-list>
      </q-scroll-area>
      <div v-if="appVersion" class="vtb-drawer-version">{{ appVersion }}</div>
    </q-drawer>

    <q-page-container>
      <!-- PersonenPage wird gecacht, damit Filter/Sortierung/Seite/Scroll beim
           Zurückkehren (z.B. von der Berechtigungen-Seite) erhalten bleiben. -->
      <router-view v-slot="{ Component }">
        <keep-alive :include="['PersonenPage']">
          <component :is="Component" />
        </keep-alive>
      </router-view>
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
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from 'src/stores/auth'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import FeedbackFab from 'src/components/FeedbackFab.vue'
import { useRefreshControl, installAutoRefresh, registerGlobalRefresh } from 'src/composables/useRefresh'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const $q = useQuasar()
const drawer = ref($q.screen.gt.sm)

// Konto-Menü: Avatar-Initial und lesbare Rollenbezeichnung
const kontoInitial = computed(() => (auth.user?.username || '?').charAt(0).toUpperCase())
const kontoRolle = computed(() => {
  const rollen = { admin: 'Administrator', mitglied: 'Mitglied' }
  return rollen[auth.user?.role] || auth.user?.role || ''
})

// Seitentitel aus der Route (meta.title) — im Header und im Browser-Tab.
const pageTitle = computed(() => route.meta?.title || '')
watch(
  pageTitle,
  (t) => {
    document.title = t ? `VTB – ${t}` : 'VTB Vereinsverwaltung'
  },
  { immediate: true },
)

// Zwei gebündelte Bereiche: „Einstellungen" (Funktionen/Abteilungen) und „Sonstiges"
// (Import/Bereinigung/Fibu-Export/Protokoll). Jeweils sichtbar, sobald der Nutzer
// mindestens einen Unterbereich darf. Import ist adminOnly – Admins sehen ohnehin alles.
const hatEinstellungenZugriff = computed(
  () =>
    auth.user?.role === 'admin' ||
    auth.hasPermission('funktionen.verwalten') ||
    auth.hasPermission('abteilungen.read'),
)
const hatSonstigesZugriff = computed(
  () =>
    auth.user?.role === 'admin' ||
    auth.hasPermission('system.config') ||
    auth.hasPermission('fibu.export') ||
    auth.hasPermission('system.protokoll'),
)

// Refresh der aktuell sichtbaren Listen-Seite (Button + Auto bei App-Fokus).
const { refreshing, hasHandler, triggerRefresh } = useRefreshControl()

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

const hatKassenZugriff = ref(false)
const hatTresorZugriff = ref(false)
const hatTermineZugriff = ref(false)

const appVersion = ref('')

async function loadAppVersion() {
  try {
    const { data } = await api.get('/api/app-info')
    appVersion.value = data.version ? `v.${data.version}` : ''
  } catch {
    appVersion.value = ''
  }
}

async function loadKassenZugriff() {
  try {
    const { data } = await api.get('/api/kassen/')
    hatKassenZugriff.value = data.length > 0
  } catch {
    hatKassenZugriff.value = false
  }
}

async function loadTresorZugriff() {
  try {
    const { data } = await api.get('/api/tresor')
    hatTresorZugriff.value = data.length > 0
  } catch {
    hatTresorZugriff.value = false
  }
}

async function loadTermineZugriff() {
  try {
    const { data } = await api.get('/api/termine/mannschaften')
    hatTermineZugriff.value = data.length > 0
  } catch {
    hatTermineZugriff.value = false
  }
}

// Alle ACL-Proben zusammen – läuft beim Mount UND bei jedem Auto-/Manuell-
// Refresh (registerGlobalRefresh): ein einmalig fehlgeschlagener Aufruf oder
// eine erst nach dem Login vergebene Kader-/ACL-Zuordnung ließ die Nav-Punkte
// sonst dauerhaft verschwinden, während sich die Dashboard-Kacheln erholten.
function ladeZugriffsProben() {
  return Promise.all([loadKassenZugriff(), loadTresorZugriff(), loadTermineZugriff()])
}

async function onLogout() {
  await auth.logoutServer()
  hatKassenZugriff.value = false
  hatTresorZugriff.value = false
  hatTermineZugriff.value = false
  router.push({ name: 'login' })
}

async function onReloadApp() {
  if ('caches' in window) {
    const keys = await caches.keys()
    await Promise.all(keys.map(k => caches.delete(k)))
  }
  window.location.reload()
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

let unregisterZugriffsProben = null
onBeforeUnmount(() => unregisterZugriffsProben?.())

onMounted(() => {
  installAutoRefresh()
  unregisterZugriffsProben = registerGlobalRefresh(ladeZugriffsProben)
  ladeZugriffsProben()
  loadAppVersion()
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
