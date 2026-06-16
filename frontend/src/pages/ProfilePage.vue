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

      <!-- Meine Berechtigungen (read-only) -->
      <div class="col-12">
        <q-card flat bordered>
          <q-card-section>
            <div class="text-subtitle1 text-weight-bold q-mb-sm">Meine Berechtigungen</div>
            <div class="text-caption text-grey-7 q-mb-md">
              Diese Rechte ergeben sich aus deinen Funktionen im Verein.
              Änderungen kann nur die Vereinsverwaltung vornehmen.
            </div>

            <q-banner v-if="me?.role === 'admin'" class="bg-blue-1 rounded-borders q-mb-md">
              <template #avatar><q-icon name="shield" color="blue" /></template>
              Als Administrator hast du uneingeschränkten Zugriff auf alle Funktionen.
            </q-banner>

            <template v-if="me?.role !== 'admin' && permGroups.length">
              <div v-for="group in permGroups" :key="group.label" class="q-mb-md">
                <div class="row items-center q-mb-xs">
                  <q-icon :name="group.icon" color="primary" size="sm" />
                  <span class="text-subtitle2 text-weight-medium q-ml-sm">{{ group.label }}</span>
                </div>
                <q-list dense>
                  <q-item v-for="perm in group.perms" :key="perm.key" class="q-px-none">
                    <q-item-section avatar style="min-width: 32px">
                      <q-icon name="check_circle" color="positive" size="xs" />
                    </q-item-section>
                    <q-item-section>{{ perm.label }}</q-item-section>
                    <q-item-section side>
                      <div class="row q-gutter-xs justify-end">
                        <q-badge
                          v-for="(c, i) in perm.origins" :key="i"
                          color="teal-1" text-color="teal-9"
                        >{{ c }}</q-badge>
                      </div>
                    </q-item-section>
                  </q-item>
                </q-list>
              </div>
            </template>
            <div v-else-if="me?.role !== 'admin'" class="text-caption text-grey-6">
              Aktuell sind dir keine besonderen Berechtigungen zugeordnet.
            </div>
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
              <q-input v-model="mitgliedForm.iban" label="IBAN" outlined dense :rules="[ibanRule]" />
              <q-input v-model="mitgliedForm.bic" label="BIC" outlined dense />
              <q-input v-model="mitgliedForm.kontoinhaber" label="Kontoinhaber" outlined dense />

              <div v-if="mitgliedError" class="text-negative text-caption">{{ mitgliedError }}</div>
              <q-btn label="Speichern" color="primary" unelevated :loading="savingMitglied" @click="onSaveMitglied" />
            </div>
          </q-card-section>
        </q-card>
      </div>

      <!-- Meine Geräte / angemeldete Sessions (Ticket #24) -->
      <div class="col-12">
        <q-card flat bordered>
          <q-card-section>
            <div class="row items-center justify-between q-mb-sm">
              <div class="text-subtitle1 text-weight-bold">Meine Geräte</div>
              <q-btn
                v-if="otherSessionsCount > 0"
                label="Alle anderen abmelden"
                icon="logout"
                color="negative"
                outline dense no-caps
                :loading="revokingOthers"
                @click="onRevokeOthers"
              />
            </div>
            <div class="text-caption text-grey-7 q-mb-md">
              Hier siehst du, auf welchen Geräten du angemeldet bist. Kommt dir etwas
              merkwürdig vor, kannst du einzelne Geräte oder alle anderen auf einmal abmelden.
            </div>

            <q-inner-loading :showing="loadingSessions" />

            <q-banner v-if="!loadingSessions && sessions.length === 0" class="bg-grey-2 rounded-borders">
              Keine aktiven Sitzungen gefunden.
            </q-banner>

            <q-list v-else separator>
              <q-item v-for="s in sessions" :key="s.id">
                <q-item-section avatar>
                  <q-icon :name="deviceIcon(s)" size="sm" :color="s.current ? 'primary' : 'grey-7'" />
                </q-item-section>
                <q-item-section>
                  <q-item-label>
                    {{ s.device_label || 'Unbekanntes Gerät' }}
                    <q-badge v-if="s.current" color="primary" label="Dieses Gerät" class="q-ml-sm" />
                  </q-item-label>
                  <q-item-label caption>
                    Zuletzt aktiv: {{ fmt(s.last_seen_at) }}<template v-if="s.ip"> · IP {{ s.ip }}</template>
                  </q-item-label>
                  <q-item-label caption>Angemeldet seit {{ fmt(s.created_at) }}</q-item-label>
                </q-item-section>
                <q-item-section side>
                  <q-btn
                    flat round dense icon="logout" color="negative"
                    :loading="revokingId === s.id"
                    @click="onRevoke(s)"
                  >
                    <q-tooltip>{{ s.current ? 'Abmelden (dieses Gerät)' : 'Dieses Gerät abmelden' }}</q-tooltip>
                  </q-btn>
                </q-item-section>
              </q-item>
            </q-list>
          </q-card-section>
        </q-card>
      </div>

    </div>
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { useAuthStore } from 'src/stores/auth'
import { ibanRule, normalizeIban, isValidIban } from 'src/utils/iban'

const $q = useQuasar()
const auth = useAuthStore()
const router = useRouter()

const me = ref(null)
const roleLabels = { admin: 'Administrator', mitglied: 'Mitglied' }

// Eigene Berechtigungen (read-only Anzeige)
const permData = ref(null)

function originChips(key) {
  const out = []
  for (const s of permData.value?.sources?.[key] || []) {
    if (s.typ === 'sockel') out.push('Standard')
    else if (s.typ === 'funktion') {
      out.push(s.abteilung_name ? `${s.funktion_name} (${s.abteilung_name})` : s.funktion_name)
    } else if (s.typ === 'override' && s.effect === 'grant') out.push('individuell')
  }
  return [...new Set(out)]
}

// Nur tatsächlich wirksame Rechte, gruppiert, mit Herkunft.
const permGroups = computed(() => {
  if (!permData.value) return []
  const effective = new Set((permData.value.effective || []).map(e => e.key))
  return (permData.value.groups || [])
    .map(g => ({
      label: g.label,
      icon: g.icon,
      perms: g.permissions
        .filter(p => effective.has(p.key))
        .map(p => ({ key: p.key, label: p.label, origins: originChips(p.key) })),
    }))
    .filter(g => g.perms.length > 0)
})

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
    const { data: perms } = await api.get('/api/auth/me/permissions')
    permData.value = perms
  } catch { /* Berechtigungen optional – Anzeige einfach weglassen */ }
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
  mitgliedForm.value.iban = normalizeIban(mitgliedForm.value.iban)
  if (mitgliedForm.value.iban && !isValidIban(mitgliedForm.value.iban)) {
    mitgliedError.value = 'Ungültige IBAN – bitte Format und Prüfziffer prüfen.'
    return
  }
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

