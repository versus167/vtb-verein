<template>
  <!-- Wann/von wem eingereicht, freigegeben, exportiert – nur die Schritte,
       die schon passiert sind. Ein Entwurf hat noch keinen. -->
  <div v-if="rechnung?.eingereicht_am" class="text-caption text-grey-7">
    <div>
      <q-icon name="send" size="xs" /> Eingereicht am
      {{ fmtZeitpunkt(rechnung.eingereicht_am) }}
      <span v-if="rechnung.eingereicht_von">von {{ rechnung.eingereicht_von }}</span>
    </div>
    <div v-if="rechnung.freigegeben_am">
      <q-icon name="how_to_reg" size="xs" /> Freigegeben am
      {{ fmtZeitpunkt(rechnung.freigegeben_am) }}
      <span v-if="rechnung.freigegeben_von">von {{ rechnung.freigegeben_von }}</span>
    </div>
    <div v-if="rechnung.exportiert_am">
      <q-icon name="lock" size="xs" /> In Fibu exportiert am
      {{ fmtZeitpunkt(rechnung.exportiert_am) }}
      <span v-if="rechnung.exportiert_von">von {{ rechnung.exportiert_von }}</span>
    </div>
  </div>
</template>

<script setup>
import { fmtZeitpunkt } from 'src/composables/useRechnungen'

defineProps({
  rechnung: { type: Object, default: null },
})
</script>
