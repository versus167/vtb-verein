<template>
  <div>
    <div class="row items-center q-gutter-sm q-mb-md">
      <q-input
        v-model="stichtag"
        type="date"
        label="Stichtag"
        dense
        outlined
        style="min-width: 180px"
        @update:model-value="load"
      />
      <div class="text-caption text-grey-7 col">
        Ehrungsjahr {{ jahr }}: wer bis zum Stichtag
        {{ data ? data.stufen.join(', ') : '' }} Jahre Mitglied ist und das zum Stichtag
        des Vorjahres noch nicht war. Grundlage ist das Eintrittsdatum.
      </div>
      <q-btn v-if="data?.ehrungen.length" flat dense no-caps icon="download" label="CSV" @click="csv" />
    </div>

    <div v-if="loading && !data" class="row justify-center q-pa-xl">
      <q-spinner size="3rem" color="primary" />
    </div>

    <template v-else-if="data">
      <div v-if="!data.ehrungen.length" class="text-grey-6 q-pa-md">
        Keine Jubilare zu diesem Stichtag.
      </div>
      <q-card v-for="gruppe in gruppen" :key="gruppe.jahre" flat bordered class="q-mb-md">
        <q-card-section class="row items-center">
          <div class="text-h6">{{ gruppe.jahre }} Jahre</div>
          <q-space />
          <q-badge color="primary" :label="gruppe.personen.length" />
        </q-card-section>
        <q-separator />
        <q-list dense separator>
          <q-item v-for="p in gruppe.personen" :key="p.mitglied_id">
            <q-item-section>
              <q-item-label>{{ p.nachname }}, {{ p.vorname }}</q-item-label>
              <q-item-label caption>
                Eintritt {{ formatDate(p.eintrittsdatum) }}
                <template v-if="p.mitgliedsnummer"> · Nr. {{ p.mitgliedsnummer }}</template>
              </q-item-label>
            </q-item-section>
            <q-item-section side class="text-right">
              {{ p.abteilungen || 'ohne Abteilung' }}
            </q-item-section>
          </q-item>
        </q-list>
      </q-card>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { formatDate } from 'src/utils/datetime'
import { csvDownload } from 'src/utils/csv'

const $q = useQuasar()
const loading = ref(false)
const data = ref(null)
// Leer = Vorgabe des Servers (der nächste 31.3.); sie steht nach dem Laden im Feld.
const stichtag = ref('')

const jahr = computed(() => (stichtag.value || data.value?.stichtag || '').slice(0, 4))

// Absteigend nach Jubiläum, wie der Server sortiert.
const gruppen = computed(() => {
  const je = new Map()
  for (const p of data.value?.ehrungen || []) {
    if (!je.has(p.jahre)) je.set(p.jahre, { jahre: p.jahre, personen: [] })
    je.get(p.jahre).personen.push(p)
  }
  return [...je.values()]
})

function csv() {
  csvDownload(`ehrungen-${jahr.value}.csv`,
    ['Jubiläum (Jahre)', 'Nachname', 'Vorname', 'Mitgliedsnr.', 'Eintritt', 'Abteilungen'],
    data.value.ehrungen.map((p) => [p.jahre, p.nachname, p.vorname, p.mitgliedsnummer,
      formatDate(p.eintrittsdatum), p.abteilungen]))
}

async function load() {
  loading.value = true
  try {
    const params = stichtag.value ? { stichtag: stichtag.value } : {}
    const res = await api.get('/api/berichte/ehrungen', { params })
    data.value = res.data
    stichtag.value = res.data.stichtag
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Laden der Ehrungen' })
  } finally {
    loading.value = false
  }
}

onMounted(load)
defineExpose({ load })
</script>
