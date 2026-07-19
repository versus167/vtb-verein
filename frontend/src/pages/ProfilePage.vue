<template>
  <q-page padding>
    <div class="text-h5 q-mb-md">Mein Profil</div>

    <!-- Profil-Informationen: die Kopfkarte bleibt bewusst immer offen -->
    <q-card flat bordered class="vtb-karte q-mb-md">
      <q-card-section class="row items-center no-wrap">
        <div class="col">
          <div class="text-h6 text-weight-bold profil-kopf__name">
            {{ me?.display_name || me?.username || '…' }}
          </div>
          <div class="row items-center q-gutter-xs q-mt-sm">
            <span class="vtb-pill">@{{ me?.username }}</span>
            <span class="vtb-pill" :class="{ 'vtb-pill--achtung': me?.role === 'admin' }">
              {{ roleLabels[me?.role] ?? me?.role }}
            </span>
          </div>
        </div>
        <div class="col-auto q-ml-md">
          <!-- Platzhalter für das Profilbild aus einem der nächsten Updates.
               Antippbar, weil der Tooltip am Handy nie erscheint und die
               Kamera-Scheibe sonst wie ein toter Upload-Button wirkt. -->
          <div class="vtb-icon profil-avatar cursor-pointer" @click="onAvatarClick">
            <span class="profil-avatar__initialen">{{ initialen }}</span>
            <q-icon name="photo_camera" size="14px" class="profil-avatar__badge" />
            <q-tooltip>Profilbild – folgt in einem der nächsten Updates</q-tooltip>
          </div>
        </div>
      </q-card-section>

      <q-separator />

      <q-card-section class="profil-fakten">
        <div class="profil-fakt">
          <q-icon name="mail" size="20px" />
          <div class="profil-fakt__text">
            <div class="text-caption text-grey-7">E-Mail</div>
            <div class="profil-fakt__wert">{{ me?.email || '–' }}</div>
          </div>
        </div>
        <div class="profil-fakt">
          <q-icon name="schedule" size="20px" />
          <div class="profil-fakt__text">
            <div class="text-caption text-grey-7">Letzter Login</div>
            <div class="profil-fakt__wert">{{ me?.last_login ? fmt(me.last_login) : 'Noch nie' }}</div>
          </div>
        </div>
      </q-card-section>
    </q-card>

    <div class="row q-col-gutter-md">
      <!-- Am Handy stapeln beide Spalten in genau dieser Reihenfolge -->
      <div class="col-12 col-md-6 profil-spalte">

        <!-- Meine Kontaktdaten (nur wenn Mitglied-Datensatz verknüpft) -->
        <ProfilPanel
          v-if="meinMitglied"
          icon="home"
          titel="Meine Kontaktdaten"
          :info="kontaktdatenInfo"
        >
          <div class="text-caption text-grey-7 q-mb-md">
            E-Mail kann nur von einem Administrator geändert werden.
          </div>
          <div class="profil-stapel">
            <q-input v-model="mitgliedForm.telefon" label="Telefon" outlined dense />
            <q-input v-model="mitgliedForm.strasse" label="Straße" outlined dense />
            <div class="profil-reihe">
              <q-input v-model="mitgliedForm.plz" label="PLZ" outlined dense class="profil-feld-plz" />
              <q-input v-model="mitgliedForm.ort" label="Ort" outlined dense class="profil-feld-breit" />
            </div>
            <q-input v-model="mitgliedForm.land" label="Land" outlined dense />

            <div v-if="mitgliedError" class="vtb-fehler">
              <q-icon name="error" size="20px" />
              <span>{{ mitgliedError }}</span>
            </div>
            <q-btn
              class="full-width"
              label="Speichern"
              color="primary"
              unelevated
              :loading="savingMitglied"
              @click="onSaveMitglied"
            />
          </div>
        </ProfilPanel>

        <!-- Meine Bankverbindung -->
        <ProfilPanel
          v-if="meinMitglied"
          icon="account_balance"
          titel="Meine Bankverbindung"
          :info="bankInfo"
        >
          <div class="text-caption text-grey-7 q-mb-md">
            Bankverbindung für den Beitragseinzug.
          </div>
          <div class="profil-stapel">
            <q-input v-model="mitgliedForm.iban" label="IBAN" outlined dense :rules="[ibanRule]" />
            <q-input v-model="mitgliedForm.bic" label="BIC" outlined dense />
            <q-input v-model="mitgliedForm.kontoinhaber" label="Kontoinhaber" outlined dense />

            <div v-if="bankError || mitgliedError" class="vtb-fehler">
              <q-icon name="error" size="20px" />
              <span>{{ bankError || mitgliedError }}</span>
            </div>
            <q-btn
              class="full-width"
              label="Speichern"
              color="primary"
              unelevated
              :loading="savingMitglied"
              @click="onSaveMitglied"
            />
          </div>
        </ProfilPanel>

        <!-- Passwort ändern -->
        <ProfilPanel
          icon="vpn_key"
          titel="Passwort ändern"
          info="Mindestens 6 Zeichen · Magic-Link bleibt möglich"
        >
          <div class="text-caption text-grey-7 q-mb-md">
            Mindestens 6 Zeichen. Du kannst dich auch weiterhin per Magic-Link anmelden.
          </div>

          <div class="profil-stapel">
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

            <div v-if="pwError" class="vtb-fehler">
              <q-icon name="error" size="20px" />
              <span>{{ pwError }}</span>
            </div>

            <q-btn
              class="full-width"
              label="Passwort ändern"
              icon="vpn_key"
              color="primary"
              unelevated
              :loading="saving"
              :disable="!pw1 || !pw2"
              @click="onChangePassword"
            />
          </div>
        </ProfilPanel>
      </div>

      <div class="col-12 col-md-6 profil-spalte">

        <!-- Benachrichtigungen -->
        <ProfilPanel
          icon="notifications"
          titel="Benachrichtigungen"
          :info="benachrichtigungInfo"
        >
          <div class="text-caption text-grey-7 q-mb-md">
            E-Mail wird immer verwendet. Matrix kann zusätzlich konfiguriert werden.
          </div>

          <div class="profil-stapel">
            <q-input :model-value="me?.email" label="E-Mail" outlined dense readonly disable />

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
              label="Hauptkanal"
              outlined
              dense
              emit-value
              map-options
              hint="Geräte mit aktivem Push werden immer zusätzlich benachrichtigt."
            />

            <!-- Web-Push je Gerät (#96) -->
            <div v-if="pushSupported" class="q-mt-sm">
              <q-toggle
                :model-value="pushSubscribed"
                :disable="pushBusy || !pushConfigured"
                label="Push auf diesem Gerät aktivieren"
                @update:model-value="onTogglePush"
              />
              <div class="text-caption text-grey-7">
                <span v-if="!pushConfigured">Push ist serverseitig noch nicht konfiguriert.</span>
                <span v-else-if="pushSubscribed">Dieses Gerät empfängt Push-Benachrichtigungen.</span>
                <span v-else>Aktivieren, um auf diesem Gerät Push-Benachrichtigungen zu erhalten.</span>
              </div>
            </div>

            <div v-if="contactError" class="vtb-fehler">
              <q-icon name="error" size="20px" />
              <span>{{ contactError }}</span>
            </div>

            <div class="profil-reihe profil-reihe--btn">
              <q-btn
                class="profil-feld-breit"
                label="Speichern"
                color="primary"
                unelevated
                :loading="savingContact"
                @click="onSaveContact"
              />
              <q-btn
                class="profil-feld-breit"
                label="Test-Nachricht"
                color="primary"
                outline
                :loading="sendingTest"
                @click="onSendTest"
              />
            </div>
          </div>
        </ProfilPanel>

        <!-- Meine Geräte / angemeldete Sessions (Ticket #24) -->
        <ProfilPanel icon="devices" titel="Meine Geräte" :info="geraeteInfo">
          <div class="text-caption text-grey-7 q-mb-md">
            Hier siehst du, auf welchen Geräten du angemeldet bist. Kommt dir etwas
            merkwürdig vor, kannst du einzelne Geräte oder alle anderen auf einmal abmelden.
          </div>

          <q-btn
            v-if="otherSessionsCount > 0"
            class="full-width q-mb-md"
            label="Alle anderen abmelden"
            icon="logout"
            color="negative"
            outline
            no-caps
            :loading="revokingOthers"
            @click="onRevokeOthers"
          />

          <q-inner-loading :showing="loadingSessions" />

          <q-banner v-if="!loadingSessions && sessions.length === 0" class="bg-grey-2 text-grey-9 rounded-borders">
            Keine aktiven Sitzungen gefunden.
          </q-banner>

          <q-list v-else separator>
            <q-item v-for="s in sessions" :key="s.id" class="q-px-none">
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
        </ProfilPanel>

        <!-- Mein Zugang (Schließanlage, Self-Service) -->
        <ProfilPanel
          v-if="zugangHasData"
          icon="meeting_room"
          titel="Mein Zugang"
          :info="zugangInfo"
        >
          <template v-if="meinZugang.chips.length">
            <div class="text-caption text-weight-medium">Meine Chips</div>
            <q-list dense>
              <q-item v-for="c in meinZugang.chips" :key="'c' + c.id" class="q-px-none">
                <q-item-section>
                  <q-item-label>{{ c.bezeichnung || ('Chip #' + c.id) }}
                    <q-chip dense size="sm" outline>Nr. {{ c.kartennummer }}</q-chip>
                    <q-chip v-if="c.status !== 'aktiv'" dense size="sm" color="orange-3">{{ c.status }}</q-chip>
                  </q-item-label>
                </q-item-section>
              </q-item>
            </q-list>
          </template>

          <template v-if="meinZugang.berechtigungen.length">
            <div class="text-caption text-weight-medium q-mt-sm">Öffnet diese Türen</div>
            <q-list dense>
              <q-item v-for="b in meinZugang.berechtigungen" :key="'b' + b.id" class="q-px-none">
                <q-item-section>
                  <q-item-label>{{ b.schloss_name }}</q-item-label>
                  <q-item-label caption v-if="b.gueltig_bis">gültig bis {{ fmt(b.gueltig_bis) }}</q-item-label>
                </q-item-section>
                <q-item-section side>
                  <q-chip dense size="sm" :color="b.sync_status === 'aktiv' ? 'green-3' : 'grey-3'">
                    {{ b.sync_status }}</q-chip>
                </q-item-section>
              </q-item>
            </q-list>
          </template>

          <template v-if="meinZugang.app_berechtigungen.length">
            <div class="text-caption text-weight-medium q-mt-sm">Befristete App-Öffnung</div>
            <q-list dense>
              <q-item v-for="a in meinZugang.app_berechtigungen" :key="'a' + a.id" class="q-px-none">
                <q-item-section>
                  <q-item-label>{{ a.schloss_name }}</q-item-label>
                  <q-item-label caption>
                    {{ a.gueltig_von ? fmt(a.gueltig_von) : 'ab sofort' }}
                    – {{ a.gueltig_bis ? fmt(a.gueltig_bis) : 'unbefristet' }}
                  </q-item-label>
                </q-item-section>
              </q-item>
            </q-list>
          </template>

          <template v-if="meinZugang.zutritte.length">
            <div class="text-caption text-weight-medium q-mt-sm">Letzte Zutritte</div>
            <q-list dense>
              <q-item v-for="l in meinZugang.zutritte" :key="'l' + l.id" class="q-px-none">
                <q-item-section avatar>
                  <q-icon :name="l.erfolg ? 'check_circle' : 'cancel'"
                    :color="l.erfolg ? 'positive' : 'negative'" size="18px" />
                </q-item-section>
                <q-item-section>
                  <q-item-label>{{ l.schloss_name }}</q-item-label>
                  <q-item-label caption>{{ fmt(l.lock_date) }} · {{ l.methode }}</q-item-label>
                </q-item-section>
              </q-item>
            </q-list>
          </template>
        </ProfilPanel>

        <!-- Meine Berechtigungen (read-only) -->
        <ProfilPanel icon="shield" titel="Meine Berechtigungen" :info="rechteInfo">
          <div class="text-caption text-grey-7 q-mb-md">
            Diese Rechte ergeben sich aus deinen Funktionen im Verein.
            Änderungen kann nur die Vereinsverwaltung vornehmen.
          </div>

          <q-banner v-if="me?.role === 'admin'" class="bg-blue-1 text-blue-10 rounded-borders">
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
        </ProfilPanel>
      </div>
    </div>
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { usePageRefresh } from 'src/composables/useRefresh'
import { usePush } from 'src/composables/usePush'
import { useRouter } from 'vue-router'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { useAuthStore } from 'src/stores/auth'
import { ibanRule, normalizeIban, isValidIban } from 'src/utils/iban'
import { formatDateTime } from 'src/utils/datetime'
import ProfilPanel from 'components/ProfilPanel.vue'

const $q = useQuasar()
const auth = useAuthStore()
const router = useRouter()

const me = ref(null)
const roleLabels = { admin: 'Administrator', mitglied: 'Mitglied' }

// Initialen als Platzhalter, bis es echte Profilbilder gibt.
const initialen = computed(() => {
  const teile = (me.value?.display_name || me.value?.username || '').trim().split(/\s+/).filter(Boolean)
  if (!teile.length) return '?'
  if (teile.length === 1) return teile[0].slice(0, 2).toUpperCase()
  return (teile[0][0] + teile[teile.length - 1][0]).toUpperCase()
})

function onAvatarClick() {
  $q.notify({ type: 'info', message: 'Profilbilder folgen in einem der nächsten Updates.' })
}

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

// Self-Service Schließanlage (eigene Chips/Türen/Zutritte)
const meinZugang = ref({ verknuepft: false, chips: [], berechtigungen: [], app_berechtigungen: [], zutritte: [] })
const zugangHasData = computed(() => {
  const z = meinZugang.value
  return !!(z && (z.chips.length || z.berechtigungen.length || z.app_berechtigungen.length || z.zutritte.length))
})
const mitgliedError = ref('')
const bankError = ref('')
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

// Web-Push (#96)
const push = usePush()
const pushSupported = ref(false)
const pushConfigured = ref(false)
const pushSubscribed = ref(false)
const pushBusy = ref(false)

const contactOptions = computed(() => {
  const opts = [
    { label: 'E-Mail', value: 'email' },
    { label: 'Matrix', value: 'matrix' },
  ]
  // 'Nur Push' nur anbieten, wenn serverseitig konfiguriert (sonst liefe es ins Leere → E-Mail)
  if (pushConfigured.value) opts.push({ label: 'Nur Push (keine E-Mail)', value: 'push' })
  return opts
})

// ---- Kurzfassungen für die zugeklappten Panel-Köpfe ----

const kontaktdatenInfo = computed(() => {
  const f = mitgliedForm.value
  const teile = [f.strasse, [f.plz, f.ort].filter(Boolean).join(' ')].filter(Boolean)
  return teile.length ? teile.join(' · ') : 'Adresse und Telefon hinterlegen'
})

const bankInfo = computed(() => {
  const iban = normalizeIban(mitgliedForm.value.iban)
  if (!iban) return 'Noch keine Bankverbindung hinterlegt'
  return iban.length > 8 ? `${iban.slice(0, 4)} •••• ${iban.slice(-4)}` : iban
})

const benachrichtigungInfo = computed(() => {
  const haupt = { email: 'E-Mail', matrix: 'Matrix', push: 'Nur Push' }[preferredContact.value] || 'E-Mail'
  if (preferredContact.value !== 'push' && pushSubscribed.value) return `${haupt} · Push auf diesem Gerät`
  return haupt
})

const geraeteInfo = computed(() => {
  if (loadingSessions.value) return 'wird geladen …'
  const n = sessions.value.length
  return n === 1 ? '1 Gerät angemeldet' : `${n} Geräte angemeldet`
})

const zugangInfo = computed(() => {
  const z = meinZugang.value
  const teile = []
  if (z.chips.length) teile.push(z.chips.length === 1 ? '1 Chip' : `${z.chips.length} Chips`)
  const tueren = z.berechtigungen.length + z.app_berechtigungen.length
  if (tueren) teile.push(tueren === 1 ? '1 Tür' : `${tueren} Türen`)
  return teile.length ? teile.join(' · ') : 'Chips, Türen und Zutritte'
})

const rechteInfo = computed(() => {
  if (me.value?.role === 'admin') return 'Administrator – voller Zugriff'
  const n = permGroups.value.reduce((s, g) => s + g.perms.length, 0)
  if (!n) return 'Keine besonderen Rechte'
  return n === 1 ? '1 Recht aus deinen Funktionen' : `${n} Rechte aus deinen Funktionen`
})

async function load() {
  const { data } = await api.get('/api/auth/me')
  me.value = data
  matrixId.value = data.matrix_id ?? ''
  preferredContact.value = ['email', 'matrix', 'push'].includes(data.preferred_contact)
    ? data.preferred_contact
    : 'email'
  await refreshPushState()
  try {
    const { data: perms } = await api.get('/api/auth/me/permissions')
    permData.value = perms
  } catch { /* Berechtigungen optional – Anzeige einfach weglassen */ }
  try {
    const { data: mz } = await api.get('/api/schliessanlage/mein-zugang')
    meinZugang.value = mz
  } catch { /* Schließanlage optional – Panel bleibt ausgeblendet */ }
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

async function refreshPushState() {
  pushSupported.value = push.isSupported()
  if (!pushSupported.value) return
  try {
    const status = await push.serverStatus()
    pushConfigured.value = !!status.configured
    pushSubscribed.value = await push.isSubscribed()
  } catch { /* Push-Status optional – Toggle bleibt aus */ }
}

async function onTogglePush(value) {
  pushBusy.value = true
  try {
    if (value) {
      await push.subscribe()
      pushSubscribed.value = true
      $q.notify({ type: 'positive', message: 'Push auf diesem Gerät aktiviert' })
    } else {
      await push.unsubscribe()
      pushSubscribed.value = false
      // Bevorzugten Kanal nicht auf einem toten Push-Gerät stehen lassen
      if (preferredContact.value === 'push') preferredContact.value = 'email'
      $q.notify({ type: 'info', message: 'Push auf diesem Gerät deaktiviert' })
    }
  } catch (e) {
    pushSubscribed.value = await push.isSubscribed()
    $q.notify({ type: 'negative', message: e.message || 'Push konnte nicht geändert werden' })
  } finally {
    pushBusy.value = false
  }
}

// Adresse und Bankverbindung stehen in getrennten Panels, liegen aber im selben
// Mitglied-Datensatz: der PUT ersetzt immer alle Felder, also schickt jeder der
// beiden Speichern-Buttons das komplette Formular.
async function onSaveMitglied() {
  mitgliedError.value = ''
  bankError.value = ''
  mitgliedForm.value.iban = normalizeIban(mitgliedForm.value.iban)
  if (mitgliedForm.value.iban && !isValidIban(mitgliedForm.value.iban)) {
    bankError.value = 'Ungültige IBAN – bitte Format und Prüfziffer prüfen.'
    // Kann aus dem Vereinsdaten-Panel ausgelöst werden, während das Bank-Panel
    // zugeklappt ist – der Hinweis dort allein bliebe unsichtbar.
    $q.notify({ type: 'negative', message: 'Ungültige IBAN – bitte unter „Meine Bankverbindung“ prüfen.' })
    return
  }
  savingMitglied.value = true
  try {
    await api.put('/api/personen/mein-mitglied', {
      ...mitgliedForm.value,
      expected_version: meinMitglied.value.version,
    })
    await load()
    $q.notify({ type: 'positive', message: 'Gespeichert' })
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
  return formatDateTime(ts)
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

usePageRefresh(() => Promise.all([load(), loadSessions()]))
onMounted(() => {
  load()
  loadSessions()
})
</script>

<style scoped lang="scss">
// Panels innerhalb einer Spalte; der Abstand zwischen den Spalten kommt vom
// q-col-gutter des Rows.
.profil-spalte > * + * {
  margin-top: 16px;
}

// Formular-Stapel bewusst mit flex/gap statt q-gutter-*: Quasars Gutter setzen
// negative Außenränder am Container und positive an den Kindern. Verschachtelt
// (Zeile-im-Stapel) addieren die sich und rücken das innere Feld ein; volle
// Breite ragt zudem über den Container hinaus.
.profil-stapel {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.profil-reihe {
  display: flex;
  gap: 8px;
  align-items: flex-start;
}
.profil-reihe--btn {
  flex-wrap: wrap;
}
.profil-feld-plz {
  flex: 0 0 110px;
}
.profil-feld-breit {
  flex: 1 1 0;
  min-width: 0;
}

.profil-kopf__name {
  line-height: 1.2;
  overflow-wrap: anywhere;
}

// Foto-Platzhalter: gestrichelter Ring signalisiert „kommt noch". Farbe und
// Fläche erbt er von .vtb-icon (Gelb auf Blau, Hellblau im Dark Mode).
.profil-avatar {
  width: 72px;
  height: 72px;
  border: 2px dashed currentColor;
  position: relative;
}
.profil-avatar__initialen {
  font-size: 24px;
  font-weight: 700;
  letter-spacing: 1px;
}
.profil-avatar__badge {
  position: absolute;
  right: -2px;
  bottom: -2px;
  padding: 4px;
  border-radius: 50%;
}
body:not(.body--dark) .profil-avatar__badge {
  background: $vtb-blau-btn-dark;
  color: $vtb-gelb;
}
body.body--dark .profil-avatar__badge {
  background: $vtb-blau-btn-dark;
  color: #fff;
}

// Fakten (E-Mail, letzter Login): am Handy untereinander, ab Tablet nebeneinander.
.profil-fakten {
  display: grid;
  grid-template-columns: 1fr;
  gap: 12px;
}
@media (min-width: 600px) {
  .profil-fakten {
    grid-template-columns: 1fr 1fr;
  }
}
.profil-fakt {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.profil-fakt__text {
  min-width: 0;
}
.profil-fakt__wert {
  font-weight: 500;
  overflow-wrap: anywhere;
}
</style>
