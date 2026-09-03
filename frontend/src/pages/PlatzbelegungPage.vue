<template>
  <q-page padding :class="`page--${aktivesTheme}`">
    <div class="row items-center q-mb-sm q-gutter-sm">
      <div class="text-h5">Platzbelegung</div>
      <q-space />
      <q-btn-toggle v-model="modus" :options="MODUS_AUSWAHL" :disable="loading"
        unelevated rounded dense no-caps toggle-color="primary" class="vtb-segment" />
      <q-btn flat dense round icon="chevron_left" :disable="loading"
        @click="blaettern(-7)" aria-label="7 Tage zurück" />
      <q-btn flat dense no-caps :disable="loading" @click="heute" label="Heute" />
      <q-btn flat dense round icon="chevron_right" :disable="loading"
        @click="blaettern(7)" aria-label="7 Tage vor" />
    </div>

    <div class="row items-center q-mb-md">
      <div class="text-subtitle1 text-weight-medium">{{ zeitraumTitel }}</div>
      <q-space />
      <q-spinner v-if="loading" color="primary" size="20px" />
    </div>

    <div class="text-caption text-grey q-mb-md">
      Wer wann auf welchem eigenen Platz ist — über alle Mannschaften hinweg.
      Abgesagte Termine bleiben stehen: Sie sagen, dass der Platz doch frei ist.
    </div>

    <q-banner v-if="fehler" dense class="bg-negative text-white q-mb-md">
      {{ fehler }}
    </q-banner>

    <q-banner v-else-if="!loading && !plaetze.length" dense class="bg-blue-1 text-blue-10">
      <template #avatar><q-icon name="info" /></template>
      Es ist noch kein Platz als eigenes Gelände hinterlegt. Der Haken „eigener Platz"
      an der Spielstätte entscheidet, was hier auftaucht.
    </q-banner>

    <!-- Raster: Plätze als Zeilen, die sieben Tage als Spalten. Ab Tablet aufwärts —
         am Handy wären sieben Spalten unlesbar, dort steht die Tagesliste unten. -->
    <div v-else-if="$q.screen.gt.sm" class="belegung-raster">
      <div class="belegung-kopf belegung-ecke"></div>
      <div v-for="tag in tage" :key="`k-${tag.iso}`"
        class="belegung-kopf" :class="{ 'belegung-heute': tag.istHeute }">
        <div class="text-weight-medium">{{ tag.wochentag }}</div>
        <div class="text-caption">{{ tag.kurz }}</div>
      </div>

      <template v-for="platz in plaetze" :key="platz.id">
        <div class="belegung-platz">
          <div class="text-weight-medium">{{ platz.name }}</div>
          <div class="text-caption text-grey-7">
            <span v-if="platz.untergrund">{{ platz.untergrund }}</span>
            <span v-if="platz.parallel_moeglich > 1">
              <span v-if="platz.untergrund"> · </span>{{ platz.parallel_moeglich }} parallel
            </span>
          </div>
        </div>
        <div v-for="tag in tage" :key="`${platz.id}-${tag.iso}`"
          class="belegung-zelle" :class="{ 'belegung-heute': tag.istHeute }">
          <TerminBlock v-for="t in belegungVon(platz.id, tag.iso)" :key="t.id"
            :termin="t" :konflikt="konflikte.has(t.id)" />
        </div>
      </template>
    </div>

    <!-- Am Handy: Tag für Tag statt Raster. Leere Tage fallen weg, sonst scrollt
         man an fünf Überschriften ohne Inhalt vorbei. -->
    <div v-else>
      <div v-for="tag in tageMitBelegung" :key="tag.iso" class="q-mb-md">
        <div class="text-weight-medium q-mb-xs" :class="{ 'text-primary': tag.istHeute }">
          {{ tag.wochentag }}, {{ tag.kurz }}
        </div>
        <q-list bordered separator class="rounded-borders">
          <q-item v-for="eintrag in tagesListe(tag.iso)" :key="`${eintrag.platz.id}-${eintrag.termin.id}`">
            <q-item-section>
              <q-item-label caption>{{ eintrag.platz.name }}</q-item-label>
              <q-item-label>
                <TerminBlock :termin="eintrag.termin"
                  :konflikt="konflikte.has(eintrag.termin.id)" flach />
              </q-item-label>
            </q-item-section>
          </q-item>
        </q-list>
      </div>
      <div v-if="!tageMitBelegung.length && !loading" class="text-grey q-pa-md">
        In diesem Zeitraum ist kein eigener Platz belegt.
      </div>
    </div>
  </q-page>
