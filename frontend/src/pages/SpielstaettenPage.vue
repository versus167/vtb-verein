<template>
  <q-page padding>
    <div class="row items-center q-mb-md q-gutter-sm">
      <div class="text-h5">Spielstätten</div>
      <q-space />
      <q-btn unelevated color="primary" icon="add" label="Neu" @click="neu" />
    </div>

    <div class="text-caption text-grey q-mb-md">
      Plätze und Hallen des Vereins – Grundlage für die Terminplanung und den
      Spielplan-Import. Nicht nur Fußball: Tennisplatz und Turnhalle gehören
      genauso hierher. Fremde Spielstätten (Auswärtsspiele) dürfen mit rein,
      sie zählen nur nicht als eigenes Gelände.
    </div>

    <q-list bordered separator>
      <q-item v-for="s in spielstaetten" :key="s.id" :clickable="!s.platzhalter"
        @click="s.platzhalter ? null : bearbeite(s)">
        <q-item-section avatar>
          <q-icon :name="s.platzhalter ? 'block' : (s.ist_eigen ? 'stadium' : 'place')"
            :color="s.ist_eigen ? 'primary' : 'grey-6'" />
        </q-item-section>
        <q-item-section>
          <q-item-label>
            {{ s.name }}
            <q-badge v-if="s.ist_eigen" color="vtb-gelb" text-color="primary"
              class="q-ml-xs text-weight-bold">eigener Platz</q-badge>
            <q-badge v-if="s.platzhalter" color="grey-7" class="q-ml-xs">Vorgabe</q-badge>
          </q-item-label>
          <q-item-label caption>
            <span v-if="s.platzhalter">
              Feste Vorgabe – nicht bearbeitbar
            </span>
            <template v-else>
              <span v-if="adresse(s)">{{ adresse(s) }}</span>
              <span v-else class="text-grey">keine Adresse</span>
              <span v-if="s.dfbnet_nr"> · DFBnet {{ s.dfbnet_nr }}</span>
              <span v-if="s.untergrund"> · {{ s.untergrund }}</span>
              <span v-if="s.parallel_moeglich > 1">
                · {{ s.parallel_moeglich }} parallel möglich
              </span>
            </template>
          </q-item-label>
        </q-item-section>
        <q-item-section v-if="!s.platzhalter" side>
          <q-icon name="chevron_right" color="grey-6" />
        </q-item-section>
      </q-item>
      <q-item v-if="spielstaetten.length === 0 && !loading">
        <q-item-section class="text-grey text-center q-py-md">
          Noch keine Spielstätten angelegt.
        </q-item-section>
      </q-item>
    </q-list>

    <q-dialog v-model="dialogOpen" persistent>
      <q-card style="min-width:340px; max-width:92vw">
        <q-card-section class="row items-center">
          <div class="text-h6">
            {{ aktuell?.id ? 'Spielstätte bearbeiten' : 'Neue Spielstätte' }}
          </div>
          <q-space />
          <q-btn flat dense round icon="close" v-close-popup />
        </q-card-section>
        <q-card-section class="q-pt-none q-gutter-sm">
          <q-input v-model="form.name" outlined dense label="Name *" autofocus />
          <q-input v-model="form.strasse" outlined dense label="Straße / Hausnr." />
          <div class="row q-gutter-sm">
            <q-input v-model="form.plz" outlined dense label="PLZ" class="col-4" />
            <q-input v-model="form.ort" outlined dense label="Ort" class="col" />
          </div>
          <q-select v-model="form.untergrund" outlined dense label="Untergrund"
            :options="UNTERGRUND_VORSCHLAEGE" use-input new-value-mode="add-unique"
            clearable hide-dropdown-icon input-debounce="0"
            hint="Wird am Termin angezeigt – danach wählen die Spieler ihre Schuhe."
            @new-value="(wert, done) => done(wert.trim(), 'add-unique')" />
          <q-toggle v-model="form.ist_eigen" label="Eigenes Vereinsgelände" dense />
          <q-input v-model="form.dfbnet_nr" outlined dense
            label="DFBnet-Spielstätten-Nr." hint="Nur nötig für den Spielplan-Import" />
          <q-input v-model.number="form.parallel_moeglich" outlined dense type="number"
            min="1" label="Parallel mögliche Belegungen"
            hint="Aus dem DFBnet-Feld „Max. parallele Spiele“. Überschneidungen werden nie
                  blockiert, nur angezeigt." />
          <div v-if="error" class="text-negative text-caption">{{ error }}</div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn v-if="aktuell?.id" flat color="negative" label="Löschen"
            :loading="busy" @click="loeschen" />
          <q-space />
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn unelevated color="primary" label="Speichern" :loading="busy"
            @click="speichern" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { usePageRefresh } from 'src/composables/useRefresh'

