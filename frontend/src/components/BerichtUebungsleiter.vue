<template>
  <div>
    <div class="row items-center q-gutter-sm q-mb-md">
      <q-select
        v-model="ablaufJahr"
        :options="jahrOptionen"
        emit-value
        map-options
        dense
        outlined
        options-dense
        label="Lizenz läuft ab"
        style="min-width: 200px"
      />
      <div class="text-caption text-grey-7 col">
        Alle mit der Funktion „Übungsleiter" oder „Übungsleiter mit Lizenz". Abteilung aus
        der trainierten Mannschaft, sonst aus der Abteilungszugehörigkeit.
      </div>
      <q-btn v-if="zeilen.length" flat dense no-caps icon="download" label="CSV" @click="csv" />
    </div>

    <q-table
      :rows="zeilen"
      :columns="spalten"
      row-key="mitglied_id"
      :loading="loading"
      :pagination="{ rowsPerPage: 0, sortBy: 'name' }"
      hide-pagination
      flat
      bordered
      dense
      :grid="$q.screen.lt.sm"
      no-data-label="Keine Übungsleiter"
    >
      <template #body-cell-abteilung="props">
        <q-td :props="props">
          {{ props.row.abteilungen || '–' }}
          <span v-if="props.row.abteilung_quelle === 'mannschaft'" class="text-caption text-grey-6">
            (Mannschaft)
          </span>
        </q-td>
      </template>
      <template #body-cell-lizenz="props">
        <q-td :props="props">
          <q-badge v-bind="lizenzBadge(props.row)" />
          <q-icon
            v-if="props.row.funktion_mit_lizenz && !props.row.lizenz"
            name="warning"
            color="warning"
            size="16px"
            class="q-ml-xs"
          >
            <q-tooltip>Als „Übungsleiter mit Lizenz" geführt, aber ohne gültige Lizenz eingetragen</q-tooltip>
          </q-icon>
        </q-td>
      </template>
    </q-table>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { formatDate } from 'src/utils/datetime'
import { csvDownload } from 'src/utils/csv'
import { GESCHLECHTER } from 'src/utils/meldung'

const $q = useQuasar()
const loading = ref(false)
const liste = ref([])
// null = alle; sonst nur, wessen Lizenz in diesem Jahr endet (Januar-Liste).
const ablaufJahr = ref(null)

const geschlecht = (code) => GESCHLECHTER.find((g) => g.key === code)?.label || ''
const ablaufJahrVon = (r) => r.trainerlizenz_gueltig_bis?.slice(0, 4) || null

const jahrOptionen = computed(() => {
  const jahre = new Set(liste.value.map(ablaufJahrVon).filter(Boolean))
  jahre.add(String(new Date().getFullYear()))
  return [
    { label: 'Alle Übungsleiter', value: null },
    ...[...jahre].sort().map((j) => ({ label: `im Jahr ${j}`, value: j })),
  ]
})

const zeilen = computed(() => (ablaufJahr.value
  ? liste.value.filter((r) => ablaufJahrVon(r) === ablaufJahr.value)
  : liste.value))

const spalten = [
  { name: 'name', label: 'Name', align: 'left', sortable: true,
    field: (r) => `${r.nachname}, ${r.vorname}` },
  { name: 'geschlecht', label: 'Geschlecht', align: 'left', sortable: true,
    field: (r) => geschlecht(r.geschlecht) },
  { name: 'abteilung', label: 'Abteilung', align: 'left', sortable: true,
    field: (r) => r.abteilungen || '' },
  // format greift im Handy-Raster, wo der Zellen-Slot mit dem Badge nicht gilt.
  { name: 'lizenz', label: 'Lizenz', align: 'left', sortable: true, field: (r) => r.lizenz,
    format: (v, r) => lizenzBadge(r).label },
  { name: 'lizenz_nr', label: 'Lizenz-Nr.', align: 'left', field: (r) => r.trainerlizenz_nr || '' },
  { name: 'lizenz_bis', label: 'Lizenzende', align: 'left', sortable: true,
    field: (r) => r.trainerlizenz_gueltig_bis || '', format: (v) => (v ? formatDate(v) : '') },
]

function lizenzBadge(r) {
  if (r.lizenz) return { color: 'positive', label: 'gültig' }
  if (r.trainerlizenz_gueltig_bis) return { color: 'negative', label: 'abgelaufen' }
  return { color: 'grey-6', label: 'keine' }
}

function csv() {
  const name = ablaufJahr.value ? `lizenzablauf-${ablaufJahr.value}` : 'uebungsleiter'
  csvDownload(`${name}.csv`,
    ['Nachname', 'Vorname', 'Geschlecht', 'Abteilung', 'Lizenz', 'Lizenz-Nr.', 'Lizenzende'],
    zeilen.value.map((r) => [r.nachname, r.vorname, geschlecht(r.geschlecht), r.abteilungen,
      r.lizenz ? 'ja' : 'nein', r.trainerlizenz_nr, formatDate(r.trainerlizenz_gueltig_bis, { placeholder: '' })]))
}

async function load() {
  loading.value = true
  try {
    const res = await api.get('/api/berichte/uebungsleiter')
    liste.value = res.data
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Laden der Übungsleiter' })
  } finally {
    loading.value = false
  }
}

onMounted(load)
defineExpose({ load })
</script>
