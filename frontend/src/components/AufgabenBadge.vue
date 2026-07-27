<template>
  <!-- Hinweis auf offene Aufgaben (#133). Ohne Aufgaben nichts anzeigen: eine
       „0" wäre ein Hinweis auf nichts und würde die Leiste nur unruhig machen. -->
  <q-badge v-if="anzahl > 0" rounded color="negative"
    :label="anzahl > 99 ? '99+' : anzahl"
    :aria-label="`${anzahl} offene Aufgaben`" />
</template>

<script setup>
defineOptions({ name: 'AufgabenBadge' })

defineProps({
  anzahl: { type: Number, default: 0 },
})
</script>
