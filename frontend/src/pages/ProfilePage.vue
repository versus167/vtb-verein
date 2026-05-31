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

      <!-- Meine Vereinsdaten (nur wenn Mitglied-Datensatz verknüpft) -->
      <div v-if="meinMitglied" class="col-12">
        <q-card flat bordered>
          <q-card-section>
            <div class="text-subtitle1 text-weight-bold q-mb-sm">Meine Vereinsdaten</div>
            <div class="text-caption text-grey-7 q-mb-md">
              E-Mail kann nur von einem Administrator geändert werden.
            </div>
            <div class="q-gutter-sm" style="max-width: 480px">
              <q-input v-model="mitgliedForm.telefon" label="Telefon" outlined dense />

              <div class="text-caption text-weight-medium text-grey-6 q-mt-sm">Adresse</div>
              <q-input v-model="mitgliedForm.strasse" label="Straße" outlined dense />
              <div class="row q-gutter-sm">
                <q-input v-model="mitgliedForm.plz" label="PLZ" outlined dense style="width: 100px" />
                <q-input v-model="mitgliedForm.ort" label="Ort" outlined dense class="col" />
              </div>
              <q-input v-model="mitgliedForm.land" label="Land" outlined dense />

              <div class="text-caption text-weight-medium text-grey-6 q-mt-sm">Bankverbindung</div>
              <q-input v-model="mitgliedForm.iban" label="IBAN" outlined dense />
              <q-input v-model="mitgliedForm.bic" label="BIC" outlined dense />
              <q-input v-model="mitgliedForm.kontoinhaber" label="Kontoinhaber" outlined dense />

              <div v-if="mitgliedError" class="text-negative text-caption">{{ mitgliedError }}</div>
              <q-btn label="Speichern" color="primary" unelevated :loading="savingMitglied" @click="onSaveMitglied" />
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
const roleLabels = { admin: 'Administrator', user: 'Bearbeiter', readonly: 'Nur Lesen', mitglied: 'Mitglied' }

const meinMitglied = ref(null)
const mitgliedForm = ref({})
const mitgliedError = ref('')
const savingMitglied = ref(false)

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
  try {
    const { data: m } = await api.get('/api/personen/mein-mitglied')
    meinMitglied.value = m
    if (m) {
      mitgliedForm.value = {
        telefon: m.telefon ?? '',
        strasse: m.strasse ?? '',
        plz: m.plz ?? '',
        ort: m.ort ?? '',
        land: m.land ?? '',
        iban: m.iban ?? '',
        bic: m.bic ?? '',
        kontoinhaber: m.kontoinhaber ?? '',
      }
    }
  } catch { /* kein Mitglied-Datensatz → ignorieren */ }
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
    await load()
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

async function onSaveMitglied() {
  mitgliedError.value = ''
  savingMitglied.value = true
  try {
    await api.put('/api/personen/mein-mitglied', {
      ...mitgliedForm.value,
      expected_version: meinMitglied.value.version,
    })
    await load()
    $q.notify({ type: 'positive', message: 'Vereinsdaten gespeichert' })
  } catch (e) {
    mitgliedError.value = e.response?.data?.detail || 'Fehler beim Speichern'
  } finally {
    savingMitglied.value = false
  }
}

onMounted(load)
</script>
