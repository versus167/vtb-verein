<template>
  <!-- Vorlauf der Termin-Erinnerungen – vereinsweit, daher nur mit termine.verwalten -->
  <q-dialog v-model="open" @show="load">
    <q-card style="min-width: 380px; max-width: 92vw">
      <q-card-section class="row items-center q-pb-none">
        <div class="text-h6">Erinnerungen</div>
        <q-space />
        <q-btn flat round dense icon="close" v-close-popup />
      </q-card-section>

      <q-card-section>
        <div class="text-body2 q-mb-md">
          Einmal täglich sieht die App nach, zu welchen Terminen noch Meldungen fehlen,
          und erinnert genau die daran – Kader wie eingeladene Gäste, jeder nur zu
          seinen eigenen offenen Terminen. Wer zu-, ab- oder „vielleicht" gesagt hat,
          hört nichts.
          <span class="text-grey-8">
            Je Termin und Stufe geht die Erinnerung genau einmal raus;
            <strong>0 Tage</strong> heißt „diese Stufe nicht erinnern".
          </span>
        </div>

        <div class="row items-center no-wrap q-mb-sm">
          <div class="col text-subtitle1">Erinnerungen verschicken</div>
          <q-toggle v-model="einstellungen.aktiv" />
        </div>

        <div class="row q-col-gutter-sm">
          <div class="col-6">
            <q-input v-model.number="einstellungen.erste_stufe_tage" type="number"
              dense outlined min="0" :max="MAX_TAGE" suffix="Tage vorher"
              label="Erste Erinnerung" :disable="!einstellungen.aktiv" />
          </div>
          <div class="col-6">
            <q-input v-model.number="einstellungen.zweite_stufe_tage" type="number"
              dense outlined min="0" :max="MAX_TAGE" suffix="Tage vorher"
              label="Zweite Erinnerung" :disable="!einstellungen.aktiv" />
          </div>
        </div>

        <q-separator class="q-my-md" />

        <div class="row items-center no-wrap">
          <div class="col">
            <div class="text-subtitle1">Auch am Spieltag</div>
            <div class="text-caption text-grey-8">
              Am Termintag selbst – nur zu Spielen und nur, solange der Anpfiff noch
              bevorsteht. Beim Training ändert die Meldung am selben Tag kaum noch
              etwas, beim Spiel zählt jeder Kopf.
            </div>
          </div>
          <q-toggle v-model="einstellungen.spieltag_aktiv"
            :disable="!einstellungen.aktiv" />
        </div>
      </q-card-section>

      <q-card-actions align="right">
        <q-btn flat label="Abbrechen" v-close-popup />
        <q-btn label="Speichern" color="primary" unelevated
          :loading="saving" @click="speichern" />
      </q-card-actions>

      <q-inner-loading :showing="loading" />
    </q-card>
  </q-dialog>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'

// Obergrenze wie im Backend (VORLAUF_MAX_TAGE): Wer drei Monate vorher erinnert,
// hat sich vertippt.
const MAX_TAGE = 28

const props = defineProps({ modelValue: { type: Boolean, default: false } })
const emit = defineEmits(['update:modelValue'])

const $q = useQuasar()
const open = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const einstellungen = ref({ aktiv: true, erste_stufe_tage: 3, zweite_stufe_tage: 1,
                            spieltag_aktiv: true })
const loading = ref(false)
const saving = ref(false)

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/api/termine/erinnerung-einstellungen')
    einstellungen.value = data
  } catch {
    $q.notify({ type: 'negative', message: 'Einstellungen konnten nicht geladen werden' })
  } finally {
    loading.value = false
  }
}

async function speichern() {
  saving.value = true
  try {
    // Nur die Felder, die der Server kennt: `id`, `version` und die Zeitstempel
    // kommen beim Lesen mit, gehören aber nicht ins Schreib-Schema.
    const e = einstellungen.value
    await api.put('/api/termine/erinnerung-einstellungen', {
      aktiv: e.aktiv,
      erste_stufe_tage: e.erste_stufe_tage,
      zweite_stufe_tage: e.zweite_stufe_tage,
      spieltag_aktiv: e.spieltag_aktiv,
    })
    $q.notify({ type: 'positive', message: 'Erinnerungen gespeichert.' })
    open.value = false
  } catch (e) {
    $q.notify({ type: 'negative',
                message: e.response?.data?.detail || 'Fehler beim Speichern.' })
  } finally {
    saving.value = false
  }
}
</script>
