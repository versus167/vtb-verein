<template>
  <q-page padding :class="`page--${aktivesTheme}`">
    <!-- Kopf: am Handy Titel und Steuerung untereinander. Sieben Bedienelemente
         in einer Zeile brachen dort mitten im Segment-Umschalter um, was nach
         kaputtem Layout aussah statt nach Umbruch. -->
    <div class="row items-center q-col-gutter-sm q-mb-sm">
      <div class="col-12 col-sm">
        <div class="text-h5">Platzbelegung</div>
      </div>
      <div class="col-12 col-sm-auto row items-center no-wrap">
        <q-btn flat dense round icon="chevron_left" :disable="loading"
          @click="blaettern(-7)" aria-label="7 Tage zurück" />
        <q-btn flat dense no-caps :disable="loading" @click="heute" label="Heute" />
        <q-btn flat dense round icon="chevron_right" :disable="loading"
          @click="blaettern(7)" aria-label="7 Tage vor" />
        <q-space />
        <q-btn-toggle v-model="modus" :options="MODUS_AUSWAHL" :disable="loading"
          unelevated rounded dense no-caps toggle-color="primary" class="vtb-segment q-ml-sm" />
      </div>
    </div>

    <div class="row items-center q-mb-sm">
      <div class="text-subtitle1 text-weight-medium">{{ zeitraumTitel }}</div>
      <q-space />
      <q-spinner v-if="loading" color="primary" size="20px" />
    </div>

    <!-- Der Hinweis erklärt die Ansicht einmal; am Handy kostete er vier Zeilen
         vom ersten Bildschirm und steht deshalb eingeklappt. -->
    <div v-if="$q.screen.gt.xs" class="text-caption text-grey q-mb-md">{{ hinweis }}</div>
    <q-expansion-item v-else dense dense-toggle icon="info" label="Was der Plan zeigt"
      class="q-mb-sm" header-class="text-caption text-grey">
      <div class="text-caption text-grey q-pb-sm q-pl-sm">{{ hinweis }}</div>
    </q-expansion-item>

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

    <!-- Am Handy: Tag für Tag statt Raster, und innerhalb des Tages Platz für
         Platz. Leere Tage fallen weg, sonst scrollt man an fünf Überschriften
         ohne Inhalt vorbei. -->
    <div v-else>
      <div v-for="tag in tageMitBelegung" :key="tag.iso" class="belegung-tag">
        <div class="belegung-tag-kopf" :class="{ 'belegung-tag-kopf--heute': tag.istHeute }">
          {{ tag.wochentag }}, {{ tag.kurz }}
        </div>
        <template v-for="gruppe in tagesGruppen(tag.iso)" :key="gruppe.platz.id">
          <div class="belegung-platz-kopf">{{ gruppe.platz.name }}</div>
          <div v-for="zeile in gruppe.zeilen" :key="zeile.schluessel" class="belegung-zeile">
            <div class="belegung-zeit-spalte">
              <span class="row items-center no-wrap">
                {{ zeile.zeit }}
                <q-icon v-if="zeile.konflikt" name="warning" color="negative"
                  size="14px" class="q-ml-xs" />
              </span>
              <span v-if="zeile.marker" class="belegung-marker">{{ zeile.marker }}</span>
            </div>
            <div class="belegung-teams">
              <span v-for="t in zeile.termine" :key="t.id"
                class="belegung-chip"
                :class="{
                  'belegung-chip--eigen': !!t.eigen,
                  'belegung-chip--abgesagt': t.status === 'abgesagt',
                  'belegung-chip--konflikt': zeile.gemischt && konflikte.has(t.id),
                  'belegung-chip--editierbar': !!t.darf_verwalten,
                }"
                :role="t.darf_verwalten ? 'button' : undefined"
                :tabindex="t.darf_verwalten ? 0 : undefined"
                :title="t.darf_verwalten ? `${terminTitel(t)} bearbeiten` : undefined"
                @click="t.darf_verwalten && bearbeiten(t)"
                @keydown.enter.prevent="t.darf_verwalten && bearbeiten(t)"
                @keydown.space.prevent="t.darf_verwalten && bearbeiten(t)">
                {{ terminTitel(t) }}
              </span>
            </div>
          </div>
        </template>
      </div>
      <div v-if="!tageMitBelegung.length && !loading" class="text-grey q-pa-md">
        In diesem Zeitraum ist kein eigener Platz belegt.
      </div>
    </div>

    <!-- Bearbeiten direkt im Plan: derselbe Dialog wie auf der Termine-Seite.
         `mannschaft-id` braucht er nicht — hier wird nur bearbeitet, nie angelegt. -->
    <TerminFormDialog v-model="formOpen" :termin="formTermin" @saved="laden" />
  </q-page>
</template>

