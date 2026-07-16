<template>
  <!-- Auf Handy/Tablet Vollbild (lange Kader-Listen), am Desktop normales Dialog-Fenster -->
  <q-dialog v-model="open" :maximized="$q.screen.lt.md" @show="onShow">
    <!-- Nur im Vollbild (Handy/Tablet) Flex-Spalte mit scrollender Liste; am Desktop
         normale Auto-Höhe — dort würde `col` (flex-basis 0) den Inhalt kollabieren. -->
    <q-card :class="$q.screen.lt.md ? 'column no-wrap' : ''"
      :style="$q.screen.lt.md ? '' : 'min-width: 380px; max-width: 92vw'">
      <q-card-section class="row items-center q-pb-none"
        :class="$q.screen.lt.md ? 'col-auto' : ''">
        <div class="text-h6">Kader &amp; Antworten</div>
        <q-space />
        <q-btn flat round dense icon="close" v-close-popup />
      </q-card-section>

      <!-- Gast eintragen: feststehend unter dem Titel, nur mit Verwalter-Recht -->
      <q-card-section v-if="darfVerwalten" class="q-pb-none"
        :class="$q.screen.lt.md ? 'col-auto' : ''">
        <q-select v-model="gastAuswahl" :options="kandidatenGefiltert"
          use-input input-debounce="0" outlined dense clearable
          label="Gast aus der Abteilung eintragen"
          :option-label="k => k.mannschaften ? `${k.name} (${k.mannschaften})` : k.name"
          :disable="busy" @filter="filterKandidaten" @update:model-value="gastEintragen">
          <template #no-option>
            <q-item><q-item-section class="text-grey">Keine Kandidaten gefunden</q-item-section></q-item>
          </template>
        </q-select>
        <div class="text-caption text-grey-7 q-mt-xs">
          Gäste werden mit Zusage eingetragen und können ihre Antwort selbst ändern.
        </div>
      </q-card-section>

      <!-- Nur die Liste scrollt – Kopf und Gast-Auswahl bleiben stehen -->
      <q-card-section style="min-height: 120px" class="relative-position"
        :class="$q.screen.lt.md ? 'col scroll' : 'kader-dialog__liste'">
        <q-inner-loading :showing="loading" />
        <div v-if="!loading && kader.length === 0" class="text-grey text-center q-py-md">
          Kein Kader hinterlegt.
        </div>
        <div v-for="grp in gruppen" :key="grp.key" class="q-mb-md">
          <div class="text-subtitle2 text-weight-bold text-grey-8 q-mb-xs">
            <q-icon :name="grp.icon" :color="grp.color" size="18px" class="q-mr-xs" />{{ grp.label }} ({{ grp.leute.length }})
          </div>
          <q-list separator>
            <q-item v-for="p in grp.leute" :key="p.mitglied_id" class="q-px-none">
              <q-item-section>
                <q-item-label class="kader-dialog__name">
                  {{ p.name }}
                  <q-badge v-if="p.gast" color="vtb-gelb" text-color="primary"
                    class="q-ml-xs text-weight-bold">Gast</q-badge>
                </q-item-label>
                <q-item-label v-if="p.rollen" caption class="kader-dialog__rolle">{{ p.rollen }}</q-item-label>
                <q-item-label v-if="p.kommentar" caption class="kader-dialog__rolle text-italic">
                  „{{ p.kommentar }}"
                </q-item-label>
              </q-item-section>
              <q-item-section v-if="darfVerwalten" side>
                <div class="row no-wrap q-gutter-xs">
                  <q-btn v-for="a in ANTWORTEN" :key="a.key" flat dense round :size="btnSize"
                    :icon="a.icon" :color="p.antwort === a.key ? a.color : 'grey-5'"
                    :disable="busy" @click="setFuer(p, a.key)">
                    <q-tooltip>{{ a.label }}</q-tooltip>
                  </q-btn>
                </div>
              </q-item-section>
            </q-item>
          </q-list>
        </div>
      </q-card-section>
    </q-card>
  </q-dialog>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { ANTWORTEN } from 'src/composables/useTermine'

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

