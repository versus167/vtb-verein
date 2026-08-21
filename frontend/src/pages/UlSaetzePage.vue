<template>
  <div>
    <div class="row items-center q-mb-md">
      <div class="text-h5">Vergütungssätze</div>
      <q-space />
      <q-btn color="primary" unelevated icon="add" label="Neuer Satz" @click="openCreate" />
    </div>

    <div class="text-grey-7 text-caption q-mb-sm">
      Auflösung beim Einreichen: ÜL-individuell → Abteilung → vereinsweit; je Stufe schlägt
      die passende Lizenz den Satz für „jede Lizenz". Stunden werden bei jeder Art erfasst –
      die Art bestimmt nur, wie daraus ein Betrag wird.
    </div>

    <q-list bordered separator>
      <q-item v-for="s in saetze" :key="s.id">
        <q-item-section>
          <q-item-label>
            <!-- Individuelle Vereinbarungen stehen oben und tragen das Abzeichen:
                 Sie sind der Grund für die ganze Seite (#84). -->
            <q-icon v-if="s.mitglied_id" name="badge" size="xs" color="primary" class="q-mr-xs" />
            {{ geltungLabel(s) }}
            <q-chip dense size="sm" outline :color="lizenzChip(s).color">
              {{ lizenzChip(s).label }}
            </q-chip>
          </q-item-label>
          <q-item-label caption>
            <span class="text-body2 text-weight-medium text-grey-9">
              {{ fmtSatz(s.verguetungsart, s.satz) }}
            </span>
            <span class="q-ml-sm">· {{ artLabel(s.verguetungsart) }}</span>
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
          <q-select v-model="form.verguetungsart" :options="verguetungsarten" emit-value map-options
            label="Vergütungsart *" outlined dense :hint="artBeschreibung" />
          <q-select v-model="form.lizenz_klassifikation" :options="lizenzOptionen" emit-value map-options
            label="Lizenz" outlined dense
            hint="Leer = gilt für beide; ein passender Satz gewinnt" />
          <q-input v-if="form.verguetungsart !== 'ohne_verguetung'"
            v-model.number="form.satz" type="number" step="0.01" min="0"
            :label="satzLabel" outlined dense />
          <q-select v-model="form.abteilung_id" :options="abteilungen" option-value="id" option-label="name"
            emit-value map-options clearable label="Abteilung (leer = vereinsweit)" outlined dense
            :hint="abteilungen.length === 0 ? 'Abteilungen nicht geladen – nur vereinsweit möglich' : ''" />
          <!-- Kern von #84: Genau hier wird ein einzelner ÜL anders behandelt als der Rest.
               Ein Satz mit ÜL schlägt jeden Abteilungs- und Vereinssatz. -->
          <q-select v-model="form.mitglied_id" :options="uebungsleiterOptions" option-value="id"
            :option-label="ulLabel" emit-value map-options clearable outlined dense
            use-input input-debounce="0" @filter="filterUebungsleiter"
            label="Übungsleiter (leer = gilt für alle)"
            :hint="ulHinweis">
            <template #prepend><q-icon name="badge" /></template>
            <template #option="{ itemProps, opt }">
              <q-item v-bind="itemProps">
                <q-item-section>{{ ulLabel(opt) }}</q-item-section>
                <q-item-section side>
                  <q-chip dense size="sm"
                    :color="opt.lizenz_aktuell_gueltig ? 'green-2' : 'blue-grey-2'"
                    :text-color="opt.lizenz_aktuell_gueltig ? 'green-9' : 'blue-grey-8'">
                    {{ opt.lizenz_aktuell_gueltig ? 'Lizenz' : 'keine Lizenz' }}
                  </q-chip>
                </q-item-section>
              </q-item>
            </template>
            <template #no-option>
              <q-item><q-item-section class="text-grey">kein Treffer</q-item-section></q-item>
            </template>
          </q-select>
          <q-input v-model="form.gueltig_ab" type="date" label="Gültig ab (optional)" outlined dense />
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
import { ref, computed, onMounted } from 'vue'
import { usePageRefresh } from 'src/composables/useRefresh'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import {
  verguetungsarten, artLabel, fmtSatz, einheit,
} from 'src/composables/useUlVerguetung'

defineOptions({ name: 'UlSaetzePage' })

const $q = useQuasar()

const saetze = ref([])
const abteilungen = ref([])
const uebungsleiter = ref([])          // Auswahl-Liste für den individuellen Satz
const uebungsleiterOptions = ref([])   // gefilterte Sicht für die Textsuche

const ulLabel = (u) => (u ? `${u.nachname}, ${u.vorname}` : '')
function filterUebungsleiter(val, update) {
  const n = (val || '').toLowerCase()
  update(() => {
    uebungsleiterOptions.value = n
      ? uebungsleiter.value.filter(u => ulLabel(u).toLowerCase().includes(n))
      : uebungsleiter.value
  })
}
const lizenzOptionen = [
  { label: 'jede Lizenz', value: null },
  { label: 'mit Lizenz', value: 'mit_lizenz' },
  { label: 'ohne Lizenz', value: 'ohne_lizenz' },
]

function lizenzChip(s) {
  if (!s.lizenz_klassifikation) return { label: 'jede Lizenz', color: 'blue-grey' }
  return s.lizenz_klassifikation === 'mit_lizenz'
    ? { label: 'mit Lizenz', color: 'green-8' }
    : { label: 'ohne Lizenz', color: 'blue-grey' }
}
function geltungLabel(s) {
  // Beim individuellen Satz steht der Name vorn – er ist die Aussage, die Abteilung
  // nur noch die Einschränkung. Ohne ÜL zählt der Bereich.
  if (s.mitglied_id) {
    const name = `${s.mitglied_vorname || ''} ${s.mitglied_nachname || ''}`.trim()
    return s.abteilung_name ? `${name} · ${s.abteilung_name}` : name
  }
  return s.abteilung_name ? `Alle ÜL · ${s.abteilung_name}` : 'Alle ÜL · vereinsweit'
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
async function loadUebungsleiter() {
  // Aktive Inhaber der ÜL-Funktionen – dieselbe Liste wie bei der Fremderfassung (#65).
  try {
    const { data } = await api.get('/api/ul-stunden/uebungsleiter')
    uebungsleiter.value = data; uebungsleiterOptions.value = data
  } catch {
    uebungsleiter.value = []; uebungsleiterOptions.value = []
  }
}
usePageRefresh(loadSaetze)
onMounted(async () => {
  try { await Promise.all([loadSaetze(), loadAbteilungen(), loadUebungsleiter()]) }
  catch { $q.notify({ type: 'negative', message: 'Fehler beim Laden' }) }
})

const dialogOpen = ref(false)
const saving = ref(false)
const error = ref('')
const form = ref({})

// Die Art bestimmt Beschriftung und Einheit des Satzfelds: €/h beim Stundensatz,
// €/Monat bei der Pauschale; ohne Vergütung gibt es gar kein Feld.
const artBeschreibung = computed(
  () => verguetungsarten.find((a) => a.value === form.value.verguetungsart)?.beschreibung || '')
const satzLabel = computed(() => `Satz (€${einheit(form.value.verguetungsart)}) *`)
const ulHinweis = computed(() => {
  if (uebungsleiter.value.length === 0) return 'Keine Übungsleiter-Funktionen vergeben'
  return form.value.mitglied_id
    ? 'Gilt nur für diesen ÜL und schlägt Abteilungs- und Vereinssatz'
    : 'Leer = Satz gilt für alle ÜL im gewählten Bereich'
})

function openCreate() {
  error.value = ''
  form.value = {
    id: null, lizenz_klassifikation: null, verguetungsart: 'stundensatz', satz: null,
    abteilung_id: null, mitglied_id: null, gueltig_ab: '', version: 1,
  }
  dialogOpen.value = true
}
function openEdit(s) {
  error.value = ''
  form.value = {
    id: s.id, lizenz_klassifikation: s.lizenz_klassifikation || null,
    verguetungsart: s.verguetungsart || 'stundensatz', satz: s.satz,
    abteilung_id: s.abteilung_id, mitglied_id: s.mitglied_id,
    gueltig_ab: s.gueltig_ab || '', version: s.version,
  }
  dialogOpen.value = true
}
async function save() {
  // Ohne Vergütung gibt es keinen Betrag – dort ist ein leeres Satzfeld richtig.
  const ohneBetrag = form.value.verguetungsart === 'ohne_verguetung'
  if (!ohneBetrag && (form.value.satz == null || Number(form.value.satz) <= 0)) {
    error.value = 'Ein Satz größer 0 ist erforderlich.'; return
  }
  saving.value = true; error.value = ''
  const payload = {
    lizenz_klassifikation: form.value.lizenz_klassifikation || null,
    verguetungsart: form.value.verguetungsart,
    satz: ohneBetrag ? 0 : Number(form.value.satz),
    abteilung_id: form.value.abteilung_id || null,
    mitglied_id: form.value.mitglied_id || null,
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
    message: `Satz „${geltungLabel(s)} · ${fmtSatz(s.verguetungsart, s.satz)}" wirklich löschen?`,
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
