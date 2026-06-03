<template>
  <div class="flex flex-center bg-grey-2" style="min-height: 100vh">
    <q-card style="min-width: 360px; max-width: 420px; width: 100%">
      <q-card-section class="text-center q-pb-none">
        <q-icon name="corporate_fare" size="4rem" color="primary" />
        <div class="text-h5 q-mt-sm">Vereinsverwaltung</div>
        <div class="text-caption text-grey">VTB</div>
      </q-card-section>

      <q-card-section>
        <q-tabs v-model="tab" dense align="justify" class="q-mb-md">
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

              <q-checkbox v-model="rememberMe" label="Angemeldet bleiben (30 Tage)" :disable="loading" />

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
          </q-tab-panel>

          <!-- Magic-Link -->
          <q-tab-panel name="magic" class="q-pa-none">
            <div v-if="!magicSent" class="q-gutter-md">
              <div class="text-body2 text-grey-7">
                Gib deine E-Mail-Adresse ein. Du erhältst einen Link, mit dem du dich ohne Passwort einloggen kannst.
              </div>
              <q-form @submit.prevent="onRequestMagicLink" class="q-gutter-md">
                <q-input
                  v-model="magicEmail"
                  label="E-Mail-Adresse"
                  type="email"
                  outlined
                  autofocus
                  :disable="loading"
                  :rules="[(v) => !!v || 'Pflichtfeld']"
                >
                  <template #prepend>
                    <q-icon name="email" />
                  </template>
                </q-input>

                <div v-if="errorMsg" class="text-negative text-center text-body2">
                  {{ errorMsg }}
                </div>

                <q-btn
                  type="submit"
                  label="Login-Link anfordern"
                  color="primary"
                  class="full-width"
                  size="lg"
                  :loading="loading"
                  unelevated
                />
              </q-form>
            </div>

            <div v-else class="text-center q-gutter-md">
              <q-icon name="mark_email_read" size="4rem" color="positive" />
              <div class="text-h6">E-Mail unterwegs!</div>
              <div class="text-body2 text-grey-7">
                Falls ein Konto mit dieser Adresse existiert, haben wir dir einen Login-Link geschickt.
                Bitte prüfe auch deinen Spam-Ordner.
              </div>
              <q-btn flat label="Nochmal versuchen" color="primary" @click="magicSent = false" />
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
            @click="window.location.reload()"
          />
        </div>
      </q-card-section>
    </q-card>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from 'src/stores/auth'
import { api } from 'src/boot/axios'

const router = useRouter()
const auth = useAuthStore()

const tab = ref('password')

const username = ref('')
const password = ref('')
const showPassword = ref(false)

const rememberMe = ref(false)

const magicEmail = ref('')
const magicSent = ref(false)

const loading = ref(false)
const errorMsg = ref('')

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
