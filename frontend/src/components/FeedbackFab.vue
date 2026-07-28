<template>
  <!-- Trigger in der festen Kopfzeile. Früher ein FAB unten rechts, der auf
       Listen-Seiten den Pagination-Pfeil verdeckt hat (#69). Öffnet den
       gemeinsamen Anlege-Dialog – hier mit Screenshot der aktuellen Seite. -->
  <q-btn id="feedback-fab" flat :dense="$q.screen.gt.sm" round icon="feedback"
    @click="dialogOpen = true">
    <q-tooltip>Feedback / Screenshot</q-tooltip>
  </q-btn>

  <TicketAnlegenDialog v-model="dialogOpen" with-screenshot />
</template>

<script setup>
import { ref } from 'vue'
import { useQuasar } from 'quasar'
import TicketAnlegenDialog from 'src/components/TicketAnlegenDialog.vue'

const $q = useQuasar()
const dialogOpen = ref(false)
</script>
