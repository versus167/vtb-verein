<template>
  <q-page class="q-pa-md">
    <div class="row items-center q-mb-md">
      <div class="text-h5">Gebühren</div>
      <q-space />
    </div>

    <q-tabs v-model="tab" dense align="left" class="text-primary q-mb-md" narrow-indicator>
      <q-tab name="katalog" label="Katalog" icon="receipt_long" />
      <q-tab name="forderungen" label="Forderungen" icon="request_quote" />
    </q-tabs>

    <!-- ════════════ Katalog ════════════ -->
    <div v-show="tab === 'katalog'">
      <div class="row q-mb-sm">
        <q-space />
        <q-btn v-if="auth.hasPermission('gebuehren.write')" color="primary" unelevated
          icon="add" label="Neue Gebühr" @click="openGebuehr()" />
      </div>
      <q-list bordered separator>
        <q-item v-for="g in gebuehren" :key="g.id">
          <q-item-section>
            <q-item-label>{{ g.name }} <span class="text-grey-7">· {{ g.betrag.toFixed(2) }} €</span></q-item-label>
            <q-item-label caption>
              <q-chip dense size="sm" :color="g.abteilung_id ? 'purple' : 'blue-grey'" text-color="white">
                {{ g.abteilung_id ? g.abteilung_name : 'Vereinsgebühr' }}
              </q-chip>
              <span class="q-mx-xs">ab {{ g.gueltig_ab }}<span v-if="g.gueltig_bis"> bis {{ g.gueltig_bis }}</span></span>
              <q-chip v-if="g.zahler_typ === 'abteilung'" dense size="sm" color="teal" text-color="white">
                Zahlung: {{ g.abteilung_name ?? 'Abteilung' }}
              </q-chip>
            </q-item-label>
          </q-item-section>
          <q-item-section side v-if="auth.hasPermission('gebuehren.write')">
            <div class="row q-gutter-xs">
              <q-btn flat dense round icon="edit" color="primary" size="sm" @click="openGebuehr(g)" />
              <q-btn flat dense round icon="delete" color="negative" size="sm" @click="deleteGebuehr(g)" />
            </div>
          </q-item-section>
        </q-item>
      </q-list>
      <div v-if="gebuehren.length === 0" class="text-grey text-center q-py-lg">Noch keine Gebühren angelegt.</div>
    </div>

    <!-- ════════════ Forderungen ════════════ -->
    <div v-show="tab === 'forderungen'">
      <div class="row items-center q-mb-sm q-gutter-sm">
        <q-select v-model="statusFilter" :options="statusFilterOptionen" option-value="value" option-label="label"
          emit-value map-options dense outlined label="Status" style="min-width:160px" @update:model-value="loadForderungen" />
        <q-space />
        <q-btn v-if="auth.hasPermission('gebuehren.abrechnen')" flat icon="download"
          label="SEPA-Export" @click="sepaExport" />
        <q-btn v-if="auth.hasPermission('gebuehren.write')" color="primary" unelevated
          icon="add" label="Forderung anlegen" @click="openForderung" />
      </div>
      <q-list bordered separator>
        <q-item v-for="f in forderungen" :key="f.id">
          <q-item-section>
            <q-item-label>{{ f.mitglied_nachname }}, {{ f.mitglied_vorname }} — {{ f.gebuehr_name }}</q-item-label>
            <q-item-label caption>
              {{ f.betrag_soll.toFixed(2) }} € · {{ f.datum }}
              <q-chip dense size="sm" :color="statusColor(f.status)" text-color="white">{{ f.status }}</q-chip>
            </q-item-label>
          </q-item-section>
          <q-item-section side v-if="auth.hasPermission('gebuehren.abrechnen') && f.status === 'offen'">
            <div class="row q-gutter-xs">
              <q-btn flat dense round icon="check" color="positive" size="sm" @click="markBezahlt(f)">
                <q-tooltip>Als bezahlt markieren</q-tooltip>
              </q-btn>
              <q-btn flat dense round icon="block" color="negative" size="sm" @click="storno(f)">
                <q-tooltip>Stornieren</q-tooltip>
              </q-btn>
            </div>
          </q-item-section>
        </q-item>
      </q-list>
      <div v-if="forderungen.length === 0" class="text-grey text-center q-py-lg">Keine Forderungen.</div>
    </div>

    <!-- Gebühr anlegen/bearbeiten -->
    <q-dialog v-model="gebuehrOpen" persistent :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card :style="$q.screen.lt.sm ? 'width:100%;border-radius:16px 16px 0 0' : 'min-width:440px'">
        <q-card-section class="text-h6">{{ gForm.id ? 'Gebühr bearbeiten' : 'Neue Gebühr' }}</q-card-section>
        <q-card-section class="q-gutter-sm q-pt-none">
          <q-input v-model="gForm.name" label="Name *" outlined dense />
          <q-select v-model="gForm.abteilung_id" :options="abteilungen" option-value="id" option-label="name"
            emit-value map-options clearable label="Abteilung (leer = Vereinsgebühr)" outlined dense />
          <q-input v-model.number="gForm.betrag" label="Betrag (€) *" outlined dense type="number" step="0.01" />
          <q-input v-model="gForm.anlass" label="Anlass" outlined dense />
          <div class="row q-gutter-sm">
            <q-input v-model="gForm.gueltig_ab" label="Gültig ab *" outlined dense type="date" class="col" />
            <q-input v-model="gForm.gueltig_bis" label="Gültig bis" outlined dense type="date" class="col" />
          </div>
          <q-select v-model="gForm.zahler_typ"
            :options="[{label:'Mitglied zahlt (SEPA)',value:'mitglied'},{label:'Abteilung zahlt',value:'abteilung'}]"
            emit-value map-options label="Zahler" outlined dense />
          <div v-if="gError" class="text-negative text-caption">{{ gError }}</div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn unelevated color="primary" :label="gForm.id ? 'Speichern' : 'Anlegen'" :loading="gSaving" @click="saveGebuehr" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Forderung anlegen -->
    <q-dialog v-model="forderungOpen" persistent :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card :style="$q.screen.lt.sm ? 'width:100%;border-radius:16px 16px 0 0' : 'min-width:440px'">
        <q-card-section class="text-h6">Forderung anlegen</q-card-section>
        <q-card-section class="q-gutter-sm q-pt-none">
          <q-select v-model="fForm.mitglied_id" :options="mitgliedOptions" option-value="id"
            :option-label="m => `${m.nachname}, ${m.vorname}`" emit-value map-options use-input
            input-debounce="0" @filter="filterMitglieder" label="Mitglied *" outlined dense />
          <div v-if="selectedMitglied" class="text-caption text-grey-7 q-px-xs">
            Abteilungen: {{ selectedMitgliedAbteilungen || '–' }}<span v-if="mitgliedAlter != null"> · Alter: {{ mitgliedAlter }} J.</span>
          </div>
          <q-input v-model="fForm.datum" label="Datum *" outlined dense type="date" />
          <q-select v-model="fForm.gebuehr_id" :options="passendeGebuehren" option-value="id"
            :option-label="g => `${g.name} (${g.betrag.toFixed(2)} €)`" emit-value map-options
            label="Gebühr *" outlined dense :disable="!fForm.mitglied_id"
            :hint="!fForm.mitglied_id ? 'Erst Mitglied wählen' : (passendeGebuehren.length === 0 ? 'Keine passende Gebühr (Verein/Abteilung/Gültigkeit)' : '')" />
          <div v-if="fError" class="text-negative text-caption">{{ fError }}</div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn unelevated color="primary" label="Anlegen" :loading="fSaving" @click="saveForderung" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { useAuthStore } from 'src/stores/auth'

