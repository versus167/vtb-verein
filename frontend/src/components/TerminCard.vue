<template>
  <q-card flat bordered class="termin-card" :class="{ 'termin-card--abgesagt': abgesagt }">
    <!-- Kopf: farbiger Balken mit Datumsblock, Titel, Status/Menü -->
    <div class="termin-card__kopf row items-center no-wrap"
      :class="abgesagt ? 'bg-negative' : 'bg-primary'"
      :style="klickbar ? 'cursor:pointer' : ''" @click="onKopfClick">
      <div class="termin-card__datum column items-center justify-center text-white">
        <div class="text-caption text-weight-medium" style="line-height:1">{{ wochentag(datumIso) }}</div>
        <div class="text-weight-bold" style="line-height:1.2">{{ tagMonat(datumIso) }}</div>
      </div>
      <div class="col termin-card__titel text-white">
        <div class="text-subtitle1 text-weight-bold termin-card__zeilen">
          {{ terminTitel(termin) }}
        </div>
        <!-- Ort/Bemerkung mit in der Kopfzeile. Umbruch statt einzeilig: Adressen
             wie „Sportplatz am Jahnhaus, Rußdorfer Straße 10, 09212 Limbach-O."
             passen auf dem Handy in keine Zeile. -->
        <div v-if="untertitel" class="text-caption termin-card__zeilen" style="opacity:.85">
          {{ untertitel }}
        </div>
      </div>
      <q-icon v-if="termin.serie_id" name="repeat" color="white" size="18px"
        class="q-mr-xs" style="opacity:.85">
        <q-tooltip>Teil einer Serie</q-tooltip>
      </q-icon>
      <!-- Offene Frage aus dem Spielplan-Import (#95): nur für Verwalter, führt
           direkt in die Entscheidung – sonst bliebe sie unbemerkt liegen. -->
      <q-badge v-if="darfVerwalten && offeneAbweichungen" color="warning"
        text-color="dark" class="q-mr-sm text-weight-bold termin-card__abweichung"
        @click.stop="abweichungOffen = true">
        <q-icon name="sync_problem" size="14px" class="q-mr-xs" />{{ offeneAbweichungen }}
        <q-tooltip>DFBnet weicht ab – bitte entscheiden</q-tooltip>
      </q-badge>
      <!-- Kein Handlungsbedarf, aber wissenswert: Der Termin steht anders da als in
           der offiziellen Ansetzung (verworfene Frage oder Änderung des Teams).
           Dezent und in anderer Farbe als die offene Frage – und nur, wenn keine
           offene Frage denselben Termin ohnehin schon markiert. -->
      <q-badge v-else-if="darfVerwalten && externDiff.length" color="white"
        text-color="primary" class="q-mr-sm text-weight-bold termin-card__abweichung"
        @click.stop="abweichungOffen = true">
        <q-icon name="sync_alt" size="14px" class="q-mr-xs" />DFBnet
        <q-tooltip>
          <div class="text-weight-medium">Weicht von der DFBnet-Ansetzung ab</div>
          <div v-for="d in externDiff" :key="d.feld">
            {{ abweichungFeldLabel(d.feld) }} laut DFBnet:
            {{ abweichungWert(d.feld, d.dfbnet) }}
          </div>
          <div class="text-italic q-mt-xs">
            Kein Handlungsbedarf – prüfen, ob das DFBnet nachzieht.
          </div>
        </q-tooltip>
      </q-badge>
      <!-- „Meine Termine": als Gast eingetragen (Antwort ohne Kader-Zugehörigkeit) -->
      <q-badge v-if="termin.gast" color="vtb-gelb" text-color="primary"
        class="q-mr-sm text-weight-bold">GAST</q-badge>
      <q-badge v-if="abgesagt" color="white" text-color="negative"
        class="q-mr-sm text-weight-bold">ABGESAGT</q-badge>
      <!-- Verwalter bekommen das Menü auch am Dashboard (kompakt) – direkt editieren -->
      <q-btn v-if="darfVerwalten" flat round dense icon="more_vert" color="white"
        @click.stop>
        <q-menu auto-close>
          <q-list dense style="min-width: 170px">
            <q-item clickable @click="emit('bearbeiten', termin)">
              <q-item-section avatar><q-icon name="edit" size="xs" /></q-item-section>
              <q-item-section>Bearbeiten</q-item-section>
            </q-item>
            <q-item v-if="!abgesagt" clickable @click="emit('absagen', termin)">
              <q-item-section avatar><q-icon name="event_busy" size="xs" /></q-item-section>
              <q-item-section>Absagen</q-item-section>
            </q-item>
            <q-item v-else clickable @click="emit('reaktivieren', termin)">
              <q-item-section avatar><q-icon name="event_available" size="xs" /></q-item-section>
              <q-item-section>Reaktivieren</q-item-section>
            </q-item>
            <q-item clickable @click="emit('loeschen', termin)">
              <q-item-section avatar><q-icon name="delete" size="xs" color="negative" /></q-item-section>
              <q-item-section class="text-negative">Löschen</q-item-section>
            </q-item>
          </q-list>
        </q-menu>
      </q-btn>
      <q-icon v-else-if="kompakt" name="chevron_right" color="white" class="q-mr-sm" />
    </div>

    <!-- Zeiten -->
    <div class="row items-center termin-card__zeiten text-center">
      <div class="col">
        <span class="text-grey-7 text-caption">Treffen </span>
        <span class="text-weight-medium">{{ treffen }}</span>
      </div>
      <q-separator vertical />
      <div class="col">
        <span class="text-grey-7 text-caption">Beginn </span>
        <span class="text-weight-medium">{{ beginn }}</span>
      </div>
      <q-separator vertical />
      <div class="col">
        <span class="text-grey-7 text-caption">Ende </span>
        <span class="text-weight-medium">{{ ende }}</span>
      </div>
    </div>

    <div v-if="!kompakt && metaText" class="termin-card__meta text-caption text-grey-7 ellipsis">
      <q-icon name="place" size="14px" /> {{ metaText }}
    </div>

    <q-separator />

    <!-- Zu-/Absagen -->
    <div class="row items-center termin-card__rsvp no-wrap">
      <q-btn v-for="a in ANTWORTEN" :key="a.key" class="col"
        :flat="termin.meine_antwort !== a.key" :unelevated="termin.meine_antwort === a.key"
        :color="termin.meine_antwort === a.key ? a.color : 'grey-7'"
        :text-color="termin.meine_antwort === a.key ? 'white' : undefined"
        dense no-caps square :disable="!termin.kann_zusagen || busy || abgesagt" @click="toggle(a.key)">
        <q-icon :name="a.icon" size="20px" />
        <span class="q-ml-xs text-weight-medium">{{ zaehler(a.key) }}</span>
        <q-tooltip>{{ a.label }}</q-tooltip>
      </q-btn>
      <!-- Route zum Spielort: als echter Link, damit das Gerät seine Navi-App
           anbietet. Hier unten statt in einer eigenen Zeile — in der Leiste ist
           Platz, und die Trefferfläche stimmt fürs Handy. -->
      <template v-if="kartenZiel">
        <q-separator vertical />
        <q-btn class="col-auto q-px-md" flat dense icon="directions" color="grey-8"
          type="a" :href="kartenZiel"
          :target="kartenZiel.startsWith('http') ? '_blank' : undefined"
          rel="noopener" @click.stop>
          <q-tooltip>Route zum Ort</q-tooltip>
        </q-btn>
      </template>
      <q-separator vertical />
      <q-btn class="col-auto q-px-md" flat dense icon="groups" color="grey-8"
        @click="kaderOffen = true">
        <q-tooltip>Kader &amp; Antworten</q-tooltip>
      </q-btn>
    </div>

    <!-- Abgesagt friert die Antworten ein: Setz-Buttons im Dialog ausblenden -->
    <TerminKaderDialog v-model="kaderOffen" :termin-id="termin.id"
      :darf-verwalten="darfVerwalten && !abgesagt" @geaendert="emit('reload')" />

    <TerminAbweichungDialog v-if="darfVerwalten" v-model="abweichungOffen"
      :termin-id="termin.id" :darf-verwalten="darfVerwalten"
      :extern-diff="externDiff" :termin-version="termin.version"
      @geaendert="emit('reload')" />
  </q-card>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import TerminKaderDialog from 'components/TerminKaderDialog.vue'
import TerminAbweichungDialog from 'components/TerminAbweichungDialog.vue'
import { ANTWORTEN, terminTitel, uhrzeit, wochentag, tagMonat, kartenLink,
         abweichungFeldLabel, abweichungWert } from 'src/composables/useTermine'

const props = defineProps({
  termin: { type: Object, required: true },
  darfVerwalten: { type: Boolean, default: false },
  kompakt: { type: Boolean, default: false },   // Dashboard-Variante: kein Menü, Kopf klickbar
})
const emit = defineEmits(['bearbeiten', 'absagen', 'reaktivieren', 'loeschen', 'reload', 'oeffnen'])

const $q = useQuasar()
const busy = ref(false)
const kaderOffen = ref(false)
const abweichungOffen = ref(false)

const abgesagt = computed(() => props.termin.status === 'abgesagt')
const offeneAbweichungen = computed(() => props.termin.abweichungen_offen ?? 0)
// Stille Abweichung vom DFBnet-Stand: keine offene Frage, aber der Termin steht
// anders da als die offizielle Ansetzung (verworfen oder vom Team geändert).
const externDiff = computed(() => props.termin.extern_diff ?? [])
const datumIso = computed(() => (props.termin.beginn ?? '').slice(0, 10))
const treffen = computed(() => props.termin.treffpunkt_zeit || '--:--')
const beginn = computed(() => uhrzeit(props.termin.beginn) || '--:--')
const ende = computed(() => uhrzeit(props.termin.ende) || '--:--')
const klickbar = computed(() => props.kompakt)
// Kopfzeile 2: Mannschaft · Ort · Bemerkung (Ellipsis, wenn der Platz ausgeht)
const untertitel = computed(() => {
  const t = props.termin
  return [t.mannschaft_name, t.ort, t.beschreibung].filter(Boolean).join(' · ')
})
// Ort steht im Kopf – hier nur noch der Treffpunkt
const metaText = computed(() =>
  props.termin.treffpunkt ? `Treffpunkt: ${props.termin.treffpunkt}` : '')
// Navigation zum Spielort; leer, solange kein Ort am Termin steht.
const kartenZiel = computed(() => kartenLink(props.termin.ort, $q.platform.is))

function zaehler(key) {
  return props.termin.zusagen?.[key] ?? 0
}
function onKopfClick() {
  if (props.kompakt) emit('oeffnen', props.termin)
}

function toggle(key) {
  if (props.termin.meine_antwort === key) return senden(key, null, true)  // zurücknehmen
  if (key === 'zu') return senden(key, null)
  // Absage/Vielleicht: Kommentar ist Pflicht (für die ganze Mannschaft sichtbar)
  const a = ANTWORTEN.find(x => x.key === key)
  $q.dialog({
    title: a.label,
    message: 'Bitte kurz begründen (für die Mannschaft sichtbar):',
    prompt: { model: '', type: 'textarea', isValid: v => v.trim().length > 0 },
    cancel: true,
  }).onOk(kommentar => senden(key, kommentar.trim()))
}

async function senden(key, kommentar, zuruecknehmen = false) {
  busy.value = true
  try {
    if (zuruecknehmen) {
      await api.delete(`/api/termine/${props.termin.id}/zusage`)
    } else {
      await api.put(`/api/termine/${props.termin.id}/zusage`, { antwort: key, kommentar })
    }
    emit('reload')
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Speichern fehlgeschlagen' })
  } finally {
    busy.value = false
  }
}
</script>

<style lang="scss" scoped>
.termin-card {
  border-radius: 12px;
  overflow: hidden;
  // Die Liste ist ein Flex-Column-Container: Ohne min-width:0 klebt die Karte an
  // ihrer min-content-Breite und sprengt auf dem Handy den Bildschirm — sichtbar
  // als seitlich scrollende Terminliste.
  min-width: 0;
  max-width: 100%;
}
.termin-card--abgesagt .termin-card__titel .text-subtitle1 {
  text-decoration: line-through;
}
.termin-card__kopf {
  min-height: 56px;
  gap: 12px;
  padding-right: 6px;
}
.termin-card__datum {
  min-width: 58px;
  align-self: stretch;
  padding: 6px 8px;
  background: rgba(0, 0, 0, 0.12);
}
.termin-card__titel {
  min-width: 0;
}
// Titel und Ortszeile dürfen umbrechen (zwei Zeilen, dann gekürzt). Einzeilig mit
// Ellipsis war die Ursache des Breitenproblems: `white-space: nowrap` macht den
// ganzen Text zur min-content-Breite, an der die Karte als Flex-Item hängen
// bleibt. `anywhere` bricht notfalls auch innerhalb langer Straßennamen.
.termin-card__zeilen {
  white-space: normal;
  overflow-wrap: anywhere;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.termin-card__zeiten {
  padding: 10px 8px;
}
.termin-card__meta {
  padding: 0 12px 8px;
}
.termin-card__rsvp {
  min-height: 44px;
}
.termin-card__abweichung {
  cursor: pointer;
}
</style>
