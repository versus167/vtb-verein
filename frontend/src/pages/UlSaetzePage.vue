<template>
  <div>
    <div class="row items-center q-mb-md">
      <div class="text-h5">Vergütungssätze</div>
      <q-space />
      <q-btn color="primary" unelevated icon="add" label="Neuer Satz" @click="openCreate" />
    </div>

    <div class="text-grey-7 text-caption q-mb-sm">
      Auflösung beim Einreichen: ÜL-individuell → Abteilung + Lizenz → vereinsweit + Lizenz.
    </div>

    <q-list bordered separator>
      <q-item v-for="s in saetze" :key="s.id">
        <q-item-section>
          <q-item-label>
            {{ geltungLabel(s) }}
            <q-chip dense size="sm" outline
              :color="s.lizenz_klassifikation === 'mit_lizenz' ? 'green-8' : 'blue-grey'">
              {{ s.lizenz_klassifikation === 'mit_lizenz' ? 'mit Lizenz' : 'ohne Lizenz' }}
            </q-chip>
          </q-item-label>
          <q-item-label caption>
            <span class="text-body2 text-weight-medium text-grey-9">{{ fmtSatz(s.satz) }}</span>
            <span v-if="s.gueltig_ab" class="q-ml-sm">· gültig ab {{ s.gueltig_ab }}</span>
          </q-item-label>
        </q-item-section>
        <q-item-section side>
          <div class="row q-gutter-xs">
            <q-btn flat dense round size="sm" icon="edit" color="primary" @click="openEdit(s)" />
            <q-btn flat dense round size="sm" icon="delete" color="negative" @click="confirmDelete(s)" />
          </div>
        </q-item-section>
      </q-item>
    </q-list>
    <div v-if="saetze.length === 0" class="text-grey text-center q-py-lg">
      Noch keine Sätze hinterlegt. Lege den ersten an.
    </div>

    <!-- Anlegen / Bearbeiten -->
    <q-dialog v-model="dialogOpen" persistent :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card :style="$q.screen.lt.sm ? 'width:100%;border-radius:16px 16px 0 0' : 'min-width:440px'">
        <q-card-section class="text-h6">{{ form.id ? 'Satz bearbeiten' : 'Neuer Satz' }}</q-card-section>
        <q-card-section class="q-gutter-sm q-pt-none">
          <q-select v-model="form.lizenz_klassifikation" :options="lizenzOptionen" emit-value map-options
            label="Lizenz *" outlined dense />
          <q-input v-model.number="form.satz" type="number" step="0.01" min="0" label="Satz (€/h) *"
            outlined dense />
          <q-select v-model="form.abteilung_id" :options="abteilungen" option-value="id" option-label="name"
            emit-value map-options clearable label="Abteilung (leer = vereinsweit)" outlined dense
            :hint="abteilungen.length === 0 ? 'Abteilungen nicht geladen – nur vereinsweit möglich' : ''" />
          <q-input v-model="form.gueltig_ab" type="date" label="Gültig ab (optional)" outlined dense />
          <div v-if="form.mitglied_id" class="text-caption text-amber-9">
            <q-icon name="info" size="xs" /> ÜL-Override für {{ form.mitglied_label }} – bleibt erhalten
            (Bearbeitung der ÜL-Zuordnung folgt später).
          </div>
          <div v-if="error" class="text-negative text-caption">{{ error }}</div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn unelevated color="primary" :label="form.id ? 'Speichern' : 'Anlegen'"
            :loading="saving" @click="save" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { usePageRefresh } from 'src/composables/useRefresh'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'

defineOptions({ name: 'UlSaetzePage' })

const $q = useQuasar()

const saetze = ref([])
const abteilungen = ref([])
const lizenzOptionen = [
  { label: 'mit Lizenz', value: 'mit_lizenz' },
  { label: 'ohne Lizenz', value: 'ohne_lizenz' },
]

function fmtSatz(v) {
  if (v == null) return '–'
  return Number(v).toLocaleString('de-DE', { style: 'currency', currency: 'EUR' }) + '/h'
}
function geltungLabel(s) {
  const scope = s.abteilung_name || 'Vereinsweit'
  if (s.mitglied_id) {
    const name = `${s.mitglied_vorname || ''} ${s.mitglied_nachname || ''}`.trim()
    return `${scope} · ÜL: ${name}`
  }
  return scope
}

async function loadSaetze() {
  const { data } = await api.get('/api/ul-stunden/saetze')
  saetze.value = data
}
async function loadAbteilungen() {
  // Eigene Berechtigung (abteilungen.read) – falls nicht vorhanden, nur vereinsweit.
  try {
    const { data } = await api.get('/api/abteilungen/')
    abteilungen.value = data
  } catch {
    abteilungen.value = []
  }
}
usePageRefresh(loadSaetze)
onMounted(async () => {
  try { await Promise.all([loadSaetze(), loadAbteilungen()]) }
  catch { $q.notify({ type: 'negative', message: 'Fehler beim Laden' }) }
})

const dialogOpen = ref(false)
const saving = ref(false)
const error = ref('')
const form = ref({})

function openCreate() {
  error.value = ''
  form.value = {
    id: null, lizenz_klassifikation: 'ohne_lizenz', satz: null,
    abteilung_id: null, mitglied_id: null, mitglied_label: '', gueltig_ab: '', version: 1,
  }
  dialogOpen.value = true
}
function openEdit(s) {
  error.value = ''
  form.value = {
    id: s.id, lizenz_klassifikation: s.lizenz_klassifikation, satz: s.satz,
    abteilung_id: s.abteilung_id, mitglied_id: s.mitglied_id,
    mitglied_label: `${s.mitglied_vorname || ''} ${s.mitglied_nachname || ''}`.trim(),
    gueltig_ab: s.gueltig_ab || '', version: s.version,
  }
  dialogOpen.value = true
}
async function save() {
  if (!form.value.lizenz_klassifikation || form.value.satz == null || Number(form.value.satz) <= 0) {
    error.value = 'Lizenz und ein Satz größer 0 sind erforderlich.'; return
  }
  saving.value = true; error.value = ''
  const payload = {
    lizenz_klassifikation: form.value.lizenz_klassifikation,
    satz: Number(form.value.satz),
    abteilung_id: form.value.abteilung_id || null,
    mitglied_id: form.value.mitglied_id || null,   // ÜL-Override bleibt erhalten (UI folgt)
    gueltig_ab: form.value.gueltig_ab || null,
  }
  try {
    if (form.value.id) {
      await api.put(`/api/ul-stunden/saetze/${form.value.id}`,
        { ...payload, expected_version: form.value.version })
    } else {
      await api.post('/api/ul-stunden/saetze', payload)
    }
    dialogOpen.value = false
    await loadSaetze()
  } catch (e) {
    error.value = e.response?.data?.detail || 'Speichern fehlgeschlagen'
  } finally {
    saving.value = false
  }
}
function confirmDelete(s) {
  $q.dialog({
    title: 'Satz löschen',
    message: `Satz „${geltungLabel(s)} · ${fmtSatz(s.satz)}" wirklich löschen?`,
    cancel: true,
  }).onOk(async () => {
    try {
      await api.delete(`/api/ul-stunden/saetze/${s.id}`)
      await loadSaetze()
    } catch (e) {
      $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Löschen fehlgeschlagen' })
    }
  })
}
</script>
