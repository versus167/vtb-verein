<template>
  <div class="flex flex-center bg-grey-2" style="min-height: 100vh">
    <q-card style="min-width: 360px; max-width: 420px; width: 100%">
      <q-card-section class="text-center q-pb-none">
        <q-icon name="corporate_fare" size="4rem" color="primary" />
        <div class="text-h5 q-mt-sm">Vereinsverwaltung</div>
        <div class="text-caption text-grey">VTB</div>
      </q-card-section>

      <q-card-section class="text-center q-gutter-md">
        <!-- Prüfung läuft -->
        <template v-if="state === 'loading'">
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

const state = ref('loading')
const errorMsg = ref('Der Link ist ungültig oder wurde bereits verwendet.')

onMounted(async () => {
  const token = route.query.token
  if (!token) {
    state.value = 'error'
    return
  }
  try {
    await auth.loginWithMagicToken(token)
    state.value = 'success'
    setTimeout(() => router.push({ name: 'dashboard' }), 1000)
  } catch (err) {
    errorMsg.value =
      err.response?.data?.detail || 'Der Link ist ungültig oder wurde bereits verwendet.'
    state.value = 'error'
  }
})
</script>
