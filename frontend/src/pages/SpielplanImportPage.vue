<template>
  <q-page padding>
    <div class="text-h5 q-mb-md">Spielplan-Import</div>

    <div class="text-caption text-grey q-mb-md">
      Vereinsspielplan aus dem DFBnet einlesen. Der erste Schritt ist immer eine
      Vorschau – erst danach lässt sich übernehmen. Spiele werden über die
      DFBnet-Zuordnung der Mannschaft erkannt (Teamname und Mannschaftsart),
      Spielstätten über ihre DFBnet-Nummer.
    </div>

    <q-card flat bordered class="q-pa-md q-mb-md">
      <q-file v-model="datei" outlined dense label="Spielplan-Datei (CSV aus dem DFBnet)"
        accept=".csv,.txt" :disable="busy" @update:model-value="bericht = null">
        <template #prepend><q-icon name="attach_file" /></template>
      </q-file>
      <div class="row q-gutter-sm q-mt-md items-center">
        <q-btn unelevated color="primary" icon="preview" label="Vorschau"
          :disable="!datei || busy" :loading="busy && !commitLaeuft" @click="senden(false)" />
        <q-btn v-if="bericht" unelevated color="positive" icon="download_done"
          label="Übernehmen" :disable="busy || nichtsZuTun"
          :loading="commitLaeuft" @click="uebernehmen" />
        <q-space />
        <q-toggle v-model="benachrichtigen" dense
          label="Kader über neue und verlegte Spiele informieren" />
      </div>
      <div v-if="fehler" class="text-negative q-mt-sm">{{ fehler }}</div>
    </q-card>

    <template v-if="bericht">
      <div class="row q-col-gutter-sm q-mb-md">
        <div v-for="k in kacheln" :key="k.schluessel" class="col-6 col-sm-4 col-md-2">
          <q-card flat bordered class="q-pa-sm text-center">
            <div class="text-h6">{{ k.wert }}</div>
            <div class="text-caption text-grey">{{ k.label }}</div>
          </q-card>
        </div>
      </div>

      <q-banner v-if="ergebnis" class="vtb-warnung q-mb-md" dense>
        {{ ergebnis.angelegt }} angelegt, {{ ergebnis.aktualisiert }} aktualisiert,
        {{ ergebnis.uebersprungen }} übersprungen.
      </q-banner>

      <q-banner v-if="ergebnis?.konflikte?.length" class="vtb-warnung q-mb-md">
        <template #avatar><q-icon name="warning" color="warning" /></template>
        <div class="text-weight-medium">
          {{ ergebnis.konflikte.length }} Termin(e) wurden nicht angefasst
        </div>
        <div class="text-caption">
          Hier weichen App und DFBnet beide vom letzten Importstand ab – das
          entscheidet der Betreuer, nicht der Import.
        </div>
        <ul class="q-my-xs">
          <li v-for="(k, i) in ergebnis.konflikte" :key="i" class="text-caption">
            {{ k.mannschaft }} · {{ k.felder.join(', ') }} — {{ k.grund }}
          </li>
        </ul>
      </q-banner>

      <q-banner v-if="ergebnis?.ohne_spielstaette?.length" class="vtb-warnung q-mb-md">
        <template #avatar><q-icon name="stadium" color="warning" /></template>
        <div class="text-weight-medium">Spielstätte fehlt</div>
        <div class="text-caption">
          Diese Spiele wurden übersprungen – die Spielstätte ist Pflichtfeld am
          Termin und wird nicht automatisch angelegt. Erst unter Einstellungen →
          Spielstätten eintragen, dann erneut übernehmen.
        </div>
        <ul class="q-my-xs">
          <li v-for="(s, i) in ergebnis.ohne_spielstaette" :key="i" class="text-caption">
            {{ s.name }} (DFBnet {{ s.dfbnet_nr }})
          </li>
        </ul>
      </q-banner>

      <q-banner v-if="bericht.fehler?.length" class="vtb-fehler q-mb-md">
        <div v-for="(f, i) in bericht.fehler" :key="i" class="text-caption">{{ f }}</div>
      </q-banner>

      <q-expansion-item v-if="bericht.neue_spielstaetten?.length"
        icon="add_location_alt" class="q-mb-sm"
        :label="`${bericht.neue_spielstaetten.length} noch nicht angelegte Spielstätte(n)`">
        <q-list dense>
          <q-item v-for="s in bericht.neue_spielstaetten" :key="s.dfbnet_nr">
            <q-item-section>
              <q-item-label>{{ s.name }}</q-item-label>
              <q-item-label caption>
                DFBnet {{ s.dfbnet_nr }} · {{ s.strasse }}, {{ s.plz }} {{ s.ort }}
                · {{ s.anzahl }}× im Plan
              </q-item-label>
            </q-item-section>
          </q-item>
        </q-list>
      </q-expansion-item>

      <q-expansion-item v-if="bericht.unbekannte_teams?.length"
        icon="groups" class="q-mb-sm"
        :label="`${bericht.unbekannte_teams.length} nicht zugeordnete Teamnamen`">
        <div class="text-caption text-grey q-pa-sm">
          Darunter sind auch die Gegner – zugeordnet werden muss nur, was eine
          eigene Mannschaft ist (Mannschaften → Team → DFBnet-Zuordnung).
        </div>
        <q-list dense>
          <q-item v-for="t in bericht.unbekannte_teams" :key="`${t.name}|${t.mannschaftsart}`">
            <q-item-section>
              <q-item-label>{{ t.name }}</q-item-label>
              <q-item-label caption>{{ t.mannschaftsart }} · {{ t.anzahl }}× im Plan</q-item-label>
            </q-item-section>
          </q-item>
        </q-list>
      </q-expansion-item>

      <q-list bordered separator>
        <q-item v-for="(b, i) in bericht.befunde" :key="i">
          <q-item-section avatar>
            <q-icon :name="symbol(b.einordnung).icon" :color="symbol(b.einordnung).farbe" />
          </q-item-section>
          <q-item-section>
            <q-item-label>
              {{ b.spiel.heim }} – {{ b.spiel.gast }}
              <span v-if="b.mannschaft_name" class="text-caption text-grey">
                · {{ b.mannschaft_name }} ({{ b.heim_auswaerts }})
              </span>
            </q-item-label>
            <q-item-label caption>
              {{ datumZeit(b.spiel.beginn) }} · {{ b.spiel.spielstaette }}
              · {{ symbol(b.einordnung).label }}
            </q-item-label>
            <q-item-label v-if="b.abweichungen?.length" caption class="text-warning">
              <span v-for="(a, j) in b.abweichungen" :key="j">
                {{ a.feld }}: „{{ a.app }}" → „{{ a.dfbnet }}"<span v-if="j < b.abweichungen.length - 1">, </span>
              </span>
            </q-item-label>
            <q-item-label v-if="b.hinweis" caption class="text-italic">{{ b.hinweis }}</q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
    </template>
  </q-page>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { datumLabel, uhrzeit } from 'src/composables/useTermine'