<script setup>
import { computed, h, onMounted, ref, watch } from 'vue'
import { QIcon, useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { usePageRefresh } from 'src/composables/useRefresh'
import { aktivesTheme } from 'src/composables/useTheme'
import TerminFormDialog from 'components/TerminFormDialog.vue'

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

// ── Darstellung eines Termins (Raster wie Handy-Liste teilen sich das) ──

function zeitfenster(t) {
  const von = (t.beginn || '').slice(11, 16)
  return t.ende ? `${von}–${t.ende.slice(11, 16)}` : von
}

function terminTitel(t) {
  return [t.mannschaft_name || 'Ohne Mannschaft', t.gegner ? `vs. ${t.gegner}` : null]
    .filter(Boolean).join(' ')
}

/** Alles außer Mannschaft und Zeit: „Spiel", „Sonstiges", „abgesagt". */
function markerVon(t) {
  const teile = []
  if (t.typ !== 'training') teile.push(t.typ === 'spiel' ? 'Spiel' : 'Sonstiges')
  if (t.status === 'abgesagt') teile.push('abgesagt')
  return teile.join(' · ')
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
 * Ein Tag für die Handy-Ansicht: Plätze als Zwischenüberschrift, darunter je
 * Zeitfenster eine Zeile.
 *
 * Zusammengefasst wird, was sich nur in der Mannschaft unterscheidet. Acht
 * Nachwuchsteams, die um 16:15 auf denselben Platz gehen, waren vorher acht
 * Einträge à drei Zeilen mit achtmal demselben Platznamen und achtmal derselben
 * Uhrzeit — genau das machte die Seite am Handy unlesbar lang.
 *
 * Typ und Status gehören zum Schlüssel: Ein abgesagtes Training darf nicht in
 * derselben Zeile stehen wie ein laufendes, sonst behauptete die Zeile etwas
 * Falsches darüber, ob der Platz frei ist.
 */
function tagesGruppen(tagIso) {
  const gruppen = []
  for (const platz of plaetze.value) {
    const eintraege = belegungVon(platz.id, tagIso)
    if (!eintraege.length) continue
    // Map statt Sortieren: `belegungVon` liefert schon nach Beginn sortiert,
    // die Einfügereihenfolge erhält das.
    const zeilen = new Map()
    for (const t of eintraege) {
      const schluessel = `${t.beginn}|${t.ende || ''}|${t.typ}|${t.status}`
      if (!zeilen.has(schluessel)) {
        zeilen.set(schluessel, {
          schluessel, zeit: zeitfenster(t), marker: markerVon(t), termine: [],
        })
      }
      zeilen.get(schluessel).termine.push(t)
    }
    // Das Warndreieck steht an der Uhrzeit statt an jedem Kürzel: Gleiches
    // Zeitfenster heißt gleiche Überschneidungsmenge, die Antwort fällt für alle
    // Termine der Zeile gleich aus. Acht Kürzel einzeln zu markieren wiederholte
    // also nur dieselbe Aussage — und genau diese Wiederholung war das Problem.
    // `gemischt` ist der Notausgang, falls die Konfliktregel je feiner wird:
    // Dann tragen die betroffenen Kürzel zusätzlich ihren roten Streifen.
    for (const zeile of zeilen.values()) {
      const betroffen = zeile.termine.filter((t) => konflikte.value.has(t.id)).length
      zeile.konflikt = betroffen > 0
      zeile.gemischt = betroffen > 0 && betroffen < zeile.termine.length
    }
    gruppen.push({ platz, zeilen: [...zeilen.values()] })
  }
  return gruppen
}

/**
 * Ein Termin im Raster: Zeit, Mannschaft, bei Spielen der Gegner.
 *
 * Als Render-Funktion statt eigener Datei — der Block ist reine Darstellung dieser
 * einen Seite und hätte anderswo keinen Nutzen. Die Handy-Liste nutzt ihn nicht:
 * Dort steht dieselbe Information zusammengefasst in einer Zeile.
 *
 * Termine eigener Mannschaften sind hervorgehoben und — wenn man sie verwalten darf
 * — anklickbar. Beides entscheidet das Backend je Termin (`eigen`, `darf_verwalten`),
 * nicht die Anzeige: Die Kader-ACL gehört nicht ins Frontend.
 */
const TerminBlock = (props) => {
  const t = props.termin
  const editierbar = !!t.darf_verwalten
  const abgesagt = t.status === 'abgesagt'
  const titel = terminTitel(t)
  const marker = markerVon(t)
  const zeilen = [
    h('div', { class: 'belegung-zeit row items-center no-wrap' }, [
      h('span', zeitfenster(t)),
      props.konflikt ? h(QIcon, {
        name: 'warning', color: 'negative', size: '14px', class: 'q-ml-xs',
      }) : null,
    ]),
    h('div', { class: 'belegung-team' }, titel),
  ]
  if (marker) zeilen.push(h('div', { class: 'belegung-typ text-caption' }, marker))
  return h('div', {
    class: ['belegung-block', {
      'belegung-block--abgesagt': abgesagt,
      'belegung-block--eigen': !!t.eigen,
      'belegung-block--konflikt': props.konflikt,
      'belegung-block--editierbar': editierbar,
    }],
    ...(editierbar ? {
      role: 'button',
      tabindex: 0,
      title: `${titel} bearbeiten`,
      onClick: () => bearbeiten(t),
      onKeydown: (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); bearbeiten(t) }
      },
    } : {}),
  }, zeilen)
}
TerminBlock.props = { termin: Object, konflikt: Boolean }