const kader = ref([])
const loading = ref(false)
const busy = ref(false)

// Auf Touch-Geräten größere Buttons (bessere Trefferfläche)
const btnSize = computed(() => ($q.screen.lt.md ? 'md' : 'sm'))

// Gruppen in fester Reihenfolge: Zusage, Vielleicht, Absage, dann Offen.
const GRUPPEN = [
  ...ANTWORTEN,
  { key: null, icon: 'radio_button_unchecked', color: 'grey-6', label: 'Offen' },
]
const gruppen = computed(() =>
  GRUPPEN.map(g => ({ ...g, leute: kader.value.filter(p => p.antwort === g.key) }))
    .filter(g => g.leute.length > 0),
)

async function load() {
  loading.value = true
  try {
    const { data } = await api.get(`/api/termine/${props.terminId}/kader`)
    // Gäste (Antworten ohne Kader-Zugehörigkeit) laufen in denselben
    // Antwort-Gruppen mit, nur mit Gast-Badge markiert.
    kader.value = [
      ...data.kader,
      ...(data.gaeste ?? []).map(p => ({ ...p, gast: true })),
    ]
  } catch {
    $q.notify({ type: 'negative', message: 'Kader konnte nicht geladen werden' })
    kader.value = []
  } finally {
    loading.value = false
  }
}

// ── Gäste eintragen (nur Verwalter) ───────────────────────────
const kandidaten = ref([])
const kandidatenGefiltert = ref([])
const gastAuswahl = ref(null)

async function loadKandidaten() {
  if (!props.darfVerwalten) return
  try {
    const { data } = await api.get(`/api/termine/${props.terminId}/gast-kandidaten`)
    kandidaten.value = data
  } catch {
    kandidaten.value = []
  }
}

function onShow() {
  load()
  loadKandidaten()
}

// Kandidaten ohne die bereits Eingetragenen, gefiltert nach Sucheingabe
function filterKandidaten(val, update) {
  update(() => {
    const drin = new Set(kader.value.map(p => p.mitglied_id))
    const s = val.toLowerCase()
    kandidatenGefiltert.value = kandidaten.value.filter(k =>
      !drin.has(k.mitglied_id)
      && (!s || `${k.name} ${k.mannschaften}`.toLowerCase().includes(s)))
  })
}

async function gastEintragen(k) {
  if (!k) return
  busy.value = true
  try {
    await api.put(`/api/termine/${props.terminId}/zusage/${k.mitglied_id}`, { antwort: 'zu' })
    gastAuswahl.value = null
    await load()
    emit('geaendert')
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Gast konnte nicht eingetragen werden' })
  } finally {
    busy.value = false
  }
}

async function setFuer(p, key) {
  busy.value = true
  try {
    if (p.antwort === key) {
      await api.delete(`/api/termine/${props.terminId}/zusage/${p.mitglied_id}`)
    } else {
      await api.put(`/api/termine/${props.terminId}/zusage/${p.mitglied_id}`, { antwort: key })
    }
    await load()
    emit('geaendert')
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Speichern fehlgeschlagen' })
  } finally {
    busy.value = false
  }
}
</script>

<style lang="scss" scoped>
.kader-dialog__name {
  font-size: 15px;
}
.kader-dialog__rolle {
  font-size: 13px;
}
// Desktop: nur die Liste scrollt, Titel + Gast-Auswahl bleiben stehen
.kader-dialog__liste {
  max-height: 60vh;
  overflow-y: auto;
}
// Handy/Tablet: Liste läuft im Vollbild, Schrift entsprechend größer
@media (max-width: $breakpoint-sm-max) {
  .kader-dialog__name {
    font-size: 17px;
  }
  .kader-dialog__rolle {
    font-size: 14px;
  }
}
</style>
