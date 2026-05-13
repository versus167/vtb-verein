<template>
  <q-page padding>
    <div class="text-h5 q-mb-lg">Mein Profil</div>

    <div class="row q-col-gutter-md" style="max-width: 680px">

      <!-- Profil-Info -->
      <div class="col-12">
        <q-card flat bordered>
          <q-card-section>
            <div class="text-subtitle1 text-weight-bold q-mb-md">Profil-Informationen</div>
            <q-list dense>
              <q-item>
                <q-item-section side style="min-width: 140px">
                  <span class="text-weight-medium">Benutzername</span>
                </q-item-section>
                <q-item-section>{{ me?.username }}</q-item-section>
              </q-item>
              <q-item>
                <q-item-section side style="min-width: 140px">
                  <span class="text-weight-medium">E-Mail</span>
                </q-item-section>
                <q-item-section>{{ me?.email }}</q-item-section>
              </q-item>
              <q-item>
                <q-item-section side style="min-width: 140px">
                  <span class="text-weight-medium">Rolle</span>
                </q-item-section>
                <q-item-section>{{ roleLabels[me?.role] ?? me?.role }}</q-item-section>
              </q-item>
              <q-item>
                <q-item-section side style="min-width: 140px">
                  <span class="text-weight-medium">Letzter Login</span>
                </q-item-section>
                <q-item-section>{{ me?.last_login ?? 'Noch nie' }}</q-item-section>
              </q-item>
            </q-list>
          </q-card-section>
        </q-card>
      </div>

      <!-- Passwort ändern -->
      <div class="col-12">
        <q-card flat bordered>
          <q-card-section>
            <div class="text-subtitle1 text-weight-bold q-mb-sm">Passwort ändern</div>
            <div class="text-caption text-grey-7 q-mb-md">
              Mindestens 6 Zeichen. Du kannst dich auch weiterhin per Magic-Link anmelden.
            </div>

            <div class="q-gutter-sm" style="max-width: 360px">
              <q-input
                v-model="pw1"
                label="Neues Passwort"
                outlined
                dense
                :type="showPw ? 'text' : 'password'"
                :rules="[(v) => !v || v.length >= 6 || 'Mindestens 6 Zeichen']"
              >
                <template #append>
                  <q-icon
                    :name="showPw ? 'visibility_off' : 'visibility'"
                    class="cursor-pointer"
                    @click="showPw = !showPw"
                  />
                </template>
              </q-input>

              <q-input
                v-model="pw2"
                label="Passwort wiederholen"
                outlined
                dense
                :type="showPw ? 'text' : 'password'"
                :rules="[(v) => !v || v === pw1 || 'Stimmt nicht überein']"
              />

              <div v-if="pwError" class="text-negative text-caption">{{ pwError }}</div>

              <q-btn
                label="Passwort ändern"
                icon="vpn_key"
                color="primary"
                unelevated
                :loading="saving"
                :disable="!pw1 || !pw2"
                @click="onChangePassword"
              />
            </div>
          </q-card-section>
        </q-card>
      </div>

    </div>
  </q-page>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { useAuthStore } from 'src/stores/auth'

const $q = useQuasar()
const auth = useAuthStore()

const me = ref(null)
const roleLabels = { admin: 'Administrator', user: 'Bearbeiter', readonly: 'Nur Lesen' }

const pw1 = ref('')
const pw2 = ref('')
const showPw = ref(false)
const pwError = ref('')
const saving = ref(false)

async function load() {
  const { data } = await api.get('/api/auth/me')
  me.value = data
}

async function onChangePassword() {
  if (pw1.value !== pw2.value) {
    pwError.value = 'Passwörter stimmen nicht überein'
    return
  }
  pwError.value = ''
  saving.value = true
  try {
    await api.post('/api/auth/me/password', { new_password: pw1.value })
    pw1.value = ''
    pw2.value = ''
    $q.notify({ type: 'positive', message: 'Passwort erfolgreich geändert' })
  } catch (e) {
    pwError.value = e.response?.data?.detail || 'Fehler beim Ändern'
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>
