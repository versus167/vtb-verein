<template>
  <!-- Serien einer Mannschaft: Liste + Bearbeiten + Löschen (nur Verwalter sinnvoll) -->
  <q-dialog v-model="open" :maximized="$q.screen.lt.md" @show="load">
    <q-card :class="$q.screen.lt.md ? 'column no-wrap' : ''"
      :style="$q.screen.lt.md ? '' : 'min-width: 460px; max-width: 92vw'">
      <q-card-section class="row items-center q-pb-none"
        :class="$q.screen.lt.md ? 'col-auto' : ''">
        <div class="text-h6">Terminserien</div>
        <q-space />
        <q-btn flat round dense icon="close" v-close-popup />
      </q-card-section>

      <q-card-section style="min-height: 100px" class="relative-position"
        :class="$q.screen.lt.md ? 'col scroll' : ''">
        <q-inner-loading :showing="loading" />
        <div v-if="!loading && serien.length === 0" class="text-grey text-center q-py-md">
          Keine Serien. Lege eine an über „Neuer Termin" → „Wöchentlich wiederholen".
        </div>

        <q-list separator>
          <template v-for="s in serien" :key="s.id">
            <q-item class="q-px-none">
              <q-item-section avatar>
                <q-icon name="repeat" color="primary" />
              </q-item-section>
              <q-item-section>
                <q-item-label>
                  {{ wochentag(s.start_datum) }} {{ s.beginn_zeit }}<template v-if="s.ende_zeit">–{{ s.ende_zeit }}</template>
                  · {{ s.typ === 'training' ? 'Training' : 'Sonstiges' }}
                </q-item-label>
                <q-item-label caption>
                  <span v-if="s.ort">{{ s.ort }} · </span>
                  {{ s.ende_datum ? `bis ${datumLabel(s.ende_datum)}` : 'offenes Ende' }}
                </q-item-label>
              </q-item-section>
              <q-item-section v-if="darfVerwalten" side>
                <div class="row no-wrap q-gutter-xs">
                  <q-btn flat dense round icon="edit" size="sm"
                    @click="editId = editId === s.id ? null : s.id; initEdit(s)" />
                  <q-btn flat dense round icon="delete" color="negative" size="sm"
                    @click="confirmDelete(s)" />
                </div>
              </q-item-section>
            </q-item>

            <!-- Inline-Bearbeitung: alles außer Wochentag (start_datum ist fix) -->
            <div v-if="editId === s.id" class="q-pa-sm q-mb-sm bg-grey-2 rounded-borders">
              <div class="text-caption text-grey-7 q-mb-sm">
                Änderungen gelten für zukünftige, nicht individuell geänderte Termine.
                Der Wochentag ist fix – dafür Serie löschen und neu anlegen.
              </div>
              <div class="q-gutter-sm">
                <q-select v-model="edit.typ" :options="typOptionen" option-value="value"
                  option-label="label" emit-value map-options label="Typ" outlined dense />
                <div class="row q-gutter-sm">
                  <q-input v-model="edit.beginnZeit" label="Beginn *" outlined dense type="time" class="col" />
                  <q-input v-model="edit.endeZeit" label="Ende" outlined dense type="time" class="col" />
                  <q-input v-model="edit.endeDatum" label="Serienende" outlined dense type="date" class="col" clearable />
                </div>
                <q-input v-model="edit.ort" label="Ort" outlined dense />
                <div class="row q-gutter-sm">
                  <q-input v-model="edit.treffpunkt" label="Treffpunkt" outlined dense class="col-7 col-grow" />
                  <q-input v-model="edit.treffpunktZeit" label="Treffpunkt-Zeit" outlined dense type="time" class="col" />
                </div>
                <q-input v-model="edit.beschreibung" label="Beschreibung" outlined dense autogrow />
                <div v-if="editError" class="text-negative text-caption">{{ editError }}</div>
                <div class="row justify-end q-gutter-sm">
                  <q-btn flat dense label="Abbrechen" @click="editId = null" />
                  <q-btn unelevated dense color="primary" label="Speichern"
                    :loading="saving" @click="saveEdit(s)" />
                </div>
              </div>
            </div>
          </template>
        </q-list>
      </q-card-section>
    </q-card>
  </q-dialog>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { wochentag, datumLabel } from 'src/composables/useTermine'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  mannschaftId: { type: [Number, String], required: true },
})
const emit = defineEmits(['update:modelValue', 'geaendert'])

const $q = useQuasar()
const open = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const typOptionen = [
  { label: 'Training', value: 'training' },
  { label: 'Sonstiges', value: 'sonstiges' },
]

const serien = ref([])
const darfVerwalten = ref(false)
const loading = ref(false)
const saving = ref(false)
const editId = ref(null)
const edit = ref({})
const editError = ref('')

async function load() {
  loading.value = true
  editId.value = null
  try {
    const { data } = await api.get(`/api/termine/mannschaften/${props.mannschaftId}/serien`)
    serien.value = data.serien
    darfVerwalten.value = data.darf_verwalten
  } catch {
    $q.notify({ type: 'negative', message: 'Serien konnten nicht geladen werden' })
    serien.value = []
  } finally {
    loading.value = false
  }
}

function initEdit(s) {
  editError.value = ''
  edit.value = { typ: s.typ, beginnZeit: s.beginn_zeit, endeZeit: s.ende_zeit ?? '',
                 ort: s.ort ?? '', treffpunkt: s.treffpunkt ?? '',
                 treffpunktZeit: s.treffpunkt_zeit ?? '', beschreibung: s.beschreibung ?? '',
                 endeDatum: s.ende_datum ?? '' }
}

async function saveEdit(s) {
  const e = edit.value
  if (!e.beginnZeit) {
    editError.value = 'Beginn ist erforderlich.'
    return
  }
  saving.value = true
  editError.value = ''
  try {
    await api.put(`/api/termine/serien/${s.id}`, {
      typ: e.typ,
      beginn_zeit: e.beginnZeit,
      ende_zeit: e.endeZeit || null,
      ort: e.ort || null,
      treffpunkt: e.treffpunkt || null,
      treffpunkt_zeit: e.treffpunktZeit || null,
      beschreibung: e.beschreibung || null,
      ende_datum: e.endeDatum || null,
      expected_version: s.version,
    })
    editId.value = null
    await load()
    emit('geaendert')
    $q.notify({ type: 'positive', message: 'Serie aktualisiert' })
  } catch (err) {
    editError.value = err.response?.data?.detail || 'Fehler beim Speichern'
  } finally {
    saving.value = false
  }
}

function confirmDelete(s) {
  $q.dialog({
    title: 'Serie löschen',
    message: `Serie „${wochentag(s.start_datum)} ${s.beginn_zeit}" wirklich löschen? ` +
      'Alle zukünftigen Termine der Serie werden entfernt, vergangene bleiben.',
    cancel: true, persistent: true,
  }).onOk(async () => {
    try {
      await api.delete(`/api/termine/serien/${s.id}`)
      await load()
      emit('geaendert')
    } catch (e) {
      $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' })
    }
  })
}
</script>