defineOptions({ name: 'SpielstaettenPage' })

const $q = useQuasar()

const spielstaetten = ref([])
const loading = ref(false)
const dialogOpen = ref(false)
const aktuell = ref(null)
const busy = ref(false)
// Vorschläge, keine feste Liste: Der DFBnet-Export bringt eigene Bezeichnungen
// mit, und Hallenböden lassen sich nicht vorab aufzählen.
const UNTERGRUND_VORSCHLAEGE = ['Rasen', 'Kunstrasen', 'Hartplatz', 'Halle', 'Asche']
const error = ref('')
const form = ref(leer())

function leer() {
  return { name: '', strasse: '', plz: '', ort: '', ist_eigen: false,
           dfbnet_nr: '', parallel_moeglich: 1, untergrund: null }
}

function adresse(s) {
  return [s.strasse, [s.plz, s.ort].filter(Boolean).join(' ')].filter(Boolean).join(', ')
}

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/api/spielstaetten/')
    spielstaetten.value = data
  } finally {
    loading.value = false
  }
}

function neu() {
  aktuell.value = null
  form.value = leer()
  error.value = ''
  dialogOpen.value = true
}

function bearbeite(s) {
  aktuell.value = s
  form.value = {
    name: s.name,
    strasse: s.strasse || '',
    plz: s.plz || '',
    ort: s.ort || '',
    ist_eigen: s.ist_eigen,
    dfbnet_nr: s.dfbnet_nr || '',
    parallel_moeglich: s.parallel_moeglich,
    untergrund: s.untergrund || null,
  }
  error.value = ''
  dialogOpen.value = true
}

async function speichern() {
  if (!form.value.name?.trim()) {
    error.value = 'Bitte einen Namen angeben.'
    return
  }
  busy.value = true
  error.value = ''
  const nutzlast = {
    name: form.value.name.trim(),
    strasse: form.value.strasse || null,
    plz: form.value.plz || null,
    ort: form.value.ort || null,
    ist_eigen: form.value.ist_eigen,
    dfbnet_nr: form.value.dfbnet_nr || null,
    parallel_moeglich: form.value.parallel_moeglich || 1,
    untergrund: form.value.untergrund || null,
  }
  try {
    if (aktuell.value?.id) {
      await api.put(`/api/spielstaetten/${aktuell.value.id}`,
        { ...nutzlast, expected_version: aktuell.value.version })
    } else {
      await api.post('/api/spielstaetten/', nutzlast)
    }
    dialogOpen.value = false
    await load()
  } catch (e) {
    error.value = e.response?.data?.detail || 'Speichern fehlgeschlagen'
  } finally {
    busy.value = false
  }
}

function loeschen() {
  $q.dialog({
    title: 'Spielstätte löschen',
    message: `„${aktuell.value.name}“ löschen? Das geht nur, solange kein Termin `
      + 'darauf verweist.',
    cancel: true,
    ok: { label: 'Löschen', color: 'negative' },
  }).onOk(async () => {
    busy.value = true
    try {
      await api.delete(`/api/spielstaetten/${aktuell.value.id}`)
      dialogOpen.value = false
      await load()
    } catch (e) {
      error.value = e.response?.data?.detail || 'Löschen fehlgeschlagen'
    } finally {
      busy.value = false
    }
  })
}

usePageRefresh(load)
onMounted(async () => {
  try { await load() } catch { $q.notify({ type: 'negative', message: 'Fehler beim Laden' }) }
})
</script>
