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

      <!-- Benachrichtigungen -->
      <div class="col-12">
        <q-card flat bordered>
          <q-card-section>
            <div class="text-subtitle1 text-weight-bold q-mb-sm">Benachrichtigungen</div>
            <div class="text-caption text-grey-7 q-mb-md">
              E-Mail wird immer verwendet. Matrix kann zusätzlich konfiguriert werden.
            </div>

            <div class="q-gutter-sm" style="max-width: 360px">
              <q-input
                :model-value="me?.email"
                label="E-Mail"
                outlined
                dense
                readonly
                disable
              />

              <q-input
                v-model="matrixId"
                label="Matrix-ID (optional)"
                outlined
                dense
                hint="z.B. @user:matrix.org"
                clearable
              />

              <q-select
                v-model="preferredContact"
                :options="contactOptions"
                label="Bevorzugter Kanal"
                outlined
                dense
                emit-value
                map-options
              />

              <div v-if="contactError" class="text-negative text-caption">{{ contactError }}</div>

              <div class="row q-gutter-sm">
                <q-btn
                  label="Speichern"
                  color="primary"
                  unelevated
                  :loading="savingContact"
                  @click="onSaveContact"
                />
                <q-btn
                  label="Test-Nachricht"
                  color="primary"
                  outline
                  :loading="sendingTest"
                  @click="onSendTest"
                />
              </div>
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

const matrixId = ref('')
const preferredContact = ref('email')
const contactError = ref('')
const savingContact = ref(false)
const sendingTest = ref(false)

const contactOptions = [
  { label: 'E-Mail', value: 'email' },
  { label: 'Matrix', value: 'matrix' },
]

async function load() {
  const { data } = await api.get('/api/auth/me')
  me.value = data
  matrixId.value = data.matrix_id ?? ''
  preferredContact.value = ['email', 'matrix'].includes(data.preferred_contact)
    ? data.preferred_contact
    : 'email'
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

async function onSaveContact() {
  contactError.value = ''
  savingContact.value = true
  try {
    await api.patch('/api/auth/me/contact', {
      matrix_id: matrixId.value || null,
      preferred_contact: preferredContact.value,
      expected_version: me.value.version,
    })
    await load()
    $q.notify({ type: 'positive', message: 'Benachrichtigungseinstellungen gespeichert' })
  } catch (e) {
    contactError.value = e.response?.data?.detail || 'Fehler beim Speichern'
  } finally {
    savingContact.value = false
  }
}

async function onSendTest() {
  sendingTest.value = true
  try {
    await api.post('/api/auth/me/contact/test')
    $q.notify({ type: 'positive', message: 'Test-Nachricht versendet' })
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Versand fehlgeschlagen' })
  } finally {
    sendingTest.value = false
  }
}

onMounted(load)
</script>