const $q = useQuasar()
const auth = useAuthStore()

const tab = ref('katalog')
const gebuehren = ref([])
const abteilungen = ref([])

const statusFilter = ref('offen')
const statusFilterOptionen = [
  { label: 'Offen', value: 'offen' },
  { label: 'Bezahlt', value: 'bezahlt' },
  { label: 'Storniert', value: 'storniert' },
  { label: 'Alle', value: '' },
]
const forderungen = ref([])

function statusColor(s) { return { offen: 'orange', bezahlt: 'positive', storniert: 'grey' }[s] ?? 'grey' }

async function loadKatalog() {
  const [{ data: g }, { data: ab }] = await Promise.all([
    api.get('/api/gebuehren'),
    api.get('/api/abteilungen/'),
  ])
  gebuehren.value = g
  abteilungen.value = ab
}
async function loadForderungen() {
  const params = statusFilter.value ? { status_filter: statusFilter.value } : {}
  const { data } = await api.get('/api/gebuehren/forderungen', { params })
  forderungen.value = data
}
onMounted(async () => {
  try { await loadKatalog(); await loadForderungen() }
  catch { $q.notify({ type: 'negative', message: 'Fehler beim Laden' }) }
})

// ── Gebühr ─────────────────────────────────────────────────
const gebuehrOpen = ref(false)
const gSaving = ref(false)
const gError = ref('')
const gForm = ref({})
function openGebuehr(g = null) {
  gError.value = ''
  gForm.value = g ? {
    id: g.id, name: g.name, abteilung_id: g.abteilung_id, betrag: g.betrag, anlass: g.anlass,
    gueltig_ab: g.gueltig_ab, gueltig_bis: g.gueltig_bis ?? '', zahler_typ: g.zahler_typ,
    version: g.version,
  } : {
    id: null, name: '', abteilung_id: null, betrag: 0, anlass: 'aufnahme',
    gueltig_ab: new Date().toISOString().slice(0, 10), gueltig_bis: '',
    zahler_typ: 'mitglied',
  }
  gebuehrOpen.value = true
}
async function saveGebuehr() {
  if (!gForm.value.name.trim() || !gForm.value.gueltig_ab) {
    gError.value = 'Name und „Gültig ab" sind erforderlich.'; return
  }
  gSaving.value = true; gError.value = ''
  try {
    const payload = {
      name: gForm.value.name.trim(), abteilung_id: gForm.value.abteilung_id || null,
      betrag: Number(gForm.value.betrag), anlass: gForm.value.anlass || 'aufnahme',
      gueltig_ab: gForm.value.gueltig_ab, gueltig_bis: gForm.value.gueltig_bis || null,
      zahler_typ: gForm.value.zahler_typ,
    }
    if (gForm.value.id) {
      await api.put(`/api/gebuehren/${gForm.value.id}`, { ...payload, expected_version: gForm.value.version })
    } else {
      await api.post('/api/gebuehren', payload)
    }
    gebuehrOpen.value = false
    await loadKatalog()
    $q.notify({ type: 'positive', message: 'Gespeichert' })
  } catch (e) {
    gError.value = e.response?.data?.detail || 'Fehler beim Speichern'
  } finally {
    gSaving.value = false
  }
}
function deleteGebuehr(g) {
  $q.dialog({ title: 'Gebühr löschen', message: `„${g.name}" löschen?`, cancel: true, persistent: true })
    .onOk(async () => {
      try { await api.delete(`/api/gebuehren/${g.id}`); await loadKatalog() }
      catch (e) { $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' }) }
    })
}

// ── Forderungen ────────────────────────────────────────────
const forderungOpen = ref(false)
const fSaving = ref(false)
const fError = ref('')
const fForm = ref({ gebuehr_id: null, mitglied_id: null, datum: '' })
const alleMitglieder = ref([])
const mitgliedOptions = ref([])
function filterMitglieder(val, update) {
  const needle = val.toLowerCase()
  update(() => {
    mitgliedOptions.value = !needle ? alleMitglieder.value
      : alleMitglieder.value.filter(m => `${m.nachname} ${m.vorname}`.toLowerCase().includes(needle))
  })
}

const selectedMitglied = computed(() =>
  alleMitglieder.value.find(m => m.id === fForm.value.mitglied_id) || null)

const mitgliedAlter = computed(() => {
  const g = selectedMitglied.value?.geburtsdatum
  if (!g) return null
  const d = new Date(g)
  if (isNaN(d.getTime())) return null
  const t = new Date()
  let a = t.getFullYear() - d.getFullYear()
  if (t.getMonth() < d.getMonth() || (t.getMonth() === d.getMonth() && t.getDate() < d.getDate())) a--
  return a
})

const selectedMitgliedAbteilungen = computed(() => {
  const m = selectedMitglied.value
  if (!m) return ''
  return m.abteilung_ids
    .map(id => abteilungen.value.find(a => a.id === id)?.name)
    .filter(Boolean).join(', ')
})

// Nur Gebühren, die für das gewählte Mitglied zutreffen: Verein (ohne Abteilung)
// oder eine Abteilung des Mitglieds, und am Forderungsdatum gültig.
const passendeGebuehren = computed(() => {
  const m = selectedMitglied.value
  if (!m) return []
  const datum = fForm.value.datum || new Date().toISOString().slice(0, 10)
  const abt = new Set(m.abteilung_ids)
  return gebuehren.value.filter(g => {
    if (g.gueltig_ab && g.gueltig_ab > datum) return false
    if (g.gueltig_bis && g.gueltig_bis < datum) return false
    return g.abteilung_id == null || abt.has(g.abteilung_id)
  })
})

// Gewählte Gebühr verwerfen, wenn sie nach Mitglied-/Datumswechsel nicht mehr passt
watch(passendeGebuehren, (list) => {
  if (fForm.value.gebuehr_id && !list.some(g => g.id === fForm.value.gebuehr_id)) {
    fForm.value.gebuehr_id = null
  }
})
async function openForderung() {
  fError.value = ''
  fForm.value = { gebuehr_id: null, mitglied_id: null, datum: new Date().toISOString().slice(0, 10) }
  if (alleMitglieder.value.length === 0) {
    const { data } = await api.get('/api/personen/')
    alleMitglieder.value = data.filter(p => p.mitglied).map(p => ({
      id: p.mitglied.id, vorname: p.mitglied.vorname, nachname: p.mitglied.nachname,
      geburtsdatum: p.mitglied.geburtsdatum,
      abteilung_ids: (p.abteilungen || []).map(a => a.abteilung_id),
    }))
  }
  mitgliedOptions.value = alleMitglieder.value
  forderungOpen.value = true
}
async function saveForderung() {
  if (!fForm.value.gebuehr_id || !fForm.value.mitglied_id || !fForm.value.datum) {
    fError.value = 'Gebühr, Mitglied und Datum sind erforderlich.'; return
  }
  fSaving.value = true; fError.value = ''
  try {
    await api.post('/api/gebuehren/forderungen', {
      gebuehr_id: fForm.value.gebuehr_id, mitglied_id: fForm.value.mitglied_id, datum: fForm.value.datum,
    })
    forderungOpen.value = false
    await loadForderungen()
    $q.notify({ type: 'positive', message: 'Forderung angelegt' })
  } catch (e) {
    fError.value = e.response?.data?.detail || 'Fehler'
  } finally {
    fSaving.value = false
  }
}
async function markBezahlt(f) {
  try {
    await api.patch(`/api/gebuehren/forderungen/${f.id}`, { bezahlt_am: new Date().toISOString().slice(0, 10) })
    await loadForderungen()
  } catch (e) { $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' }) }
}
function storno(f) {
  $q.dialog({ title: 'Forderung stornieren', message: 'Wirklich stornieren?', cancel: true })
    .onOk(async () => {
      try { await api.patch(`/api/gebuehren/forderungen/${f.id}`, { bezahlt_am: null }); await loadForderungen() }
      catch (e) { $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' }) }
    })
}
async function sepaExport() {
  try {
    const res = await api.get('/api/gebuehren/sepa-export', { responseType: 'blob' })
    const url = URL.createObjectURL(res.data)
    const a = document.createElement('a')
    a.href = url; a.download = 'sepa_gebuehren.csv'; a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.status === 404 ? 'Keine offenen SEPA-Gebühren' : 'Fehler' })
  }
}
</script>
