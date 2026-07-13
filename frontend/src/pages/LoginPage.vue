<template>
  <div class="login-screen">
    <div class="login-panel">
      <div class="login-badge">
        <img src="/icons/vtb-wappen-512.png" alt="VTB-Wappen" />
      </div>

      <q-card flat dark class="login-card">
        <q-card-section class="text-center q-pb-none">
          <div class="login-title text-h5 text-weight-bold">VTB Chemnitz</div>
          <div class="login-subtitle">Vereinsverwaltung</div>
        </q-card-section>

        <q-card-section>
          <q-tabs
            v-model="tab"
            dense
            align="justify"
            class="q-mb-md"
            active-color="yellow"
            indicator-color="yellow"
          >
            <q-tab name="password" label="Passwort" />
            <q-tab name="magic" label="Login-Link" />
          </q-tabs>

          <!-- Passwort-Login -->
          <q-tab-panels v-model="tab" animated>
            <q-tab-panel name="password" class="q-pa-none">
              <q-form @submit.prevent="onLogin" class="q-gutter-md">
                <q-input
                  v-model="username"
                  label="Benutzername"
                  outlined
                  dark
                  color="yellow"
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
                  color="yellow"
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
                  color="yellow"
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
                  Gib deine E-Mail-Adresse ein. Du erhältst einen Link, mit dem du dich ohne Passwort einloggen kannst.
                </div>
                <q-form @submit.prevent="onRequestMagicLink" class="q-gutter-md">
                  <q-input
                    v-model="magicEmail"
                    label="E-Mail-Adresse"
                    type="email"
                    outlined
                    dark
                    color="yellow"
                    autofocus
                    no-error-icon
                    lazy-rules="ondemand"
                    :disable="loading"
                    :rules="[(v) => !!v || 'Pflichtfeld']"
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
                    color="yellow"
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
                  Falls ein Konto mit dieser Adresse existiert, haben wir dir einen Login-Link geschickt.
                  Bitte prüfe auch deinen Spam-Ordner.
                </div>
                <q-btn flat label="Nochmal versuchen" color="yellow" no-caps @click="magicSent = false" />
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

const router = useRouter()
const auth = useAuthStore()

const tab = ref('magic')

const appVersion = ref('')

async function loadAppVersion() {
  try {
    const { data } = await api.get('/api/app-info')
    appVersion.value = data.version ? `v.${data.version}` : ''
  } catch {
    appVersion.value = ''
  }
}

onMounted(loadAppVersion)

const username = ref('')
const password = ref('')
const showPassword = ref(false)

const rememberMe = ref(false)

const magicEmail = ref('')
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

async function onLogin() {
  errorMsg.value = ''
  loading.value = true
  try {
    await auth.login(username.value, password.value, rememberMe.value)
    router.push({ name: 'dashboard' })
  } catch (err) {
    errorMsg.value = err.response?.data?.detail || 'Anmeldung fehlgeschlagen'
  } finally {
    loading.value = false
  }
}

async function onRequestMagicLink() {
  errorMsg.value = ''
  loading.value = true
  try {
    await api.post('/api/auth/magic-link/request', { email: magicEmail.value })
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
  background: linear-gradient(165deg, #fff05a 0%, $vtb-gelb 45%, #e3d100 100%);
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
  background: linear-gradient(170deg, #0d3a85 0%, $vtb-blau 45%, #022a68 100%);
  /* Kräftiger Schlagschatten — das helle Gelb verschluckt zarte Schatten,
     daher hohe Deckkraft und warmer, dunkler Ton (wirkt auf Gelb natürlich). */
  box-shadow:
    0 6px 16px rgba(0, 0, 0, 0.35),
    0 28px 55px -8px rgba(75, 62, 0, 0.65);
}

.login-title {
  color: $vtb-gelb;
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
  color: $vtb-gelb;
}

/* Eingabefelder: weichere Ecken, Rahmen in Gelb */
:deep(.q-field--outlined .q-field__control) {
  border-radius: 12px;
}
:deep(.q-field--outlined .q-field__control:before) {
  border-color: rgba(254, 235, 3, 0.5);
}
:deep(.q-field--outlined:hover .q-field__control:before) {
  border-color: $vtb-gelb;
}

/* Tab-Panels ohne eigenen Hintergrund (sonst Kasten auf der blauen Karte) */
:deep(.q-tab-panels) {
  background: transparent;
}
</style>
