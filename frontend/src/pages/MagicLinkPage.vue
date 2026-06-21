<template>
  <div class="flex flex-center" :class="$q.dark.isActive ? 'login-bg--dark' : 'bg-grey-2'" style="min-height: 100vh">
    <q-card style="min-width: 360px; max-width: 420px; width: 100%">
      <q-card-section class="text-center q-pb-none">
        <q-icon name="corporate_fare" size="4rem" color="primary" />
        <div class="text-h5 q-mt-sm">Vereinsverwaltung</div>
        <div class="text-caption text-grey">VTB</div>
      </q-card-section>

      <q-card-section class="text-center q-gutter-md">
        <!-- Auswahl: Sitzungsdauer -->
        <template v-if="state === 'prompt'">
          <q-icon name="login" size="3rem" color="primary" />
          <div class="text-h6">Fast geschafft</div>
          <div class="text-body2 text-grey-7">
            Klicke auf „Einloggen“, um fortzufahren.
          </div>
          <q-checkbox v-model="rememberMe" label="30 Tage eingeloggt bleiben" />
          <q-btn
            unelevated
            color="primary"
            label="Einloggen"
            class="full-width q-mt-sm"
            @click="doLogin"
          />
        </template>

        <!-- Prüfung läuft -->
        <template v-else-if="state === 'loading'">
          <q-spinner-dots color="primary" size="3rem" />
          <div class="text-body2 text-grey-7">Link wird geprüft …</div>
        </template>

        <!-- Erfolg -->
        <template v-else-if="state === 'success'">
          <q-icon name="check_circle" size="3rem" color="positive" />
          <div class="text-h6">Erfolgreich eingeloggt</div>
          <div class="text-body2 text-grey-7">Du wirst weitergeleitet …</div>
        </template>

        <!-- Fehler -->
        <template v-else>
          <q-icon name="error_outline" size="3rem" color="negative" />
          <div class="text-h6">Link ungültig</div>
          <div class="text-body2 text-grey-7">
            {{ errorMsg }}
          </div>
          <q-btn
            unelevated
            color="primary"
            label="Zurück zum Login"
            class="full-width q-mt-md"
            @click="$router.push({ name: 'login' })"
          />
        </template>
      </q-card-section>
    </q-card>
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

<style scoped>
/* Im Darkmode dunkler als die Karte (#1d1d1d), damit sie sich abhebt. */
.login-bg--dark {
  background-color: #121212;
}
</style>