</template>

<script setup>
import { computed, h, onMounted, ref, watch } from 'vue'
import { QIcon, useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { usePageRefresh } from 'src/composables/useRefresh'
import { aktivesTheme } from 'src/composables/useTheme'

defineOptions({ name: 'PlatzbelegungPage' })

const $q = useQuasar()

// Ein Termin ohne `ende` ist die Regel, nicht die Ausnahme (Training wird selten
// beendet). Für die Konflikt-Rechnung unten braucht er trotzdem eine Dauer; 90
// Minuten ist die übliche Einheit und im Zweifel eher zu lang als zu kurz — ein
// übersehener Konflikt wäre der teurere Fehler.
const ANNAHME_DAUER_MIN = 90

const WOCHENTAGE = ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag',
  'Samstag', 'Sonntag']

// Zwei Zuschnitte desselben Sieben-Tage-Fensters. „7 Tage" beginnt bei heute und
// ist die Alltagsfrage des Platzwarts (was steht als Nächstes an?), „Woche" liegt
// auf Mo–So und passt zu Aushängen und Absprachen, die in Kalenderwochen denken.
// Die Wahl gilt pro Gerät.
const MODUS_KEY = 'vtb_platzbelegung_modus'
const MODUS_AUSWAHL = [
  { label: '7 Tage', value: 'rollend' },
  { label: 'Woche', value: 'woche' },
]

const plaetze = ref([])
const termine = ref([])
const loading = ref(false)
const fehler = ref('')
const modus = ref(localStorage.getItem(MODUS_KEY) === 'woche' ? 'woche' : 'rollend')

// Geblättert wird als Versatz zu heute, nicht als festes Startdatum: Damit wandert
// das rollende Fenster von selbst mit, wenn die Seite über Mitternacht offen bleibt
// und der Auto-Refresh nachlädt.
const versatz = ref(0)
const heuteDatum = ref(tagesBeginn(new Date()))

/** `d` ohne Uhrzeit — Datumsvergleiche sollen nicht an der Tageszeit hängen. */
function tagesBeginn(d) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate())
}

/** Montag der Woche, in der `d` liegt — der Anker im Wochenmodus. */
function montagVon(d) {
  const kopie = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  const seitMontag = (kopie.getDay() + 6) % 7   // Sonntag = 0 → 6
  kopie.setDate(kopie.getDate() - seitMontag)
  return kopie
}