defineOptions({ name: 'SpielplanImportPage' })

const $q = useQuasar()

const datei = ref(null)
const bericht = ref(null)
const ergebnis = ref(null)
const busy = ref(false)
const commitLaeuft = ref(false)
const benachrichtigen = ref(false)
const fehler = ref('')

const EINORDNUNG = {
  neu: { label: 'wird angelegt', icon: 'add_circle', farbe: 'positive' },
  aenderung: { label: 'weicht ab', icon: 'sync_problem', farbe: 'warning' },
  unveraendert: { label: 'unverändert', icon: 'check_circle', farbe: 'grey-6' },
  platzbelegung: { label: 'Platzbelegung (fremdes Spiel auf eigenem Platz)', icon: 'stadium', farbe: 'info' },
  fremd: { label: 'betrifft uns nicht', icon: 'remove_circle_outline', farbe: 'grey-5' },
}

function symbol(einordnung) {
  return EINORDNUNG[einordnung] ?? { label: einordnung, icon: 'help', farbe: 'grey' }
}

function datumZeit(beginn) {
  if (!beginn) return ''
  return `${datumLabel(beginn.slice(0, 10))} ${uhrzeit(beginn)}`
}

const kacheln = computed(() => {
  const z = bericht.value?.zusammenfassung ?? {}
  return Object.entries(EINORDNUNG).map(([schluessel, meta]) => ({
    schluessel, label: meta.label, wert: z[schluessel] ?? 0,
  }))
})

// „Nichts zu tun" heißt: keine Zeile, die ein Lauf anlegen oder ändern würde.
const nichtsZuTun = computed(() => {
  const z = bericht.value?.zusammenfassung ?? {}
  return (z.neu ?? 0) === 0 && (z.aenderung ?? 0) === 0
})

async function senden(commit) {
  busy.value = true
  commitLaeuft.value = commit
  fehler.value = ''
  const form = new FormData()
  form.append('file', datei.value)
  form.append('commit', commit ? 'true' : 'false')
  form.append('benachrichtigen', benachrichtigen.value ? 'true' : 'false')
  try {
    const { data } = await api.post('/api/import/dfbnet', form)
    if (commit) {
      ergebnis.value = data
      bericht.value = data.bericht
      $q.notify({ type: 'positive',
        message: `${data.angelegt} angelegt, ${data.aktualisiert} aktualisiert` })
    } else {
      ergebnis.value = null
      bericht.value = data
    }
  } catch (e) {
    fehler.value = e.response?.data?.detail || 'Import fehlgeschlagen'
  } finally {
    busy.value = false
    commitLaeuft.value = false
  }
}

function uebernehmen() {
  const z = bericht.value?.zusammenfassung ?? {}
  $q.dialog({
    title: 'Spielplan übernehmen',
    message: `${z.neu ?? 0} Spiel(e) anlegen und ${z.aenderung ?? 0} abweichende prüfen? `
      + 'Termine, die in der App geändert wurden, bleiben unangetastet.',
    cancel: true, persistent: true,
  }).onOk(() => senden(true))
}
</script>
