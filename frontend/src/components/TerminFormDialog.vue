<template>
  <q-dialog v-model="open" persistent :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
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
        <!-- Serien nur beim Anlegen und nicht für Spiele -->
        <template v-if="!form.id && form.typ !== 'spiel'">
          <q-toggle v-model="form.wiederholen" label="Wöchentlich wiederholen" dense />
          <template v-if="form.wiederholen">
            <q-input v-model="form.serieEnde" label="Wiederholen bis (optional)"
              outlined dense type="date" clearable />
            <div class="text-caption text-grey-7">
              Termine werden rollierend 8 Wochen im Voraus erzeugt; der Wochentag
              ergibt sich aus dem Datum oben.
            </div>
          </template>
        </template>
        <div v-if="formError" class="text-negative text-caption">{{ formError }}</div>
      </q-card-section>
      <q-card-actions align="right">
        <q-btn flat label="Abbrechen" v-close-popup />
        <q-btn unelevated color="primary" :label="form.id ? 'Speichern' : 'Anlegen'"
          :loading="saving" @click="save" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { uhrzeit } from 'src/composables/useTermine'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  // Bearbeiten: bestehender Termin; null = Anlegen (dann ist mannschaftId nötig)
  termin: { type: Object, default: null },
  mannschaftId: { type: [Number, String], default: null },
})
const emit = defineEmits(['update:modelValue', 'saved'])

const $q = useQuasar()
const open = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const typOptionen = [
  { label: 'Training', value: 'training' },
  { label: 'Spiel', value: 'spiel' },
  { label: 'Sonstiges', value: 'sonstiges' },
]

const saving = ref(false)
const formError = ref('')
const form = ref({})

function leeresFormular() {
  return { id: null, version: null, typ: 'training',
           datum: new Date().toISOString().slice(0, 10), zeit: '', endeZeit: '',
           ort: '', treffpunkt: '', treffpunktZeit: '', gegner: '', heimAuswaerts: 'heim',
           beschreibung: '', wiederholen: false, serieEnde: '' }
}

watch(open, (offen) => {
  if (!offen) return
  const t = props.termin
  form.value = t
    ? { id: t.id, version: t.version, typ: t.typ,
        datum: t.beginn.slice(0, 10), zeit: uhrzeit(t.beginn), endeZeit: uhrzeit(t.ende ?? ''),
        ort: t.ort ?? '', treffpunkt: t.treffpunkt ?? '', treffpunktZeit: t.treffpunkt_zeit ?? '',
        gegner: t.gegner ?? '', heimAuswaerts: t.heim_auswaerts ?? 'heim',
        beschreibung: t.beschreibung ?? '' }
    : leeresFormular()
  formError.value = ''
})

async function save() {
  const f = form.value
  if (!f.datum || !f.zeit) {
    formError.value = 'Datum und Beginn sind erforderlich.'
    return
  }
  saving.value = true
  formError.value = ''
  try {
    if (!f.id && f.wiederholen && f.typ !== 'spiel') {
      // Wöchentliche Serie statt Einzeltermin
      await api.post(`/api/termine/mannschaften/${props.mannschaftId}/serien`, {
        typ: f.typ,
        beginn_zeit: f.zeit,
        ende_zeit: f.endeZeit || null,
        ort: f.ort || null,
        treffpunkt: f.treffpunkt || null,
        treffpunkt_zeit: f.treffpunktZeit || null,
        beschreibung: f.beschreibung || null,
        start_datum: f.datum,
        ende_datum: f.serieEnde || null,
      })
      open.value = false
      emit('saved')
      $q.notify({ type: 'positive', message: 'Serie angelegt' })
      return
    }
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
      await api.post(`/api/termine/mannschaften/${props.mannschaftId}`, payload)
    }
    open.value = false
    emit('saved')
    $q.notify({ type: 'positive', message: 'Gespeichert' })
  } catch (e) {
    formError.value = e.response?.data?.detail || 'Fehler beim Speichern'
  } finally {
    saving.value = false
  }
}
</script>
