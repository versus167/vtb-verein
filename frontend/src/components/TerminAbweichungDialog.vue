<template>
  <q-dialog v-model="open" :maximized="$q.screen.lt.md" @show="load">
    <q-card :class="$q.screen.lt.md ? 'column no-wrap' : ''"
      :style="$q.screen.lt.md ? '' : 'min-width: 420px; max-width: 92vw'">
      <q-card-section class="row items-center q-pb-none"
        :class="$q.screen.lt.md ? 'col-auto' : ''">
        <div class="text-h6">Abweichungen laut DFBnet</div>
        <q-space />
        <q-btn flat round dense icon="close" v-close-popup />
      </q-card-section>

      <q-card-section class="q-pb-none" :class="$q.screen.lt.md ? 'col-auto' : ''">
        <div class="text-caption text-grey-7">
          Hier haben sich seit dem letzten Import <b>beide Seiten</b> geändert – der
          Import fasst den Termin deshalb nicht an. Beide Wege sind endgültig: Auch
          „Behalten" merkt sich den DFBnet-Stand, es wird also nicht erneut gefragt.
        </div>
      </q-card-section>

      <q-card-section style="min-height: 120px" class="relative-position"
        :class="$q.screen.lt.md ? 'col scroll' : 'abweichung-dialog__liste'">
        <q-inner-loading :showing="loading" />
        <div v-if="!loading && abweichungen.length === 0" class="text-grey text-center q-py-md">
          Keine Abweichungen.
        </div>

        <q-list separator>
          <q-item v-for="a in abweichungen" :key="a.id" class="q-px-none">
            <q-item-section>
              <q-item-label class="text-weight-medium">
                {{ feldLabel(a.feld) }}
                <q-badge v-if="a.status !== 'offen'" :color="statusFarbe(a.status)"
                  class="q-ml-xs">{{ statusLabel(a.status) }}</q-badge>
              </q-item-label>

              <q-item-label v-if="a.feld === 'entfallen'" caption>
                Steht im aktuellen Export nicht mehr – das kann eine Absage sein oder
                schlicht außerhalb des Auszugs liegen.
              </q-item-label>
              <q-item-label v-else caption>
                <span class="text-strike">{{ wertText(a.feld, a.wert_app) }}</span>
                <q-icon name="arrow_right_alt" size="18px" class="q-mx-xs" />
                <span class="text-weight-medium">{{ wertText(a.feld, a.wert_extern) }}</span>
                <span v-if="a.spielstaette_name"> ({{ a.spielstaette_name }})</span>
              </q-item-label>

              <q-item-label caption class="text-grey">
                erkannt {{ zeitpunkt(a.erkannt_am) }}
                <template v-if="a.entschieden_von">
                  · entschieden von {{ a.entschieden_von }}
                </template>
              </q-item-label>
            </q-item-section>

            <q-item-section v-if="a.status === 'offen' && darfVerwalten" side>
              <div class="row no-wrap q-gutter-xs">
                <q-btn unelevated dense no-caps color="primary" :disable="busy"
                  :label="a.feld === 'entfallen' ? 'Absagen' : 'Übernehmen'"
                  @click="entscheiden(a, 'uebernommen')" />
                <q-btn flat dense no-caps color="grey-8" :disable="busy"
                  :label="a.feld === 'entfallen' ? 'Findet statt' : 'Behalten'"
                  @click="entscheiden(a, 'verworfen')" />
              </div>
            </q-item-section>
          </q-item>
        </q-list>
      </q-card-section>

      <q-card-section v-if="darfVerwalten && hatOffene" class="q-pt-none"
        :class="$q.screen.lt.md ? 'col-auto' : ''">
        <q-toggle v-model="benachrichtigen" dense
          label="Kader über die Änderung informieren" />
      </q-card-section>
    </q-card>
  </q-dialog>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { datumLabel, uhrzeit } from 'src/composables/useTermine'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  terminId: { type: Number, required: true },
  darfVerwalten: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'geaendert'])

const $q = useQuasar()
const open = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const abweichungen = ref([])
const loading = ref(false)
const busy = ref(false)
const benachrichtigen = ref(true)

const hatOffene = computed(() => abweichungen.value.some(a => a.status === 'offen'))

const FELDER = {
  beginn: 'Anstoß', ort: 'Spielort', heim_auswaerts: 'Heimrecht',
  gegner: 'Gegner', entfallen: 'Spiel nicht mehr im Spielplan',
}
const STATUS = {
  uebernommen: { label: 'übernommen', farbe: 'positive' },
  verworfen: { label: 'behalten', farbe: 'grey-7' },
  hinfaellig: { label: 'erledigt', farbe: 'grey-6' },
}

function feldLabel(feld) {
  return FELDER[feld] ?? feld
}
function statusLabel(status) {
  return STATUS[status]?.label ?? status
}
function statusFarbe(status) {
  return STATUS[status]?.farbe ?? 'grey'
}

function wertText(feld, wert) {
  if (!wert) return '–'
  if (feld === 'beginn') return `${datumLabel(wert.slice(0, 10))} ${uhrzeit(wert)}`
  if (feld === 'heim_auswaerts') return wert === 'heim' ? 'Heimspiel' : 'Auswärtsspiel'
  return wert
}

// erkannt_am/entschieden_am sind echte Zeitstempel (TIMESTAMPTZ), keine Wandzeit.
function zeitpunkt(wert) {
  if (!wert) return ''
  const d = new Date(wert)
  return Number.isNaN(d.getTime())
    ? wert
    : d.toLocaleString('de-DE', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

async function load() {
  loading.value = true
  try {
    const { data } = await api.get(`/api/termine/${props.terminId}/abweichungen`)
    abweichungen.value = data
  } catch {
    $q.notify({ type: 'negative', message: 'Abweichungen konnten nicht geladen werden' })
    abweichungen.value = []
  } finally {
    loading.value = false
  }
}

async function entscheiden(a, entscheidung) {
  busy.value = true
  try {
    await api.post(`/api/termine/abweichungen/${a.id}/entscheiden`, {
      entscheidung,
      expected_version: a.version,
      benachrichtigen: benachrichtigen.value,
    })
    await load()
    emit('geaendert')
    $q.notify({
      type: 'positive',
      message: entscheidung === 'uebernommen' ? 'Termin angepasst' : 'Termin bleibt wie er ist',
    })
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Speichern fehlgeschlagen' })
  } finally {
    busy.value = false
  }
}
</script>

<style lang="scss" scoped>
// Desktop: nur die Liste scrollt, Kopf und Hinweis bleiben stehen
.abweichung-dialog__liste {
  max-height: 60vh;
  overflow-y: auto;
}
</style>
