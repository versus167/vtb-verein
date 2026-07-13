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

        <!-- q-gutter-y-md statt q-gutter-md: der horizontale Gutter-Anteil würde
             den Vollbreite-Button aus der Mitte schieben -->
        <q-card-section class="text-center q-gutter-y-md">
          <!-- Auswahl: Sitzungsdauer -->
          <template v-if="state === 'prompt'">
            <q-icon name="login" size="3rem" color="vtb-gelb" />
            <div class="text-h6">Fast geschafft</div>
            <div class="text-body2 login-hint">
              Klicke auf „Einloggen“, um fortzufahren.
            </div>
            <q-checkbox v-model="rememberMe" dark label="30 Tage eingeloggt bleiben" />
            <q-btn
              unelevated
              color="vtb-gelb"
              text-color="primary"
              label="Einloggen"
              no-caps
              size="lg"
              class="full-width login-btn text-weight-bold q-mt-sm"
              @click="doLogin"
            />
          </template>

          <!-- Prüfung läuft -->
          <template v-else-if="state === 'loading'">
            <q-spinner-dots color="vtb-gelb" size="3rem" />
            <div class="text-body2 login-hint">Link wird geprüft …</div>
          </template>

          <!-- Erfolg -->
          <template v-else-if="state === 'success'">
            <q-icon name="check_circle" size="3rem" color="positive" />
            <div class="text-h6">Erfolgreich eingeloggt</div>
            <div class="text-body2 login-hint">Du wirst weitergeleitet …</div>
          </template>

          <!-- Fehler -->
          <template v-else>
            <q-icon name="error_outline" size="3rem" color="vtb-gelb" />
            <div class="text-h6">Link ungültig</div>
            <div class="login-error text-body2">
              {{ errorMsg }}
            </div>
            <q-btn
              unelevated
              color="vtb-gelb"
              text-color="primary"
              label="Zurück zum Login"
              no-caps
              size="lg"
              class="full-width login-btn text-weight-bold q-mt-md"
              @click="$router.push({ name: 'login' })"
            />
          </template>
        </q-card-section>
      </q-card>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from 'src/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const state = ref('prompt')
const rememberMe = ref(false)
const errorMsg = ref('Der Link ist ungültig oder wurde bereits verwendet.')

onMounted(() => {
  if (!route.query.token) {
    state.value = 'error'
  }
})

async function doLogin() {
  const token = route.query.token
  if (!token) {
    state.value = 'error'
    return
  }
  state.value = 'loading'
  try {
    await auth.loginWithMagicToken(token, rememberMe.value)
    state.value = 'success'
    setTimeout(() => router.push({ name: 'dashboard' }), 1000)
  } catch (err) {
    errorMsg.value =
      err.response?.data?.detail || 'Der Link ist ungültig oder wurde bereits verwendet.'
    state.value = 'error'
  }
}
</script>

<style lang="scss" scoped>
/* Gleicher Look wie die Login-Seite (LoginPage.vue): bewusst in beiden Modi
   identisch — Gelb außen als Fortsetzung des PWA-Splash, Wappenblau als Karte. */
.login-screen {
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

.login-btn {
  border-radius: 12px;
}

/* Fehlermeldungen in Gelb auf der blauen Karte */
.login-error {
  font-weight: 600;
  color: $vtb-gelb;
}
</style>