// ---- Meine Geräte / Sessions (Ticket #24) ----
const sessions = ref([])
const loadingSessions = ref(false)
const revokingId = ref(null)
const revokingOthers = ref(false)

const otherSessionsCount = computed(() => sessions.value.filter(s => !s.current).length)

function deviceIcon(s) {
  const ua = (s.user_agent || '').toLowerCase()
  if (/ipad|tablet/.test(ua)) return 'tablet'
  if (/android|iphone|ipod|mobile/.test(ua)) return 'smartphone'
  return 'computer'
}

function fmt(ts) {
  if (!ts) return '–'
  const d = new Date(ts)
  return isNaN(d.getTime())
    ? ts
    : d.toLocaleString('de-DE', { dateStyle: 'medium', timeStyle: 'short' })
}

async function loadSessions() {
  loadingSessions.value = true
  try {
    const { data } = await api.get('/api/auth/me/sessions')
    sessions.value = data
  } catch { /* Anzeige optional */ } finally {
    loadingSessions.value = false
  }
}

function logoutSelf() {
  auth.logout()
  router.push({ name: 'login' })
}

async function onRevoke(s) {
  if (s.current) {
    $q.dialog({
      title: 'Dieses Gerät abmelden?',
      message: 'Du wirst hier abgemeldet und musst dich neu anmelden.',
      cancel: true,
      persistent: true,
    }).onOk(async () => {
      try {
        await api.delete(`/api/auth/me/sessions/${s.id}`)
        logoutSelf()
      } catch (e) {
        $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Abmelden fehlgeschlagen' })
      }
    })
    return
  }
  revokingId.value = s.id
  try {
    await api.delete(`/api/auth/me/sessions/${s.id}`)
    await loadSessions()
    $q.notify({ type: 'positive', message: 'Gerät abgemeldet' })
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Abmelden fehlgeschlagen' })
  } finally {
    revokingId.value = null
  }
}

function onRevokeOthers() {
  $q.dialog({
    title: 'Alle anderen Geräte abmelden?',
    message: 'Alle Sitzungen außer dieser werden beendet.',
    cancel: true,
    persistent: true,
  }).onOk(async () => {
    revokingOthers.value = true
    try {
      const { data } = await api.post('/api/auth/me/sessions/revoke-others')
      await loadSessions()
      $q.notify({ type: 'positive', message: `${data.revoked} Gerät(e) abgemeldet` })
    } catch (e) {
      $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Abmelden fehlgeschlagen' })
    } finally {
      revokingOthers.value = false
    }
  })
}

onMounted(() => {
  load()
  loadSessions()
})
</script>
