<template>
  <q-layout view="lHh Lpr lFf">
    <q-header>
      <q-toolbar>
        <!-- Kopfzeilen-Buttons am Handy ohne dense (42 statt 34 px) – leichter treffbar. -->
        <q-btn flat :dense="$q.screen.gt.sm" round icon="menu" @click="drawer = !drawer">
          <!-- Summe offener Aufgaben (#133): immer sichtbar (auch am Desktop mit
               offener Schublade), damit die Gesamtzahl auf einen Blick da ist; beim
               Öffnen zeigt die Nav zusätzlich die Einzel-Badges pro Bereich. -->
          <q-badge v-if="aufgaben.gesamt > 0" floating rounded color="negative"
            :label="aufgaben.gesamt > 99 ? '99+' : aufgaben.gesamt"
            :aria-label="`${aufgaben.gesamt} offene Aufgaben insgesamt`" />
        </q-btn>
        <q-toolbar-title>{{ toolbarTitle }}</q-toolbar-title>
        <!-- Seiten-Refresh nur am Desktop: am Handy wirkte er neben „App neu laden"
             im Konto-Menü wie ein zweiter Reload-Knopf. Auto-Refresh bei App-Fokus
             bleibt aktiv. -->
        <q-btn
          v-if="hasHandler && $q.screen.gt.sm"
          flat dense round icon="refresh"
          :loading="refreshing"
          @click="triggerRefresh"
        >
          <q-tooltip>Aktualisieren</q-tooltip>
        </q-btn>
        <!-- Push- und Theme-Button nur auf der Übersicht — auf Unterseiten nehmen
             sie am Handy dem Seitentitel zu viel Platz weg. Am Desktop überall. -->
        <FeedbackFab v-if="auth.hasPermission('tickets.access')" />
        <PushStatusButton v-if="zeigeKopfExtras" />
        <!-- Erscheinungsbild (#131): VTB-Look, neutrales Hell, Dunkel oder System.
             Menü statt Durchklicken — bei vier Zuständen rät man sonst, was kommt. -->
        <q-btn v-if="zeigeKopfExtras" flat :dense="$q.screen.gt.sm" round :icon="themeIcon">
          <q-tooltip>Erscheinungsbild: {{ themeLabel }}</q-tooltip>
          <q-menu>
            <q-list style="min-width: 200px">
              <q-item-label header class="q-py-sm">Erscheinungsbild</q-item-label>
              <!-- Kein eigenes active-class: die gewählte Zeile soll die
                   Aktiv-Farbe des jeweiligen Themes tragen (app.scss färbt
                   .q-item--active in Menüs je Theme um). -->
              <q-item
                v-for="t in THEME_AUSWAHL"
                :key="t.wert"
                clickable
                v-close-popup
                :active="themeWahl === t.wert"
                @click="setTheme(t.wert)"
              >
                <q-item-section avatar><q-icon :name="t.icon" /></q-item-section>
                <q-item-section>{{ t.label }}</q-item-section>
                <q-item-section side v-if="themeWahl === t.wert">
                  <q-icon name="check" />
                </q-item-section>
              </q-item>
            </q-list>
          </q-menu>
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
              <img src="/icons/logo-512.png" alt="Vereinslogo" class="vtb-drawer-home__logo" />
            </q-item-section>
            <q-item-section>Home</q-item-section>
          </q-item>

          <q-item
            v-if="hatMannschaftenZugriff || auth.hasPermission('mannschaften.read')"
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
            v-if="hatTeamkasseZugriff"
            clickable
            :to="{ name: 'teamkasse' }"
            active-class="vtb-nav-active"
          >
            <q-item-section avatar><q-icon name="sports_bar" /></q-item-section>
            <q-item-section>Teamkasse</q-item-section>
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
            v-if="auth.hasPermission('personen.freischalten') || auth.hasPermission('personen.permissions')"
            clickable
            :to="{ name: 'zugaenge' }"
            active-class="vtb-nav-active"
          >
            <q-item-section avatar><q-icon name="how_to_reg" /></q-item-section>
            <q-item-section>Zugänge</q-item-section>
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
            <q-item-section>Passwörter/Kontakte</q-item-section>
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
            <q-item-section side>
              <AufgabenBadge :anzahl="aufgaben.anzahl('tickets')" />
            </q-item-section>
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
            <q-item-section side>
              <AufgabenBadge :anzahl="aufgaben.anzahl('uebungsleiter')" />
            </q-item-section>
          </q-item>

          <q-item
            v-if="hatRechnungenZugriff"
            clickable
            :to="{ name: 'rechnungen' }"
            active-class="vtb-nav-active"
          >
            <q-item-section avatar><q-icon name="receipt_long" /></q-item-section>
            <q-item-section>Rechnungen</q-item-section>
            <q-item-section side>
              <AufgabenBadge :anzahl="aufgaben.anzahl('rechnungen')" />
            </q-item-section>
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
      <div v-if="appVersion || sourceUrl" class="vtb-drawer-version">
        <span v-if="appVersion">{{ appVersion }}</span>
        <template v-if="appVersion && sourceUrl"> · </template>
        <a v-if="sourceUrl" :href="sourceUrl" target="_blank" rel="noopener">Quellcode</a>
      </div>
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
import { useAufgabenStore } from 'src/stores/aufgaben'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import AufgabenBadge from 'src/components/AufgabenBadge.vue'
import FeedbackFab from 'src/components/FeedbackFab.vue'
import PushStatusButton from 'src/components/PushStatusButton.vue'
import { useRefreshControl, installAutoRefresh, registerGlobalRefresh } from 'src/composables/useRefresh'
import { appInfo, ladeAppInfo, versionLabel } from 'src/composables/useAppInfo'
import { THEME_AUSWAHL, setTheme, themeWahl, themeIcon, themeLabel } from 'src/composables/useTheme'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
// Offene Aufgaben für die Hinweise an Nav-Punkten und Dashboard-Kacheln (#133).
// Zentral hier geladen, weil das Layout immer steht – die Kacheln lesen mit.
const aufgaben = useAufgabenStore()
const $q = useQuasar()
const drawer = ref($q.screen.gt.sm)

// Konto-Menü: Avatar-Initial und lesbare Rollenbezeichnung
const kontoInitial = computed(() => (auth.user?.username || '?').charAt(0).toUpperCase())
const kontoRolle = computed(() => {
  const rollen = { admin: 'Administrator', mitglied: 'Mitglied' }
  return rollen[auth.user?.role] || auth.user?.role || ''
})

// Push-/Theme-Button: am Handy nur auf der Übersicht (Platz für den Seitentitel),
// am Desktop auf allen Seiten.
const zeigeKopfExtras = computed(() => $q.screen.gt.sm || route.name === 'dashboard')

// Seitentitel aus der Route (meta.title) — im Header und im Browser-Tab.
const pageTitle = computed(() => route.meta?.title || '')

// Vereinskürzel als Titel-Präfix; Stammdatum aus /api/app-info (VTB_VEREIN_KURZ).
// Solange nichts geladen ist, bleibt das Präfix weg — lieber ohne als mit einem
// fremden Vereinskürzel.
const vereinKurz = computed(() => (appInfo.value.verein_kurz || '').trim())

watch(
  [pageTitle, vereinKurz],
  ([t, kurz]) => {
    if (t) document.title = kurz ? `${kurz} – ${t}` : t
    else document.title = kurz ? `${kurz} Vereinsverwaltung` : 'Vereinsverwaltung'
  },
  { immediate: true },
)

// Kopfzeilen-Titel: am Desktop „<Kürzel> – <Seite>". Am Handy ohne Präfix nur der
// Seitenname — und auf der Übersicht gar nichts, dort steht bereits die
// „Willkommen …"-Begrüßung auf der Seite.
const toolbarTitle = computed(() => {
  if ($q.screen.gt.sm) {
    if (!pageTitle.value) return vereinKurz.value
    return vereinKurz.value ? `${vereinKurz.value} – ${pageTitle.value}` : pageTitle.value
  }
  return route.name === 'dashboard' ? '' : pageTitle.value
})

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
    auth.hasPermission('spielstaetten.verwalten') ||
    auth.hasPermission('fibu.export') ||
    auth.hasPermission('system.protokoll'),
)