function iso(d) {
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const t = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${m}-${t}`
}

const heuteIso = computed(() => iso(heuteDatum.value))

/** Erster Tag des Fensters: heute bzw. Wochenanfang, um `versatz` verschoben. */
const startDatum = computed(() => {
  const d = modus.value === 'woche' ? montagVon(heuteDatum.value) : tagesBeginn(heuteDatum.value)
  d.setDate(d.getDate() + versatz.value)
  return d
})

const tage = computed(() => Array.from({ length: 7 }, (_, i) => {
  const d = new Date(startDatum.value)
  d.setDate(d.getDate() + i)
  return {
    iso: iso(d),
    wochentag: WOCHENTAGE[(d.getDay() + 6) % 7],
    kurz: `${String(d.getDate()).padStart(2, '0')}.${String(d.getMonth() + 1).padStart(2, '0')}.`,
    istHeute: iso(d) === heuteIso.value,
  }
}))

const zeitraumTitel = computed(() => {
  const t = tage.value
  return `${t[0].wochentag.slice(0, 2)} ${t[0].kurz} – ${t[6].wochentag.slice(0, 2)} ${t[6].kurz}`
})

/** Termine je Platz und Tag, aufsteigend nach Beginn. */
const nachPlatzUndTag = computed(() => {
  const map = new Map()
  for (const t of termine.value) {
    const schluessel = `${t.spielstaette_id}|${(t.beginn || '').slice(0, 10)}`
    if (!map.has(schluessel)) map.set(schluessel, [])
    map.get(schluessel).push(t)
  }
  for (const liste of map.values()) liste.sort((a, b) => a.beginn.localeCompare(b.beginn))
  return map
})

function belegungVon(platzId, tagIso) {
  return nachPlatzUndTag.value.get(`${platzId}|${tagIso}`) || []
}

const tageMitBelegung = computed(() =>
  tage.value.filter((tag) => plaetze.value.some((p) => belegungVon(p.id, tag.iso).length)))

function tagesListe(tagIso) {
  const zeilen = []
  for (const platz of plaetze.value) {
    for (const termin of belegungVon(platz.id, tagIso)) zeilen.push({ platz, termin })
  }
  return zeilen.sort((a, b) => a.termin.beginn.localeCompare(b.termin.beginn))
}

function minuten(zeitstempel) {
  const uhr = (zeitstempel || '').slice(11, 16)
  if (!uhr) return null
  return Number(uhr.slice(0, 2)) * 60 + Number(uhr.slice(3, 5))
}

function fenster(t) {
  const von = minuten(t.beginn)
  if (von === null) return null
  const bis = minuten(t.ende)
  return { von, bis: bis !== null && bis > von ? bis : von + ANNAHME_DAUER_MIN }
}

/**
 * Termine, die ihren Platz überbuchen.
 *
 * Nicht jede Überschneidung ist ein Konflikt: `parallel_moeglich` sagt, wie viele
 * Termine gleichzeitig draufpassen (geteiltes Kleinfeld, Halle mit zwei Feldern).
 * Gezählt wird deshalb je Startzeitpunkt, wie viele Termine gerade laufen —
 * überschreitet das die Kapazität, sind alle daran beteiligten markiert.
 * Abgesagte zählen nicht mit: Sie belegen nichts.
 */
const konflikte = computed(() => {
  const treffer = new Set()
  for (const platz of plaetze.value) {
    for (const tag of tage.value) {
      const aktive = belegungVon(platz.id, tag.iso)
        .filter((t) => t.status !== 'abgesagt')
        .map((t) => ({ t, f: fenster(t) }))
        .filter((e) => e.f)
      for (const { f } of aktive) {
        const gleichzeitig = aktive.filter((e) => e.f.von < f.bis && f.von < e.f.bis)
        if (gleichzeitig.length > platz.parallel_moeglich) {
          for (const e of gleichzeitig) treffer.add(e.t.id)
        }
      }
    }
  }
  return treffer
})

/**
 * Ein Termin im Raster: Zeit, Mannschaft, bei Spielen der Gegner.
 *
 * Als Render-Funktion statt eigener Datei — der Block ist reine Darstellung dieser
 * einen Seite und hätte anderswo keinen Nutzen. `flach` lässt den Rahmen weg, weil
 * er in der Handy-Liste schon in einem q-item steckt.
 */
const TerminBlock = (props) => {
  const t = props.termin
  const abgesagt = t.status === 'abgesagt'
  const zeit = (t.beginn || '').slice(11, 16)
    + (t.ende ? `–${t.ende.slice(11, 16)}` : '')
  const titel = [t.mannschaft_name || 'Ohne Mannschaft', t.gegner ? `vs. ${t.gegner}` : null]
    .filter(Boolean).join(' ')
  const zeilen = [
    h('div', { class: 'belegung-zeit row items-center no-wrap' }, [
      h('span', zeit),
      props.konflikt ? h(QIcon, {
        name: 'warning', color: 'negative', size: '14px', class: 'q-ml-xs',
      }) : null,
    ]),
    h('div', { class: 'belegung-team' }, titel),
  ]
  if (t.typ !== 'training') {
    zeilen.push(h('div', { class: 'belegung-typ text-caption' },
      t.typ === 'spiel' ? 'Spiel' : 'Sonstiges'))
  }
  if (abgesagt) zeilen.push(h('div', { class: 'belegung-typ text-caption' }, 'abgesagt'))
  return h('div', {
    class: ['belegung-block', {
      'belegung-block--flach': props.flach,
      'belegung-block--abgesagt': abgesagt,
      'belegung-block--konflikt': props.konflikt,
    }],
  }, zeilen)
}
TerminBlock.props = { termin: Object, konflikt: Boolean, flach: Boolean }

async function laden() {
  // Datum vor dem Laden nachziehen: Bei einer über Nacht offenen Seite zeigte das
  // rollende Fenster sonst weiter auf gestern.
  const jetzt = tagesBeginn(new Date())
  if (jetzt.getTime() !== heuteDatum.value.getTime()) heuteDatum.value = jetzt

  loading.value = true
  fehler.value = ''
  try {
    const { data } = await api.get('/api/spielstaetten/belegung', {
      params: { von: tage.value[0].iso, bis: tage.value[6].iso },
    })
    plaetze.value = data.plaetze
    termine.value = data.termine
  } catch (e) {
    fehler.value = e.response?.data?.detail || 'Belegungsplan konnte nicht geladen werden'
  } finally {
    loading.value = false
  }
}

function blaettern(schritt) {
  versatz.value += schritt
  laden()
}

function heute() {
  versatz.value = 0
  laden()
}

// Beim Umschalten zurück auf das aktuelle Fenster: Ein Versatz aus dem einen
// Zuschnitt sagt im anderen nichts aus, und gemeint ist ohnehin „was ist jetzt".
watch(modus, (wert) => {
  localStorage.setItem(MODUS_KEY, wert)
  versatz.value = 0
  laden()
})

onMounted(laden)
usePageRefresh(laden)
</script>

<style scoped>
.belegung-raster {
  display: grid;
  grid-template-columns: minmax(130px, 190px) repeat(7, minmax(0, 1fr));
  gap: 2px;
}

/* Farben kommen aus currentColor statt aus festen Hexwerten: Das Raster muss in
   allen drei Themes lesbar sein, und die Schriftfarbe kennt das Theme bereits. */
.belegung-kopf,
.belegung-platz,
.belegung-zelle {
  border-radius: 4px;
  padding: 6px 8px;
}

.belegung-kopf {
  text-align: center;
  background: rgba(128, 128, 128, 0.14);
}

.belegung-ecke {
  background: none;
}

.belegung-platz {
  background: rgba(128, 128, 128, 0.08);
}

.belegung-zelle {
  background: rgba(128, 128, 128, 0.04);
  min-height: 56px;
}

.belegung-heute {
  outline: 2px solid currentColor;
  outline-offset: -2px;
}

.belegung-block {
  border-left: 3px solid currentColor;
  padding: 2px 6px;
  margin-bottom: 4px;
  border-radius: 3px;
  background: rgba(128, 128, 128, 0.12);
  font-size: 0.78rem;
  line-height: 1.25;
}

.belegung-block:last-child {
  margin-bottom: 0;
}

.belegung-block--flach {
  border-left: none;
  background: none;
  padding: 0;
  margin: 0;
  font-size: 0.9rem;
}

.belegung-block--abgesagt {
  opacity: 0.55;
  text-decoration: line-through;
}

.belegung-block--konflikt {
  border-left-color: var(--q-negative);
}

.belegung-zeit {
  font-weight: 600;
}

.belegung-team {
  overflow-wrap: anywhere;
}

.belegung-typ {
  opacity: 0.75;
}
</style>
