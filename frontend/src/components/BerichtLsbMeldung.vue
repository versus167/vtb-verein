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
        Mitglied ist, wer bis zum Stichtag eingetreten ist; wer genau am Stichtag austritt,
        zählt noch mit. Gastspieler zählen nicht.
      </div>
    </div>

    <div v-if="loading && !data" class="row justify-center q-pa-xl">
      <q-spinner size="3rem" color="primary" />
    </div>

    <div v-else-if="data" class="row q-col-gutter-md">
      <!-- A-Meldung -->
      <div class="col-12 col-md-6">
        <q-card flat bordered>
          <q-card-section class="row items-center q-gutter-sm">
            <div>
              <div class="text-h6">A-Meldung: Vereinsmitglieder</div>
              <div class="text-caption text-grey-7">
                Jede Person einmal – auch passive und solche ohne Abteilung
              </div>
            </div>
            <q-space />
            <q-btn flat dense no-caps icon="download" label="CSV" @click="csvA" />
          </q-card-section>
          <q-separator />
          <JahrgangTabelle :tabelle="data.a" />
        </q-card>
      </div>

      <!-- B-Meldung -->
      <div class="col-12 col-md-6">
        <q-card flat bordered>
          <q-card-section class="row items-center q-gutter-sm">
            <div>
              <div class="text-h6">B-Meldung: je Abteilung</div>
              <div class="text-caption text-grey-7">
                Aktive Abteilungsmitglieder; wer in zwei Abteilungen ist, zählt in beiden
              </div>
            </div>
            <q-space />
            <q-btn flat dense no-caps icon="download" label="CSV" @click="csvB" />
          </q-card-section>
          <q-separator />
          <q-list separator>
            <q-expansion-item v-for="abt in data.b" :key="abt.abteilung_id" dense-toggle>
              <template #header>
                <q-item-section>{{ abt.name }}</q-item-section>
                <q-item-section side class="text-weight-medium">{{ abt.anzahl }}</q-item-section>
              </template>
              <JahrgangTabelle :tabelle="abt" />
            </q-expansion-item>
            <q-item>
              <q-item-section class="text-weight-bold">Summe B-Meldung</q-item-section>
              <q-item-section side class="text-weight-bold">{{ data.b_summe }}</q-item-section>
            </q-item>
            <q-item>
              <q-item-section>
                <q-item-label class="text-grey-7">Ohne aktive Abteilung</q-item-label>
                <q-item-label caption>Nicht Teil der Meldung – nur zur Kontrolle gegen die A-Meldung</q-item-label>
              </q-item-section>
              <q-item-section side>{{ data.ohne_abteilung }}</q-item-section>
            </q-item>
          </q-list>
        </q-card>
      </div>

      <!-- Fehlende Angaben -->
      <div v-if="data.luecken === null || data.luecken.length" class="col-12">
        <q-card flat bordered>
          <q-card-section>
            <div class="text-h6">Fehlende Angaben</div>
            <div class="text-caption text-grey-7">
              Diese Mitglieder stehen oben unter „ohne Angabe" – zum Nachpflegen
            </div>
          </q-card-section>
          <q-separator />
          <q-card-section v-if="data.luecken === null" class="text-grey-7">
            Die Namen sieht nur, wer auch Personen sehen darf.
          </q-card-section>
          <q-list v-else dense separator>
            <q-item v-for="p in data.luecken" :key="p.mitglied_id">
              <q-item-section>
                <q-item-label>{{ p.nachname }}, {{ p.vorname }}</q-item-label>
                <q-item-label v-if="p.mitgliedsnummer" caption>Nr. {{ p.mitgliedsnummer }}</q-item-label>
              </q-item-section>
              <q-item-section side class="row no-wrap q-gutter-xs">
                <q-badge v-if="p.ohne_geburtsdatum" outline color="warning" label="Geburtsdatum fehlt" />
                <q-badge v-if="p.ohne_geschlecht" outline color="warning" label="Geschlecht fehlt" />
              </q-item-section>
            </q-item>
          </q-list>
        </q-card>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import JahrgangTabelle from 'src/components/JahrgangTabelle.vue'
import { csvDownload } from 'src/utils/csv'
import { JAHRGANG_KOPF, jahrgangZeilen } from 'src/utils/meldung'

const $q = useQuasar()
const loading = ref(false)
const data = ref(null)
// Gemeldet wird im Januar, zum Jahresende davor.
const stichtag = ref(`${new Date().getFullYear() - 1}-12-31`)

function csvA() {
  csvDownload(`lsb-a-meldung-${data.value.stichtag}.csv`, JAHRGANG_KOPF, jahrgangZeilen(data.value.a))
}

function csvB() {
  csvDownload(`lsb-b-meldung-${data.value.stichtag}.csv`, ['Abteilung', ...JAHRGANG_KOPF],
    data.value.b.flatMap((abt) => jahrgangZeilen(abt, [abt.name])))
}

async function load() {
  if (!stichtag.value) return
  loading.value = true
  try {
    const res = await api.get('/api/berichte/lsb-meldung', { params: { stichtag: stichtag.value } })
    data.value = res.data
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Laden der LSB-Meldung' })
  } finally {
    loading.value = false
  }
}

onMounted(load)
defineExpose({ load })
</script>
