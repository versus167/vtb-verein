<template>
  <q-page class="q-pa-md">
    <div class="row items-center q-mb-md">
      <div class="text-h5">Termine</div>
      <q-space />
      <q-btn v-if="darfVerwalten && tab !== 'meine'" color="primary" unelevated
        icon="add" label="Neuer Termin" :round="$q.screen.lt.sm" @click="openCreate" />
    </div>

    <!-- Meine Termine + ein Tab je Mannschaft -->
    <q-tabs v-model="tab" dense align="left" active-color="primary"
      indicator-color="primary" class="text-grey-7" :breakpoint="0">
      <q-tab name="meine" label="Meine Termine" />
      <q-tab v-for="m in teams" :key="m.id" :name="m.id" :label="teamLabel(m)" />
    </q-tabs>
    <q-separator class="q-mb-md" />

    <div class="row items-center q-mb-md">
      <q-toggle v-model="vergangene" label="Vergangene anzeigen" dense />
    </div>

    <q-inner-loading :showing="loading" />
    <div v-if="!loading && termine.length === 0" class="text-grey text-center q-py-xl">
      Keine Termine{{ vergangene ? '' : ' ab heute' }}.
    </div>

    <!-- Card-Liste (nach beginn sortiert; Datum steckt in der Card) -->
    <div class="column q-gutter-md">
      <TerminCard v-for="t in termine" :key="t.id" :termin="t"
        :darf-verwalten="kannVerwalten(t)"
        @bearbeiten="openEdit" @absagen="setStatus($event, 'absagen')"
        @reaktivieren="setStatus($event, 'reaktivieren')" @loeschen="confirmDelete"
        @reload="loadTermine" />
    </div>

    <!-- Termin anlegen/bearbeiten -->
    <q-dialog v-model="formOpen" persistent :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card :style="$q.screen.lt.sm ? 'width:100%;border-radius:16px 16px 0 0' : 'min-width:440px'">
        <q-card-section class="text-h6">{{ form.id ? 'Termin bearbeiten' : 'Neuer Termin' }}</q-card-section>
        <q-card-section class="q-gutter-sm q-pt-none">
          <q-select v-model="form.typ" :options="typOptionen" option-value="value" option-label="label"
            emit-value map-options label="Typ *" outlined dense />
          <div class="row q-gutter-sm">
            <q-input v-model="form.datum" label="Datum *" outlined dense type="date" class="col" />
            <q-input v-model="form.zeit" label="Beginn *" outlined dense type="time" class="col" />
            <q-input v-model="form.endeZeit" label="Ende" outlined dense type="time" class="col" />
          </div>
          <q-input v-model="form.ort" label="Ort" outlined dense />
          <div class="row q-gutter-sm">
            <q-input v-model="form.treffpunkt" label="Treffpunkt" outlined dense class="col-7 col-grow" />
            <q-input v-model="form.treffpunktZeit" label="Treffpunkt-Zeit" outlined dense type="time" class="col" />
          </div>
          <template v-if="form.typ === 'spiel'">
            <q-input v-model="form.gegner" label="Gegner" outlined dense />
            <q-btn-toggle v-model="form.heimAuswaerts" spread unelevated toggle-color="primary"
              :options="[{ label: 'Heim', value: 'heim' }, { label: 'Auswärts', value: 'auswaerts' }]" />
          </template>
          <q-input v-model="form.beschreibung" label="Beschreibung" outlined dense type="textarea" autogrow />
          <div v-if="formError" class="text-negative text-caption">{{ formError }}</div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn unelevated color="primary" :label="form.id ? 'Speichern' : 'Anlegen'"
            :loading="saving" @click="save" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { usePageRefresh } from 'src/composables/useRefresh'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { useAuthStore } from 'src/stores/auth'
import TerminCard from 'components/TerminCard.vue'
import { terminTitel, uhrzeit, datumLabel } from 'src/composables/useTermine'

const $q = useQuasar()
const auth = useAuthStore()

const teams = ref([])
const termine = ref([])
const tab = ref('meine')
const vergangene = ref(false)
const loading = ref(false)

const darfVerwalten = computed(() => {
  if (auth.hasPermission('termine.verwalten')) return true
  const team = teams.value.find(m => m.id === tab.value)
  return team?.zugriff === 'verwalten'
})

const typOptionen = [
  { label: 'Training', value: 'training' },
  { label: 'Spiel', value: 'spiel' },
  { label: 'Sonstiges', value: 'sonstiges' },
]

function teamLabel(m) {
  return m.saison ? `${m.name} (${m.saison})` : m.name
}