// Rechnungen: rein permission-gesteuert, keine ACL-Ressourcenliste nötig.
// 'rechnungen.freigeben' kann rein abteilungs-scoped geerbt sein – hasPermission
// ist lenient und erfasst das (die Abteilungs-Prüfung macht das Backend).
const hatRechnungenZugriff = computed(
  () =>
    auth.hasPermission('rechnungen.einreichen') ||
    auth.hasPermission('rechnungen.freigeben') ||
    auth.hasPermission('rechnungen.verwalten'),
)

// Refresh der aktuell sichtbaren Listen-Seite (Button + Auto bei App-Fokus).
const { refreshing, hasHandler, triggerRefresh } = useRefreshControl()

const hatKassenZugriff = ref(false)
const hatTresorZugriff = ref(false)
const hatTermineZugriff = ref(false)
const hatMannschaftenZugriff = ref(false)
const hatTeamkasseZugriff = ref(false)

const appVersion = versionLabel
const sourceUrl = computed(() => appInfo.value.source_url || '')   // AGPL §13

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

// Kader-ÜL/Betreuer ohne globales mannschaften.read sehen den Bereich scoped
// (nur ihre Abteilung); die Liste liefert dann >0 Teams bzw. 403 (#121).
async function loadMannschaftenZugriff() {
  try {
    const { data } = await api.get('/api/mannschaften')
    hatMannschaftenZugriff.value = data.length > 0
  } catch {
    hatMannschaftenZugriff.value = false
  }
}

async function loadTeamkasseZugriff() {
  try {
    const { data } = await api.get('/api/clubdeckel/teams')
    hatTeamkasseZugriff.value = data.length > 0
  } catch {
    hatTeamkasseZugriff.value = false
  }
}

// Alle ACL-Proben zusammen – läuft beim Mount UND bei jedem Auto-/Manuell-
// Refresh (registerGlobalRefresh): ein einmalig fehlgeschlagener Aufruf oder
// eine erst nach dem Login vergebene Kader-/ACL-Zuordnung ließ die Nav-Punkte
// sonst dauerhaft verschwinden, während sich die Dashboard-Kacheln erholten.
// auth.loadMe() läuft mit (#130): Rechte-Änderungen greifen so ohne App-Neustart
// beim nächsten Refresh (Button bzw. Rückkehr zur App) statt erst beim Neuladen.
// Die offenen Aufgaben (#133) hängen mit dran: sie sollen sich beim selben
// Anlass aktualisieren wie die Nav-Punkte, an denen sie stehen.
function ladeZugriffsProben() {
  return Promise.all([auth.loadMe().catch(() => {}),
    loadKassenZugriff(), loadTresorZugriff(), loadTermineZugriff(),
    loadMannschaftenZugriff(), loadTeamkasseZugriff(), aufgaben.laden()])
}

async function onLogout() {
  await auth.logoutServer()
  hatKassenZugriff.value = false
  hatTresorZugriff.value = false
  hatTermineZugriff.value = false
  hatMannschaftenZugriff.value = false
  hatTeamkasseZugriff.value = false
  aufgaben.zuruecksetzen()
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
  ladeAppInfo()
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
