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
        Alter am Stichtag. Alle Vereinsmitglieder, auch passive und solche ohne Abteilung;
        Gastspieler zählen nicht.
      </div>
      <q-btn v-if="data" flat dense no-caps icon="download" label="CSV" @click="csv" />
    </div>

    <div v-if="loading && !data" class="row justify-center q-pa-xl">
      <q-spinner size="3rem" color="primary" />
    </div>

    <q-card v-else-if="data" flat bordered style="max-width: 480px">
      <q-markup-table flat dense>
        <thead>
          <tr>
            <th class="text-left">Altersgruppe</th>
            <th class="text-right">Mitglieder</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="g in data.gruppen" :key="g.gruppe">
            <td>{{ g.gruppe }}</td>
            <td class="text-right">{{ g.anzahl }}</td>
          </tr>
          <tr v-if="data.ohne_geburtsdatum">
            <td class="text-grey-7">ohne Geburtsdatum</td>
            <td class="text-right">{{ data.ohne_geburtsdatum }}</td>
          </tr>
        </tbody>
        <tfoot>
          <tr class="text-weight-bold">
            <td>Summe</td>
            <td class="text-right">{{ data.summe }}</td>
          </tr>
        </tfoot>
      </q-markup-table>
    </q-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { csvDownload } from 'src/utils/csv'
import { heuteIso } from 'src/utils/zeitraum'

const $q = useQuasar()
const loading = ref(false)
const data = ref(null)
const stichtag = ref(heuteIso())

function csv() {
  const zeilen = data.value.gruppen.map((g) => [g.gruppe, g.anzahl])
  if (data.value.ohne_geburtsdatum) zeilen.push(['ohne Geburtsdatum', data.value.ohne_geburtsdatum])
  zeilen.push(['Summe', data.value.summe])
  csvDownload(`altersgruppen-${data.value.stichtag}.csv`, ['Altersgruppe', 'Mitglieder'], zeilen)
}

async function load() {
  if (!stichtag.value) return
  loading.value = true
  try {
    const res = await api.get('/api/berichte/altersgruppen', { params: { stichtag: stichtag.value } })
    data.value = res.data
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Laden der Altersgruppen' })
  } finally {
    loading.value = false
  }
}

onMounted(load)
defineExpose({ load })
</script>
