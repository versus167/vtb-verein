<template>
  <!-- Termin-Auswahl für Buchen und Auswertung der Teamkasse (#167).
       Einen Tages-Ausschnitt gibt es bewusst nicht mehr: Jede Buchung hängt an
       einem Termin, und die Termine teilen die Zeitachse lückenlos unter sich
       auf — „der Tag" wäre damit nur eine zweite, ungenauere Schreibweise für
       dasselbe, die zudem über Mitternacht auseinanderfiele. -->
  <div class="row items-center no-wrap tt-terminwahl">
    <q-btn flat round dense icon="chevron_left" :disable="zielId(-1) === null"
      @click="$emit('update:modelValue', zielId(-1))">
      <q-tooltip>Vorheriger Termin</q-tooltip>
    </q-btn>
    <q-select
      :model-value="modelValue"
      :options="terminOptionen"
      emit-value map-options dense outlined options-dense
      class="col"
      :label="label"
      @update:model-value="v => $emit('update:modelValue', v)"
    />
    <q-btn flat round dense icon="chevron_right" :disable="zielId(1) === null"
      @click="$emit('update:modelValue', zielId(1))">
      <q-tooltip>Nächster Termin</q-tooltip>
    </q-btn>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  modelValue: { type: Number, default: null },
  termine: { type: Array, default: () => [] },
  laufendId: { type: Number, default: null },
  label: { type: String, default: 'Termin' },
})
defineEmits(['update:modelValue'])

const terminOptionen = computed(() => props.termine.map(t => ({
  // Der laufende Termin wird markiert: Am Tresen ist genau er fast immer gemeint.
  label: t.id === props.laufendId ? `${t.label} · läuft` : t.label,
  value: t.id,
})))

/** Termin-ids entlang der ZEITACHSE. Die Liste vom Backend kommt jüngste
 *  zuerst; geblättert wird aber vorwärts/rückwärts in der Zeit, nicht in der
 *  Anzeige-Reihenfolge. `beginn` ist Wandzeit-TEXT und damit lexikografisch
 *  vergleichbar. */
const idsChrono = computed(() => [...props.termine]
  .sort((a, b) => (a.beginn || '').localeCompare(b.beginn || ''))
  .map(t => t.id))

/** Ziel eines Schritts (−1 = vorheriger, +1 = nächster) oder null am Rand —
 *  daraus speist sich auch der Deaktiviert-Zustand der Pfeile. */
function zielId(schritt) {
  const ids = idsChrono.value
  const jetzt = ids.indexOf(props.modelValue)
  const ziel = jetzt >= 0 ? jetzt + schritt
    : (schritt > 0 ? 0 : ids.length - 1)      // ohne Auswahl: an den Rand
  return ziel >= 0 && ziel < ids.length ? ids[ziel] : null
}
</script>

<style lang="scss" scoped>
.tt-terminwahl {
  min-width: 260px;
  max-width: 400px;
}
</style>
