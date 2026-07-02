<template>
  <div class="stunden-kalender">
    <div v-for="monat in monate" :key="monat.key" class="q-mb-md">
      <div class="text-subtitle2 text-center q-mb-xs">{{ monat.titel }}</div>

      <div class="kal-grid kal-head">
        <div v-for="wt in wochentage" :key="wt" class="kal-zelle">{{ wt }}</div>
      </div>

      <div v-for="(woche, wi) in monat.wochen" :key="wi" class="kal-grid">
        <div v-for="(zelle, zi) in woche" :key="zi" class="kal-zelle"
          :class="{ 'kal-ausserhalb': zelle && !zelle.imZeitraum }">
          <template v-if="zelle">
            <!-- Tag mit Einträgen: Datum ist durch die umkreiste Stundenzahl ersetzt -->
            <q-avatar v-if="zelle.termine.length" class="kal-badge cursor-pointer"
              color="primary" text-color="white" size="32px" font-size="13px">
              {{ fmtStd(zelle.summe) }}
              <q-menu anchor="bottom middle" self="top middle">
                <q-list dense style="min-width:210px">
                  <q-item-label header class="q-py-xs">{{ zelle.kopf }}</q-item-label>
                  <q-separator />
                  <q-item v-for="t in zelle.termine" :key="t.id">
                    <q-item-section>
                      <q-item-label>{{ fmtStd(t.stunden) }} Std.</q-item-label>
                      <q-item-label caption>{{ t.angebot || '—' }}</q-item-label>
                    </q-item-section>
                    <q-item-section side v-if="editable">
                      <q-btn flat dense round size="sm" icon="delete" color="negative"
                        @click="$emit('delete', t)" />
                    </q-item-section>
                  </q-item>
                </q-list>
              </q-menu>
            </q-avatar>
            <!-- Tag ohne Eintrag: normale Tageszahl -->
            <span v-else class="kal-tagnr">{{ zelle.tag }}</span>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  termine: { type: Array, default: () => [] },   // [{ id, datum, stunden, angebot }]
  von: { type: String, default: '' },            // Zeitraum-Anfang 'YYYY-MM-DD'
  bis: { type: String, default: '' },            // Zeitraum-Ende 'YYYY-MM-DD'
  editable: { type: Boolean, default: false },   // Löschen anbieten (nur im Entwurf)
})
defineEmits(['delete'])

const wochentage = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']
const monatsnamen = ['Januar', 'Februar', 'März', 'April', 'Mai', 'Juni',
  'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember']

// Stunden hübsch: ganze Zahl ohne Nachkomma, sonst mit Komma (1.5 → "1,5")
function fmtStd(v) {
  const n = Number(v)
  if (!Number.isFinite(n)) return ''
  if (Number.isInteger(n)) return String(n)
  return n.toFixed(2).replace(/0+$/, '').replace(/\.$/, '').replace('.', ',')
}
function iso(y, m0, d) {
  return `${y}-${String(m0 + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`
}
function isoWeekday(y, m0, d) {
  const wd = new Date(y, m0, d).getDay()
  return wd === 0 ? 7 : wd   // So=7 statt 0
}

// Termine nach Tag (ISO) gruppieren.
const proTag = computed(() => {
  const map = new Map()
  for (const t of props.termine) {
    const key = (t.datum || '').slice(0, 10)
    if (!key) continue
    if (!map.has(key)) map.set(key, [])
    map.get(key).push(t)
  }
  return map
})

// Je ein Kalendergitter pro Monat zwischen von und bis (inkl.).
const monate = computed(() => {
  const out = []
  const von = props.von || (props.termine[0]?.datum || '').slice(0, 10)
  const bis = props.bis || von
  if (!von) return out
  let y = Number(von.slice(0, 4))
  let m = Number(von.slice(5, 7)) - 1
  const ey = Number(bis.slice(0, 4))
  const em = Number(bis.slice(5, 7)) - 1
  // guard: Sicherheitslimit gegen Endlosschleife bei kaputten Grenzen
  for (let guard = 0; guard < 60 && (y < ey || (y === ey && m <= em)); guard++) {
    out.push(baueMonat(y, m))
    if (++m > 11) { m = 0; y++ }
  }
  return out
})

function baueMonat(y, m0) {
  const tageImMonat = new Date(y, m0 + 1, 0).getDate()
  const fuehrend = isoWeekday(y, m0, 1) - 1
  const zellen = []
  for (let i = 0; i < fuehrend; i++) zellen.push(null)
  for (let d = 1; d <= tageImMonat; d++) {
    const key = iso(y, m0, d)
    const termine = proTag.value.get(key) || []
    const summe = termine.reduce((s, t) => s + Number(t.stunden || 0), 0)
    const imZeitraum = (!props.von || key >= props.von) && (!props.bis || key <= props.bis)
    const wd = isoWeekday(y, m0, d)
    zellen.push({
      tag: d, key, termine, summe, imZeitraum,
      kopf: `${wochentage[wd - 1]}, ${String(d).padStart(2, '0')}.${String(m0 + 1).padStart(2, '0')}.${y}`,
    })
  }
  while (zellen.length % 7 !== 0) zellen.push(null)
  const wochen = []
  for (let i = 0; i < zellen.length; i += 7) wochen.push(zellen.slice(i, i + 7))
  return { key: `${y}-${m0}`, titel: `${monatsnamen[m0]} ${y}`, wochen }
}
</script>

<style scoped>
.kal-grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 2px; }
.kal-zelle { height: 40px; display: flex; align-items: center; justify-content: center; }
.kal-head .kal-zelle { height: auto; padding: 2px 0; font-size: 11px; font-weight: 600; opacity: 0.7; }
.kal-tagnr { color: #9e9e9e; font-size: 12px; }
.kal-ausserhalb .kal-tagnr { opacity: 0.45; }
.kal-badge { font-weight: 600; }
</style>