function kannVerwalten(t) {
  if (auth.hasPermission('termine.verwalten')) return true
  if (tab.value === 'meine') return t.zugriff === 'verwalten'
  return darfVerwalten.value
}

function vonFilter() {
  const heute = new Date()
  if (!vergangene.value) return heute.toISOString().slice(0, 10)
  heute.setDate(heute.getDate() - 90)
  return heute.toISOString().slice(0, 10)
}

async function loadTermine() {
  loading.value = true
  try {
    if (tab.value === 'meine') {
      const { data } = await api.get('/api/termine/meine', { params: { von: vonFilter() } })
      termine.value = data
    } else {
      const { data } = await api.get(`/api/termine/mannschaften/${tab.value}`,
        { params: { von: vonFilter() } })
      termine.value = data.termine
    }
  } catch {
    $q.notify({ type: 'negative', message: 'Fehler beim Laden der Termine' })
    termine.value = []
  } finally {
    loading.value = false
  }
}

async function load() {
  try {
    const { data } = await api.get('/api/termine/mannschaften')
    teams.value = data
  } catch {
    $q.notify({ type: 'negative', message: 'Fehler beim Laden' })
    teams.value = []
  }
  await loadTermine()
}
usePageRefresh(load)
onMounted(load)
watch(tab, loadTermine)
watch(vergangene, loadTermine)

// ── Termin anlegen/bearbeiten ──────────────────────────────
const formOpen = ref(false)
const saving = ref(false)
const formError = ref('')
const form = ref({})

function leeresFormular() {
  return { id: null, version: null, typ: 'training',
           datum: new Date().toISOString().slice(0, 10), zeit: '', endeZeit: '',
           ort: '', treffpunkt: '', treffpunktZeit: '', gegner: '', heimAuswaerts: 'heim',
           beschreibung: '' }
}
function openCreate() {
  form.value = leeresFormular()
  formError.value = ''
  formOpen.value = true
}
function openEdit(t) {
  form.value = { id: t.id, version: t.version, typ: t.typ,
                 datum: t.beginn.slice(0, 10), zeit: uhrzeit(t.beginn), endeZeit: uhrzeit(t.ende ?? ''),
                 ort: t.ort ?? '', treffpunkt: t.treffpunkt ?? '', treffpunktZeit: t.treffpunkt_zeit ?? '',
                 gegner: t.gegner ?? '', heimAuswaerts: t.heim_auswaerts ?? 'heim',
                 beschreibung: t.beschreibung ?? '' }
  formError.value = ''
  formOpen.value = true
}
async function save() {
  const f = form.value
  if (!f.datum || !f.zeit) {
    formError.value = 'Datum und Beginn sind erforderlich.'
    return
  }
  saving.value = true
  formError.value = ''
  try {
    const payload = {
      typ: f.typ,
      beginn: `${f.datum}T${f.zeit}`,
      ende: f.endeZeit ? `${f.datum}T${f.endeZeit}` : null,
      ort: f.ort || null,
      treffpunkt: f.treffpunkt || null,
      treffpunkt_zeit: f.treffpunktZeit || null,
      gegner: f.typ === 'spiel' ? (f.gegner || null) : null,
      heim_auswaerts: f.typ === 'spiel' ? f.heimAuswaerts : null,
      beschreibung: f.beschreibung || null,
    }
    if (f.id) {
      await api.put(`/api/termine/${f.id}`, { ...payload, expected_version: f.version })
    } else {
      await api.post(`/api/termine/mannschaften/${tab.value}`, payload)
    }
    formOpen.value = false
    await loadTermine()
    $q.notify({ type: 'positive', message: 'Gespeichert' })
  } catch (e) {
    formError.value = e.response?.data?.detail || 'Fehler beim Speichern'
  } finally {
    saving.value = false
  }
}

async function setStatus(t, aktion) {
  try {
    await api.post(`/api/termine/${t.id}/${aktion}`, { expected_version: t.version })
    await loadTermine()
    $q.notify({ type: 'positive', message: aktion === 'absagen' ? 'Termin abgesagt' : 'Termin reaktiviert' })
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' })
  }
}
function confirmDelete(t) {
  $q.dialog({
    title: 'Termin löschen',
    message: `„${terminTitel(t)}" am ${datumLabel(t.beginn.slice(0, 10))} wirklich löschen?`,
    cancel: true, persistent: true,
  }).onOk(async () => {
    try {
      await api.delete(`/api/termine/${t.id}`)
      await loadTermine()
    } catch (e) {
      $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' })
    }
  })
}
</script>
