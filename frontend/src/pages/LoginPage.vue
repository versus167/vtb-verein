<template>
  <div class="flex flex-center bg-grey-2" style="min-height: 100vh">
    <q-card style="min-width: 360px; max-width: 420px; width: 100%">
      <q-card-section class="text-center q-pb-none">
        <q-icon name="corporate_fare" size="4rem" color="primary" />
        <div class="text-h5 q-mt-sm">Vereinsverwaltung</div>
        <div class="text-caption text-grey">VTB</div>
      </q-card-section>

      <q-card-section>
        <q-form @submit.prevent="onLogin" class="q-gutter-md">
          <q-input
            v-model="username"
            label="Benutzername"
            outlined
            autofocus
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

          <div v-if="errorMsg" class="text-negative text-center text-body2">
            {{ errorMsg }}
          </div>

          <q-btn
            type="submit"
            label="Anmelden"
            color="primary"
            class="full-width"
            size="lg"
            :loading="loading"
            unelevated
          />
        </q-form>
      </q-card-section>
    </q-card>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from 'src/stores/auth'

const router = useRouter()
const auth = useAuthStore()

const username = ref('')
const password = ref('')
const showPassword = ref(false)
const loading = ref(false)
const errorMsg = ref('')

async function onLogin() {
  errorMsg.value = ''
  loading.value = true
  try {
    await auth.login(username.value, password.value)
    router.push({ name: 'dashboard' })
  } catch (err) {
    errorMsg.value = err.response?.data?.detail || 'Anmeldung fehlgeschlagen'
  } finally {
    loading.value = false
  }
}
</script>
