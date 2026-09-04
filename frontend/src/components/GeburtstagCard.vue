<template>
  <q-card flat bordered class="geburtstag-card row items-center no-wrap">
    <!-- Datumsblock in derselben Breite wie an der Terminkarte, damit die
         gemischte Liste eine durchgehende linke Kante behält. Getönt statt
         farbig gefüllt: Ein Geburtstag ist ein Hinweis, kein Termin, und soll
         die Spiele und Trainings daneben nicht überstrahlen. -->
    <div class="geburtstag-card__datum column items-center justify-center">
      <div class="text-caption text-weight-medium" style="line-height:1">
        {{ wochentag(geburtstag.datum) }}
      </div>
      <div class="text-weight-bold" style="line-height:1.2">
        {{ tagMonat(geburtstag.datum) }}
      </div>
    </div>
    <q-icon name="cake" color="primary" size="22px" class="q-mx-sm" />
    <div class="col geburtstag-card__text">
      <div class="text-body2 text-weight-medium ellipsis">{{ name }}</div>
      <div v-if="untertitel" class="text-caption text-grey-7 ellipsis">{{ untertitel }}</div>
    </div>
  </q-card>
</template>

<script setup>
import { computed } from 'vue'
import { wochentag, tagMonat } from 'src/composables/useTermine'

const props = defineProps({
  geburtstag: { type: Object, required: true },
})

const name = computed(() => {
  const g = props.geburtstag
  return `${g.vorname || ''} ${g.nachname || ''}`.trim() || 'Ohne Namen'
})

// „wird 30 · Erste" – das Alter fehlt nur, wenn das Geburtsjahr in den
// Stammdaten unmöglich ist (Tippfehler); der Tag steht dann trotzdem da.
const untertitel = computed(() => {
  const g = props.geburtstag
  return [g.alter != null ? `wird ${g.alter}` : null, g.mannschaft_name]
    .filter(Boolean).join(' · ')
})
</script>

<style lang="scss" scoped>
.geburtstag-card {
  border-radius: 12px;
  overflow: hidden;
  // Wie an der Terminkarte: ohne min-width bleibt die Karte im Flex-Column an
  // ihrer min-content-Breite hängen und schiebt die Liste seitlich raus.
  min-width: 0;
  max-width: 100%;
  min-height: 48px;
  padding-right: 12px;
}
.geburtstag-card__datum {
  min-width: 58px;
  align-self: stretch;
  padding: 6px 8px;
  background: rgba($flaeche-rgb, 0.1);
}
.geburtstag-card__text {
  min-width: 0;
}
</style>
