<template>
  <div class="login-screen">
    <div class="login-panel">
      <div class="login-badge">
        <img src="/icons/logo-512.png" alt="Vereinslogo" />
      </div>

      <q-card flat dark class="login-card">
        <q-card-section class="text-center q-pb-none">
          <div v-if="vereinName" class="login-title text-h5 text-weight-bold">{{ vereinName }}</div>
          <div class="login-subtitle">Vereinsverwaltung</div>
        </q-card-section>

        <q-card-section>
          <q-tabs
            v-model="tab"
            dense
            align="justify"
            class="q-mb-md"
            active-color="vtb-gelb"
            indicator-color="vtb-gelb"
          >
            <q-tab name="password" label="Passwort" />
            <q-tab name="magic" label="Login-Link" />
          </q-tabs>

          <!-- Passwort-Login -->
          <q-tab-panels v-model="tab" animated>
            <q-tab-panel name="password" class="q-pa-none">
              <q-form @submit.prevent="onLogin" class="q-gutter-md">
                <q-input
                  v-model="kennung"
                  label="Benutzername oder E-Mail"
                  outlined
                  dark
                  color="vtb-gelb"
                  autofocus
                  no-error-icon
                  lazy-rules="ondemand"
                  :disable="loading"
                  :rules="[(v) => !!v || 'Pflichtfeld']"
                >
                  <template #prepend>
                    <q-icon name="person" />
                  </template>
                </q-input>

                <q-input
                  v-model="password"
                  label="Passwort"
                  outlined
                  dark
                  color="vtb-gelb"
                  no-error-icon
                  lazy-rules="ondemand"
                  :type="showPassword ? 'text' : 'password'"
                  :disable="loading"
                  :rules="[(v) => !!v || 'Pflichtfeld']"
                >
                  <template #prepend>
                    <q-icon name="lock" />
                  </template>
                  <template #append>
                    <q-icon
                      :name="showPassword ? 'visibility_off' : 'visibility'"
                      class="cursor-pointer"
                      @click="showPassword = !showPassword"
                    />
                  </template>
                </q-input>

                <q-checkbox v-model="rememberMe" dark label="Angemeldet bleiben (30 Tage)" :disable="loading" />

                <div v-if="errorMsg" class="login-error text-center text-body2">
                  {{ errorMsg }}
                </div>

                <q-btn
                  type="submit"
                  label="Anmelden"
                  color="vtb-gelb"
                  text-color="primary"
                  no-caps
                  class="full-width login-btn text-weight-bold"
                  size="lg"
                  :loading="loading"
                  unelevated
                />
              </q-form>
            </q-tab-panel>

            <!-- Magic-Link -->
            <q-tab-panel name="magic" class="q-pa-none">
              <div v-if="!magicSent" class="q-gutter-md">
                <div class="text-body2 text-center login-hint">
                  Gib deine E-Mail-Adresse oder deinen Benutzernamen ein. Den Link schicken wir
                  an die hinterlegte Adresse – damit loggst du dich ohne Passwort ein.
                </div>
                <q-form @submit.prevent="onRequestMagicLink" class="q-gutter-md">
                  <q-input
                    v-model="magicKennung"
                    label="E-Mail-Adresse oder Benutzername"
                    outlined
                    dark
                    color="vtb-gelb"
                    autofocus
                    no-error-icon
                    lazy-rules="ondemand"
                    :disable="loading"
                    :rules="[kennungRule]"
                  >
                    <template #prepend>
                      <q-icon name="email" />
                    </template>
                  </q-input>

                  <div v-if="errorMsg" class="login-error text-center text-body2">
                    {{ errorMsg }}
                  </div>

                  <q-btn
                    type="submit"
                    label="Login-Link anfordern"
                    color="vtb-gelb"
                    text-color="primary"
                    no-caps
                    class="full-width login-btn text-weight-bold"
                    size="lg"
                    :loading="loading"
                    unelevated
                  />
                </q-form>
              </div>

              <div v-else class="text-center q-gutter-md">
                <q-icon name="mark_email_read" size="4rem" color="positive" />
                <div class="text-h6">E-Mail unterwegs!</div>
                <div class="text-body2 login-hint">
                  Falls es dazu ein Konto gibt, haben wir den Login-Link an die dort hinterlegte
                  E-Mail-Adresse geschickt. Bitte prüfe auch deinen Spam-Ordner.
                </div>
                <q-btn flat label="Nochmal versuchen" color="vtb-gelb" no-caps @click="magicSent = false" />
              </div>
            </q-tab-panel>
          </q-tab-panels>
          <div class="text-center q-mt-md">
            <q-btn
              flat
              dense
              size="sm"
              label="App neu laden"
              icon="refresh"
              no-caps
              @click="onReloadApp"
            />
          </div>
        </q-card-section>
      </q-card>
    </div>

    <div v-if="appVersion" class="login-version">{{ appVersion }}</div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from 'src/stores/auth'
