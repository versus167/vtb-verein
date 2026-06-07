<template>
  <q-page class="q-pa-md">
    <div class="text-h5 q-mb-md">Datenimport (SPG-Verein)</div>

    <q-card flat bordered class="q-mb-md" style="max-width: 720px">
      <q-card-section class="q-gutter-md">
        <q-file
          v-model="file"
          label="CSV-Export auswählen"
          accept=".csv,text/csv"
          outlined dense clearable
          :error="!!fileError" :error-message="fileError">
          <template #prepend><q-icon name="attach_file" /></template>
        </q-file>

        <div class="q-gutter-sm">
          <q-toggle v-model="commit" color="negative"
            :label="commit ? 'Schreiben (COMMIT) – Änderungen werden gespeichert' : 'Dry-Run – nur Vorschau, schreibt nichts'" />
          <div>
            <q-toggle v-model="update" dense label="Bestehende Mitglieder aktualisieren (per Mitgliedsnummer)" />
          </div>
          <div>
            <q-toggle v-model="allowUnmatched" dense
              label="Nicht zugeordnete Abteilungen überspringen (statt Abbruch)" />
          </div>
        </div>

        <q-banner v-if="commit" dense class="bg-orange-1 text-orange-9">
          <template #avatar><q-icon name="warning" color="orange" /></template>
          COMMIT ist aktiv – der Import schreibt direkt in die Datenbank.
        </q-banner>

        <q-btn
          :label="commit ? 'Import schreiben' : 'Vorschau erstellen'"
          :color="commit ? 'negative' : 'primary'"
          :icon="commit ? 'upload' : 'preview'"
          :loading="running" :disable="!file"
          unelevated @click="onStart" />
      </q-card-section>
    </q-card>

    <!-- Ergebnis -->
    <q-card v-if="result" flat bordered style="max-width: 720px">
      <q-card-section>
        <div class="row items-center">
          <div class="text-h6">Ergebnis</div>
          <q-space />
          <q-chip v-if="result.target_db" dense color="blue-grey" text-color="white" icon="storage">
            {{ result.target_db }}
          </q-chip>
          <q-chip :color="result.committed ? 'negative' : 'grey-7'" text-color="white" dense class="q-ml-xs">
            {{ result.committed ? 'COMMIT (geschrieben)' : 'DRY-RUN' }}
          </q-chip>
        </div>

        <q-banner v-if="result.aborted" class="bg-red-1 text-red-9 q-mt-sm" dense>
          <template #avatar><q-icon name="error" color="negative" /></template>
          <div class="text-weight-medium">Abgebrochen – nichts geschrieben</div>
          {{ result.abort_reason }}
        </q-banner>
      </q-card-section>

      <q-separator />

      <q-card-section>
        <div class="text-subtitle2 q-mb-xs">Abteilungs-Abgleich</div>
        <q-list dense bordered>
          <q-item v-for="a in result.abteilungs_abgleich" :key="a.name">
            <q-item-section avatar>
              <q-icon :name="a.matched ? 'check_circle' : 'cancel'"
                      :color="a.matched ? 'positive' : 'negative'" />
            </q-item-section>
            <q-item-section>{{ a.name }}</q-item-section>
            <q-item-section side>{{ a.count }} Mitglieder</q-item-section>
          </q-item>
          <q-item v-if="result.ehrenmitglieder_count">
            <q-item-section avatar><q-icon name="star" color="amber-8" /></q-item-section>
            <q-item-section>Ehrenmitglieder → Funktion „ehrenmitglied"</q-item-section>
            <q-item-section side>{{ result.ehrenmitglieder_count }}</q-item-section>
          </q-item>
        </q-list>
        <div v-if="result.unmatched_abteilungen.length" class="text-negative text-caption q-mt-xs">
          Nicht zugeordnet: {{ result.unmatched_abteilungen.join(', ') }}
          ({{ result.abt_unmatched_zuordnungen }} Zuordnungen übersprungen)
        </div>
      </q-card-section>

      <q-separator />

      <q-card-section class="row q-col-gutter-md">
        <div class="col-6 col-sm-4" v-for="s in summary" :key="s.label">
          <div class="text-h6">{{ s.value }}</div>
          <div class="text-caption text-grey-7">{{ s.label }}</div>
        </div>
      </q-card-section>

      <q-card-section v-if="result.neue_funktionen.length" class="q-pt-none text-caption text-grey-7">
        Neue Funktions-Katalogeinträge: {{ result.neue_funktionen.join(', ') }}
      </q-card-section>
    </q-card>
  </q-page>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'

const $q = useQuasar()

const file = ref(null)
const fileError = ref('')
const commit = ref(false)
const update = ref(false)
const allowUnmatched = ref(false)
const running = ref(false)
const result = ref(null)

const summary = computed(() => {
  const r = result.value
  if (!r) return []
  return [
    { label: 'Mitglieder neu', value: r.neu },
    { label: 'aktualisiert', value: r.aktualisiert },
    { label: 'übersprungen (existiert)', value: r.skip_exist },
    { label: 'übersprungen (kein Name)', value: r.skip_noname },
    { label: 'davon Ehrenmitglied', value: r.ehrenmitglied },
    { label: 'Kontakte', value: r.kontakte },
    { label: 'Abteilungs-Zuordnungen', value: r.abteilungen },
    { label: 'Funktions-Zuordnungen', value: r.funktionen },
    { label: 'Zeilen gelesen', value: r.rows },
  ]
})

async function doImport() {
  running.value = true
  fileError.value = ''
  try {
    const fd = new FormData()
    fd.append('file', file.value)
    fd.append('commit', commit.value ? 'true' : 'false')
    fd.append('update', update.value ? 'true' : 'false')
    fd.append('allow_unmatched', allowUnmatched.value ? 'true' : 'false')
    const { data } = await api.post('/api/import/spg', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    result.value = data
    if (data.aborted) {
      $q.notify({ type: 'warning', message: 'Import abgebrochen (siehe Ergebnis).' })
    } else if (data.committed) {
      $q.notify({ type: 'positive', message: `Import geschrieben: ${data.neu} neu, ${data.aktualisiert} aktualisiert.` })
    } else {
      $q.notify({ type: 'info', message: 'Vorschau erstellt (nichts geschrieben).' })
    }
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Import fehlgeschlagen' })
  } finally {
    running.value = false
  }
}

function onStart() {
  if (!file.value) {
    fileError.value = 'Bitte eine CSV-Datei wählen.'
    return
  }
  if (commit.value) {
    $q.dialog({
      title: 'Import schreiben?',
      message: 'Der Import schreibt direkt in die Datenbank. Fortfahren?',
      cancel: true, persistent: true,
      ok: { label: 'Schreiben', color: 'negative' },
    }).onOk(doImport)
  } else {
    doImport()
  }
}
</script>