// ── Bearbeiten (nur eigene bzw. mit termine.verwalten) ──
const formOpen = ref(false)
const formTermin = ref(null)
const hatEigene = computed(() => termine.value.some((t) => t.eigen))

const hinweis = computed(() => [
  'Wer wann auf welchem eigenen Platz ist — über alle Mannschaften hinweg.',
  'Abgesagte Termine bleiben stehen: Sie sagen, dass der Platz doch frei ist.',
  hatEigene.value
    ? 'Die eigenen Mannschaften sind hervorgehoben; anklicken bearbeitet den Termin.'
    : null,
].filter(Boolean).join(' '))

function bearbeiten(t) {
  formTermin.value = t
  formOpen.value = true
}

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

.belegung-block--abgesagt {
  opacity: 0.55;
  text-decoration: line-through;
}

/* Eigene Mannschaft: VTB-Blau am Rand (semantisch über `primary`, der einzige
   erlaubte Blauton) UND ein kräftigerer Grundton plus fettere Schrift. Die Farbe
   allein trüge nicht — im Theme „VTB" liegt der Plan selbst auf Wappenblau, dort
   erkennt man den Block am Ton und am Gewicht. Steht VOR --konflikt, damit die
   Warnung den Rand behält: Ein Konflikt ist die wichtigere Aussage. */
.belegung-block--eigen {
  border-left-color: var(--q-primary);
  background: rgba(128, 128, 128, 0.26);
}

.belegung-block--eigen .belegung-team {
  font-weight: 600;
}

.belegung-block--konflikt {
  border-left-color: var(--q-negative);
}

.belegung-block--editierbar {
  cursor: pointer;
}

.belegung-block--editierbar:hover {
  background: rgba(128, 128, 128, 0.34);
}

.belegung-block--editierbar:focus-visible {
  outline: 2px solid currentColor;
  outline-offset: 1px;
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

/* ── Handy: Tagesliste ──────────────────────────────────────────────────────
   Bewusst ohne q-list/q-item: Deren 48px Mindesthöhe und 16px Seitenpolster
   sind Tippziel-Maße für Menüzeilen. Hier steht je Zeile eine Uhrzeit und ein
   paar Mannschaftskürzel — sieben Tage ergaben damit eine Seite von über
   viertausend Pixeln Höhe. */
.belegung-tag {
  margin-bottom: 14px;
}

.belegung-tag-kopf {
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 4px;
  background: rgba(128, 128, 128, 0.14);
}

.belegung-tag-kopf--heute {
  outline: 2px solid currentColor;
  outline-offset: -2px;
}

.belegung-platz-kopf {
  font-size: 0.78rem;
  opacity: 0.7;
  margin: 6px 0 1px 2px;
}

.belegung-zeile {
  display: flex;
  gap: 8px;
  padding: 2px 0 2px 8px;
  border-left: 2px solid rgba(128, 128, 128, 0.3);
}

.belegung-zeit-spalte {
  flex: 0 0 auto;
  min-width: 82px;
  padding-top: 3px;
  font-size: 0.8rem;
  font-weight: 600;
  line-height: 1.25;
  font-variant-numeric: tabular-nums;
}

.belegung-marker {
  display: block;
  font-weight: 400;
  font-size: 0.72rem;
  opacity: 0.75;
}

.belegung-teams {
  display: flex;
  flex-wrap: wrap;
  gap: 3px 5px;
  font-size: 0.85rem;
  line-height: 1.25;
}

/* Kein `nowrap`: Bei einem Spiel steht der Gegner mit im Kürzel, und der passt
   am Handy nicht immer in eine Zeile. */
.belegung-chip {
  padding: 3px 6px;
  border-radius: 3px;
  background: rgba(128, 128, 128, 0.14);
  overflow-wrap: anywhere;
}

.belegung-chip--abgesagt {
  opacity: 0.55;
  text-decoration: line-through;
}

/* Wie im Raster: eigene Mannschaft am kräftigeren Grundton und am Gewicht, die
   Farbe allein trägt in den dunklen Themes nicht. --konflikt steht danach und
   übernimmt den Randstreifen. */
.belegung-chip--eigen {
  font-weight: 600;
  background: rgba(128, 128, 128, 0.28);
  box-shadow: inset 2px 0 0 var(--q-primary);
}

.belegung-chip--konflikt {
  box-shadow: inset 2px 0 0 var(--q-negative);
}

.belegung-chip--editierbar {
  cursor: pointer;
}

.belegung-chip--editierbar:focus-visible {
  outline: 2px solid currentColor;
  outline-offset: 1px;
}
</style>