import { api } from 'src/boot/axios'
import { ladeAppInfo, versionLabel, vereinName } from 'src/composables/useAppInfo'
import { zurUebersicht } from 'src/router/nach-login'
import { pruefeMailadresse } from 'src/utils/email'

const router = useRouter()
const auth = useAuthStore()

const tab = ref('magic')

const appVersion = versionLabel

onMounted(ladeAppInfo)

// Layout und Übersicht schon während der Eingabe holen (#157). Der Sprung nach
// dem Anmelden braucht beide Dateien; lädt der Browser sie erst in dem Moment,
// hängt der wichtigste Klick der App am Netz — und auf einem frisch geöffneten
// Gerät installiert sich zeitgleich der Service Worker. Vorher geholt, ist der
// Wechsel rein lokal. Fehlschlag ist unkritisch: Dann lädt der Router sie beim
// Wechsel nach, und scheitert das auch, greift router.onError.
onMounted(() => {
  import('layouts/MainLayout.vue').catch(() => {})
  import('pages/DashboardPage.vue').catch(() => {})
})

// Kennung = Benutzername *oder* E-Mail-Adresse. Beides ist eindeutig, also nimmt
// das Backend an beiden Stellen beides an – Passwort-Login wie Login-Link.
const kennung = ref('')
const password = ref('')
const showPassword = ref(false)

const rememberMe = ref(false)

const magicKennung = ref('')
const magicSent = ref(false)

const loading = ref(false)
const errorMsg = ref('')

async function onReloadApp() {
  if ('caches' in window) {
    const keys = await caches.keys()
    await Promise.all(keys.map(k => caches.delete(k)))
  }
  window.location.reload()
}

// Nur wenn ein @ drinsteht, ist eine Adresse gemeint – dann soll ein Vertipper
// sofort auffallen. Ohne @ ist ein Benutzername gemeint, für den es keine Formregel
// gibt außer: nicht leer.
function kennungRule (value) {
  const wert = (value ?? '').trim()
  if (!wert) return 'Bitte E-Mail-Adresse oder Benutzernamen eingeben.'
  return wert.includes('@') ? (pruefeMailadresse(wert) || true) : true
}

async function onLogin() {
  errorMsg.value = ''
  loading.value = true
  try {
    await auth.login(kennung.value, password.value, rememberMe.value)
  } catch (err) {
    errorMsg.value = err.response?.data?.detail || 'Anmeldung fehlgeschlagen'
    loading.value = false
    return
  }

  // Ab hier ist die Anmeldung durch; was jetzt schiefgeht, ist ein Navigations-
  // und kein Anmeldeproblem — deshalb nicht als „Anmeldung fehlgeschlagen"
  // melden, sondern ans Ziel bringen (alle Fälle in `zurUebersicht`, #157).
  // Der Knopf bleibt dabei im Ladezustand: Der Klick ist erst fertig, wenn die
  // Übersicht steht, nicht schon, wenn das Passwort stimmt.
  await zurUebersicht(router)
}

