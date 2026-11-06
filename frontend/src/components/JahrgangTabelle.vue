<template>
  <q-markup-table flat dense>
    <thead>
      <tr>
        <th class="text-left">Jahrgang</th>
        <th v-for="g in GESCHLECHTER" :key="g.key" class="text-right">{{ g.label }}</th>
        <th class="text-right">Summe</th>
      </tr>
    </thead>
    <tbody>
      <tr v-for="z in tabelle.zeilen" :key="z.jahrgang ?? 'ohne'">
        <td :class="{ 'text-grey-7': z.jahrgang == null }">{{ z.jahrgang ?? 'ohne Geburtsdatum' }}</td>
        <td v-for="g in GESCHLECHTER" :key="g.key" class="text-right">{{ z[g.key] || '' }}</td>
        <td class="text-right text-weight-medium">{{ z.summe }}</td>
      </tr>
      <tr v-if="!tabelle.zeilen.length">
        <td :colspan="GESCHLECHTER.length + 2" class="text-center text-grey-6">Niemand zum Stichtag</td>
      </tr>
    </tbody>
    <tfoot v-if="tabelle.zeilen.length">
      <tr class="text-weight-bold">
        <td>Summe</td>
        <td v-for="g in GESCHLECHTER" :key="g.key" class="text-right">{{ tabelle.summe[g.key] }}</td>
        <td class="text-right">{{ tabelle.summe.summe }}</td>
      </tr>
    </tfoot>
  </q-markup-table>
</template>

<script setup>
// Jahrgang × Geschlecht, wie es StatistikRepository._jahrgangstabelle liefert.
import { GESCHLECHTER } from 'src/utils/meldung'

defineProps({
  tabelle: { type: Object, required: true },
})
</script>

