<template>
  <!-- Zeitlicher Ausschnitt für Matrix und Auswertung der Teamkasse (#167):
       entweder ein Termin (Training/Spiel) oder ein einzelner Tag. Zwei Fragen,
       die sich nicht decken — „was lief beim Spiel" ist nicht „was lief zwischen
       0 und 24 Uhr", weil ein Abend über Mitternacht laufen kann. -->
  <div class="row items-center q-gutter-sm">
    <q-btn-toggle
      :model-value="modelValue.modus"
      :options="[
        { label: 'Termin', value: 'termin' },
        { label: 'Tag', value: 'tag' },
      ]"
      unelevated dense no-caps class="vtb-segment"
      toggle-color="primary"
      @update:model-value="v => setzen({ modus: v })"
    />

    <q-select
      v-if="modelValue.modus === 'termin'"
      :model-value="modelValue.termin"
      :options="terminOptionen"
      emit-value map-options dense outlined options-dense
      class="tt-ausschnitt-feld"
      label="Termin"
      @update:model-value="v => setzen({ termin: v })"
    />

    <q-input
      v-else
      :model-value="modelValue.tag"
      type="date" dense outlined
      class="tt-ausschnitt-feld"
      label="Tag"
      @update:model-value="v => setzen({ tag: v })"
    />
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  modelValue: { type: Object, required: true },
  termine: { type: Array, default: () => [] },
  laufendId: { type: Number, default: null },
})
const emit = defineEmits(['update:modelValue'])

const terminOptionen = computed(() => props.termine.map(t => ({
  // Der laufende Termin wird markiert: Am Tresen ist genau er fast immer gemeint.
  label: t.id === props.laufendId ? `${t.label} · läuft` : t.label,
  value: t.id,
})))

function setzen(aenderung) {
  emit('update:modelValue', { ...props.modelValue, ...aenderung })
}
</script>

<style lang="scss" scoped>
.tt-ausschnitt-feld {
  min-width: 200px;
  max-width: 320px;
}
</style>