async function onRequestMagicLink() {
  errorMsg.value = ''
  loading.value = true
  try {
    await api.post('/api/auth/magic-link/request', { kennung: magicKennung.value })
    magicSent.value = true
  } catch (err) {
    errorMsg.value = err.response?.data?.detail || 'Anfrage fehlgeschlagen'
  } finally {
    loading.value = false
  }
}
</script>

<style lang="scss" scoped>
/* Die Login-Seite ist bewusst in beiden Modi identisch (reine Vereinsfarben):
   Gelb außen als nahtlose Fortsetzung des PWA-Splash, Wappenblau als Karte. */
.login-screen {
  position: relative;
  min-height: 100vh;
  /* dvh = sichtbare Höhe ohne Browser-Adressleiste (sonst scrollt es am Handy) */
  min-height: 100dvh;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 24px;
  background: linear-gradient(165deg, #fff05a 0%, $akzent 45%, #e3d100 100%);
}

.login-panel {
  position: relative;
  width: 100%;
  max-width: 430px;
  /* Platz für die obere Wappenhälfte, die über der Karte thront */
  padding-top: 105px;
  /* Nicht mittig, sondern etwas erhöht — auf kleinen Displays kompakt. */
  margin-top: clamp(12px, 6vh, 110px);
  animation: login-pop 0.45s ease-out;
}

@keyframes login-pop {
  from {
    opacity: 0;
    transform: translateY(14px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

/* Großes freistehendes Wappen, halb über der Kartenkante thronend */
.login-badge {
  position: absolute;
  top: 0;
  left: 50%;
  transform: translateX(-50%);
  z-index: 1;

  img {
    width: 190px;
    height: 190px;
    filter: drop-shadow(0 14px 22px rgba(60, 50, 0, 0.45));
  }
}

/* Doppelte Klasse für höhere Spezifität: muss den globalen
   Dark-Mode-Kartenstil (body--dark .q-card) übertrumpfen. */
.q-card.login-card {
  border-radius: 20px;
  /* Platz für die untere Wappenhälfte, die in die Karte hineinragt */
  padding-top: 92px;
  color: #fff;
  /* Wappenblau mit leichtem Verlauf */
  background: linear-gradient(170deg, #0d3a85 0%, $flaeche 45%, #022a68 100%);
  /* Kräftiger Schlagschatten — das helle Gelb verschluckt zarte Schatten,
     daher hohe Deckkraft und warmer, dunkler Ton (wirkt auf Gelb natürlich). */
  box-shadow:
    0 6px 16px rgba(0, 0, 0, 0.35),
    0 28px 55px -8px rgba(75, 62, 0, 0.65);
}

.login-title {
  color: $akzent;
  letter-spacing: 0.5px;
}

.login-subtitle {
  margin-top: 2px;
  font-size: 0.85rem;
  color: rgba(255, 255, 255, 0.65);
}

.login-hint {
  color: rgba(255, 255, 255, 0.75);
}

/* Versions-Angabe fest in der sichtbaren Bildschirmecke (dunkel, liegt auf Gelb) */
.login-version {
  position: fixed;
  right: 16px;
  bottom: 10px;
  font-size: 11px;
  color: rgba(0, 0, 0, 0.45);
}

.login-btn {
  border-radius: 12px;
}

/* Fehlermeldungen in Gelb auf der blauen Karte */
.login-error {
  font-weight: 600;
  color: $akzent;
}

/* Eingabefelder: weichere Ecken, Rahmen in Gelb */
:deep(.q-field--outlined .q-field__control) {
  border-radius: 12px;
}
:deep(.q-field--outlined .q-field__control:before) {
  border-color: rgba($akzent-rgb, 0.5);
}
:deep(.q-field--outlined:hover .q-field__control:before) {
  border-color: $akzent;
}

/* Tab-Panels ohne eigenen Hintergrund (sonst Kasten auf der blauen Karte) */
:deep(.q-tab-panels) {
  background: transparent;
}
</style>
