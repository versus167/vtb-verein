<template>
  <!-- Termin-Auswahl für Buchen und Auswertung der Teamkasse (#167).
       Einen Tages-Ausschnitt gibt es bewusst nicht mehr: Jede Buchung hängt an
       einem Termin, und die Termine teilen die Zeitachse lückenlos unter sich
       auf — „der Tag" wäre damit nur eine zweite, ungenauere Schreibweise für
       dasselbe, die zudem über Mitternacht auseinanderfiele. -->
  <q-select
    :model-value="modelValue"
    :options="terminOptionen"
    emit-value map-options dense outlined options-dense
    class="tt-terminwahl"
    :label="label"
    @update:model-value="v => $emit('update:modelValue', v)"
  />
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
</script>

<style lang="scss" scoped>
.tt-terminwahl {
  min-width: 220px;
  max-width: 340px;
}
</style>
