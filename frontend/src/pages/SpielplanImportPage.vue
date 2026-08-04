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
        accept=".csv,.txt" :disable="busy"
        @update:model-value="bericht = null; zugeordnet = {}; angelegt = {}">
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
        {{ ergebnis.uebersprungen }} übersprungen<span v-if="ergebnis.spielstaetten_aktualisiert">,
        {{ ergebnis.spielstaetten_aktualisiert }} Spielstätte(n) nachgezogen</span>.
      </q-banner>

      <q-banner v-if="ergebnis?.konflikte?.length" class="vtb-warnung q-mb-md">
        <template #avatar><q-icon name="warning" color="warning" /></template>
        <div class="text-weight-medium">
          {{ ergebnis.konflikte.length }} Termin(e) warten auf eine Entscheidung
        </div>
        <div class="text-caption">
          Hier weichen App und DFBnet beide vom letzten Importstand ab – das
          entscheidet der Betreuer, nicht der Import. Die offenen Fragen stehen
          jetzt am Termin: unter „Termine" trägt die Karte ein Warn-Symbol.
        </div>
        <ul class="q-my-xs">
          <li v-for="(k, i) in ergebnis.konflikte" :key="i" class="text-caption">
            {{ k.mannschaft }} · {{ k.felder.join(', ') }} — {{ k.grund }}
          </li>
        </ul>
      </q-banner>

      <q-banner v-if="ergebnis?.entfallen" class="vtb-warnung q-mb-md">
        <template #avatar><q-icon name="event_busy" color="warning" /></template>
        <div class="text-weight-medium">
          {{ ergebnis.entfallen }} Spiel(e) stehen nicht mehr in diesem Auszug
        </div>
        <div class="text-caption">
          Abgesagt wird deswegen nichts: Der Export ist ein Zeitfenster-Auszug, kein
          Vollbestand — meist steckt eine Verlegung über den Zeitraum hinaus
          dahinter. Auch das entscheidet der Betreuer am Termin.
        </div>
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
        <div class="text-caption text-grey q-pa-sm">
          Ohne Spielstätte wird ein Spiel übersprungen – sie ist Pflichtfeld am Termin.
          Auch fremde Plätze gehören angelegt, sonst fehlen die Auswärtsspiele.
        </div>
        <div v-if="offeneAenderungen" class="q-px-sm q-pb-sm">
          <q-btn dense unelevated color="primary" icon="refresh" label="Vorschau aktualisieren"
            :disable="!datei || busy" :loading="busy" @click="senden(false)" />
        </div>
        <q-list dense>
          <q-item v-for="s in bericht.neue_spielstaetten" :key="s.dfbnet_nr">
            <q-item-section>
              <q-item-label>{{ s.name }}</q-item-label>
              <q-item-label caption>
                DFBnet {{ s.dfbnet_nr }} · {{ s.strasse }}, {{ s.plz }} {{ s.ort }}
                <span v-if="s.untergrund"> · {{ s.untergrund }}</span>
                · {{ s.anzahl }}× im Plan
              </q-item-label>
            </q-item-section>
            <q-item-section side>
              <div v-if="angelegt[s.dfbnet_nr]" class="text-caption text-positive">
                <q-icon name="check_circle" size="xs" /> {{ angelegt[s.dfbnet_nr] }}
              </div>
              <q-btn v-else-if="darfSpielstaetten" dense flat color="primary" icon="add_location_alt"
                label="Anlegen" @click="oeffneSpielstaette(s)" />
            </q-item-section>
          </q-item>
        </q-list>
      </q-expansion-item>

      <!-- Bekannte Plätze, deren Stammdaten der Lauf nachzieht. Hier gibt es
           nichts zu entscheiden: Anschrift, Belag und Kapazität stehen im
           DFBnet, das ist die offizielle Quelle. -->
      <q-expansion-item v-if="bericht.abweichende_spielstaetten?.length"
        icon="edit_location_alt" class="q-mb-sm"
        :label="`${bericht.abweichende_spielstaetten.length} Spielstätte(n) werden aktualisiert`">
        <div class="text-caption text-grey q-pa-sm">
          Anschrift, Untergrund und Kapazität kommen beim Übernehmen aus dem Export.
          Der Name bleibt, wie ihr ihn nennt – für die Zuordnung zählt ohnehin nur
          die DFBnet-Nummer.
        </div>
        <q-list dense>
          <q-item v-for="p in bericht.abweichende_spielstaetten" :key="p.id">
            <q-item-section>
              <q-item-label>{{ p.name }}</q-item-label>
              <q-item-label v-for="f in p.felder" :key="f.feld" caption>
                {{ STAETTE_FELDER[f.feld] ?? f.feld }}:
                <span v-if="f.app">„{{ f.app }}"</span>
                <span v-else class="text-italic">leer</span>
                → „{{ f.dfbnet }}"
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
          eigene Mannschaft ist.
        </div>
        <div v-if="offeneAenderungen" class="q-px-sm q-pb-sm">
          <q-btn dense unelevated color="primary" icon="refresh"
            label="Vorschau aktualisieren" :disable="!datei || busy" :loading="busy"
            @click="senden(false)" />
          <span class="text-caption text-grey q-ml-sm">
            {{ offeneAenderungen }} Änderung(en) gespeichert – wirkt sich erst auf
            die Vorschau aus, wenn sie neu gelesen wird.
          </span>
        </div>
        <q-list dense>
          <q-item v-for="t in bericht.unbekannte_teams" :key="teamKey(t)">
            <q-item-section>
              <q-item-label>{{ t.name }}</q-item-label>
              <q-item-label caption>{{ t.mannschaftsart }} · {{ t.anzahl }}× im Plan</q-item-label>
            </q-item-section>
            <q-item-section side>
              <div v-if="zugeordnet[teamKey(t)]" class="text-caption text-positive">
                <q-icon name="check_circle" size="xs" /> {{ zugeordnet[teamKey(t)] }}
              </div>
              <q-btn v-else-if="darfZuordnen" dense flat color="primary" icon="link"
                label="Zuordnen" @click="oeffneZuordnung(t)" />
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
            <!-- Je Feld dazu, was ein Lauf damit täte – „Vorschau = Aktion" -->
            <q-item-label v-for="(a, j) in b.abweichungen" :key="j" caption
              :class="a.wirkung === 'entscheidung' ? 'text-warning' : 'text-grey'">
              {{ a.feld }}: „{{ a.app }}" → „{{ a.dfbnet }}" — {{ WIRKUNG[a.wirkung] }}
            </q-item-label>
            <q-item-label v-if="b.hinweis" caption class="text-italic">{{ b.hinweis }}</q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
    </template>

    <!-- Zuordnung direkt aus der Vorschau: der Teamname steht fest (er kommt aus
         der Datei), gewählt wird die eigene Mannschaft. Umgekehrt müsste man den
         Namen exakt abtippen – genau das soll der Dialog ersparen. -->
    <q-dialog v-model="zuordnenOffen">
      <q-card style="min-width: 340px; max-width: 90vw">
        <q-card-section>
          <div class="text-subtitle1">DFBnet-Team zuordnen</div>
          <div class="text-caption text-grey">
            „{{ zuTeam?.name }}" · {{ zuTeam?.mannschaftsart }}
          </div>
        </q-card-section>

        <q-card-section class="q-gutter-md">
          <q-select v-model="abteilungFilter" :options="abteilungOptionen" outlined dense
            label="Abteilung" emit-value map-options
            hint="Schränkt die Auswahl unten ein – die Wahl wird gemerkt."
            @update:model-value="abteilungGewechselt" />

          <q-select v-model="zuMannschaft" :options="mannschaftOptionen" outlined dense
            label="Eigene Mannschaft" use-input input-debounce="0" fill-input hide-selected
            :loading="mannschaftenLaden" @filter="filterMannschaften">
            <template #option="{ itemProps, opt }">
              <q-item v-bind="itemProps">
                <q-item-section>
                  <q-item-label>{{ opt.label }}</q-item-label>
                  <q-item-label caption>{{ opt.caption }}</q-item-label>
                </q-item-section>
              </q-item>
            </template>
            <template #no-option>
              <q-item><q-item-section class="text-grey">Keine Mannschaft gefunden</q-item-section></q-item>
            </template>
          </q-select>

          <q-option-group v-if="zuMannschaft" v-model="zuModus" :options="modusOptionen" dense />

          <div class="text-caption text-grey">
            Der Hauptname greift nur zusammen mit der Mannschaftsart – deshalb ist
            „VTB Chemnitz 2" bei den Herren etwas anderes als bei den E-Junioren.
            Weitere Namen gelten dagegen unabhängig von der Art; sie sind für
            Spielgemeinschaften gedacht.
          </div>
          <div v-if="zuordnenFehler" class="text-negative text-caption">{{ zuordnenFehler }}</div>
        </q-card-section>

        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup :disable="zuordnenBusy" />
          <q-btn unelevated color="primary" label="Zuordnen" :disable="!zuMannschaft"
            :loading="zuordnenBusy" @click="zuordnungSpeichern" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Spielstätte aus dem Vorschlag anlegen. Alles außer „eigenes Gelände" steht
         im Export – das kann er nicht wissen, hängt aber die Platzbelegung daran. -->
    <q-dialog v-model="stOffen">
      <q-card style="min-width: 340px; max-width: 90vw">
        <q-card-section>
          <div class="text-subtitle1">Spielstätte anlegen</div>
          <div class="text-caption text-grey">
            DFBnet-Nr. {{ stForm.dfbnet_nr }} · {{ stAnzahl }}× im Plan
          </div>
        </q-card-section>

        <q-card-section class="q-gutter-sm">
          <q-input v-model="stForm.name" label="Name *" outlined dense />
          <q-input v-model="stForm.strasse" label="Straße/Hausnr." outlined dense />
          <div class="row q-col-gutter-sm">
            <div class="col-4"><q-input v-model="stForm.plz" label="PLZ" outlined dense /></div>
            <div class="col-8"><q-input v-model="stForm.ort" label="Ort" outlined dense /></div>
          </div>
          <q-input v-model.number="stForm.parallel_moeglich" type="number" min="1" outlined dense
            label="Parallel mögliche Spiele"
            hint="Aus dem Export übernommen – wie viele Partien gleichzeitig laufen können." />
          <q-input v-model="stForm.untergrund" outlined dense label="Untergrund"
            hint="Steht als Platztyp im Export; wird am Termin angezeigt." />
          <q-toggle v-model="stForm.ist_eigen" label="Eigenes Vereinsgelände" />
          <div class="text-caption text-grey">
            Nur auf eigenem Gelände zählt ein fremdes Spiel als Platzbelegung; sonst
            gilt die Zeile als „betrifft uns nicht". Für Auswärtsplätze also aus lassen.
          </div>
          <div v-if="stFehler" class="text-negative text-caption">{{ stFehler }}</div>
        </q-card-section>

        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup :disable="stBusy" />
          <q-btn unelevated color="primary" label="Anlegen" :disable="!stForm.name?.trim()"
            :loading="stBusy" @click="spielstaetteSpeichern" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { useAuthStore } from 'src/stores/auth'
import { usePageRefresh } from 'src/composables/useRefresh'
import { datumLabel, uhrzeit } from 'src/composables/useTermine'

defineOptions({ name: 'SpielplanImportPage' })

const $q = useQuasar()
const auth = useAuthStore()

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

// Was mit einem abweichenden Feld geschieht (Ergebnis des Drei-Wege-Abgleichs).
const WIRKUNG = {
  uebernehmen: 'wird übernommen',
  bleibt: 'bleibt so (Team weicht bewusst ab)',
  entscheidung: 'Betreuer entscheidet',
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
    // Der frische Bericht kennt Zuordnungen und Spielstätten bereits.
    zugeordnet.value = {}
    angelegt.value = {}
  } catch (e) {
    fehler.value = e.response?.data?.detail || 'Import fehlgeschlagen'
  } finally {
    busy.value = false
    commitLaeuft.value = false
  }
}

// ── Zuordnung eines DFBnet-Teamnamens zu einer eigenen Mannschaft ──────────
// Schreibt über die normale Mannschafts-API (dfbnet_name/-mannschaftsart bzw.
// Alias); die Vorschau selbst bleibt zustandslos und wird danach neu gelesen.
const darfZuordnen = computed(() => auth.hasPermission('mannschaften.write'))
const mannschaften = ref([])
const zuordnenOffen = ref(false)
const zuordnenBusy = ref(false)
const zuordnenFehler = ref('')
const zuTeam = ref(null)          // Eintrag aus bericht.unbekannte_teams
const zuMannschaft = ref(null)    // gewählte Option (mit .team)
const zuModus = ref('haupt')
const mannschaftenLaden = ref(false)
const mannschaftSuche = ref('')   // Eingabe im Auswahlfeld (q-select @filter)
// Merker je Teamname, solange der Bericht steht – die Vorschau kennt die frische
// Zuordnung erst nach dem nächsten Lauf.
const zugeordnet = ref({})
const zugeordneteAnzahl = computed(() => Object.keys(zugeordnet.value).length)

// ── Spielstätte aus dem Vorschlag anlegen ─────────────────────────────────
const darfSpielstaetten = computed(
  () => auth.hasPermission('spielstaetten.verwalten') ||
        auth.hasPermission('system.config'))
const stOffen = ref(false)
const stBusy = ref(false)
const stFehler = ref('')
const stAnzahl = ref(0)
const stForm = ref({ name: '', dfbnet_nr: '', strasse: '', plz: '', ort: '',
                     untergrund: '', parallel_moeglich: 1, ist_eigen: false })
const angelegt = ref({})          // dfbnet_nr -> Name, solange der Bericht steht

// Anzeige-Namen der Stammdatenfelder, die der Export mitbringt (der Name gehört
// bewusst nicht dazu – den überschreibt der Lauf nie).
const STAETTE_FELDER = {
  strasse: 'Straße', plz: 'PLZ', ort: 'Ort', untergrund: 'Untergrund',
  parallel_moeglich: 'Parallel mögliche Spiele',
}

const offeneAenderungen = computed(
  () => zugeordneteAnzahl.value + Object.keys(angelegt.value).length)

function oeffneSpielstaette(s) {
  stForm.value = {
    name: s.name || '', dfbnet_nr: s.dfbnet_nr, strasse: s.strasse || '',
    plz: s.plz || '', ort: s.ort || '',
    untergrund: s.untergrund || '',
    parallel_moeglich: s.parallel_moeglich || 1, ist_eigen: false,
  }
  stAnzahl.value = s.anzahl
  stFehler.value = ''
  stOffen.value = true
}

async function spielstaetteSpeichern() {
  stBusy.value = true
  stFehler.value = ''
  try {
    const { data } = await api.post('/api/spielstaetten/', {
      name: stForm.value.name.trim(),
      dfbnet_nr: stForm.value.dfbnet_nr,
      strasse: stForm.value.strasse || null,
      plz: stForm.value.plz || null,
      ort: stForm.value.ort || null,
      ist_eigen: stForm.value.ist_eigen,
      untergrund: stForm.value.untergrund || null,
      parallel_moeglich: Number(stForm.value.parallel_moeglich) || 1,
    })
    angelegt.value = { ...angelegt.value, [stForm.value.dfbnet_nr]: data.name }
    stOffen.value = false
    $q.notify({ type: 'positive', message: `Spielstätte „${data.name}" angelegt` })
  } catch (e) {
    stFehler.value = e.response?.data?.detail || 'Anlegen fehlgeschlagen'
  } finally {
    stBusy.value = false
  }
}

function teamKey(t) {
  return `${t.name}|${t.mannschaftsart}`
}

// Abteilungsfilter: Spielpläne betreffen praktisch immer nur eine Abteilung
// (Fußball). Bewusst nicht auf den Namen „Fußball" verdrahtet – Abteilungen sind
// Stammdaten und dürfen umbenannt werden. Die Wahl wird gemerkt, der Vorschlag
// ergibt sich aus den bestehenden DFBnet-Zuordnungen.
const ABTEILUNG_KEY = 'vtb_spielplan_abteilung'
const abteilungFilter = ref(null)   // null = alle Abteilungen

const abteilungOptionen = computed(() => {
  const bekannt = new Map()
  for (const m of mannschaften.value) {
    if (m.abteilung_id != null && !bekannt.has(m.abteilung_id)) {
      bekannt.set(m.abteilung_id, {
        value: m.abteilung_id, label: m.abteilung_name || `Abteilung ${m.abteilung_id}`,
      })
    }
  }
  return [
    { value: null, label: 'Alle Abteilungen' },
    ...[...bekannt.values()].sort((a, b) => a.label.localeCompare(b.label, 'de')),
  ]
})

const alleOptionen = computed(() => mannschaften.value
  .filter((m) => abteilungFilter.value == null || m.abteilung_id === abteilungFilter.value)
  .map((m) => ({
    label: m.name,
    caption: [m.abteilung_name, m.dfbnet_name ? `DFBnet: ${m.dfbnet_name}` : 'ohne DFBnet-Zuordnung']
      .filter(Boolean).join(' · '),
    team: m,
  })))

// Vorschlag: die Abteilung, in der schon DFBnet-Zuordnungen liegen – beim ersten
// Import gibt es die noch nicht, dann bleiben alle Mannschaften wählbar.
function vorgabeAbteilung() {
  const gemerkt = Number(localStorage.getItem(ABTEILUNG_KEY))
  if (gemerkt && mannschaften.value.some((m) => m.abteilung_id === gemerkt)) return gemerkt
  const zaehler = new Map()
  for (const m of mannschaften.value) {
    if (m.dfbnet_name) zaehler.set(m.abteilung_id, (zaehler.get(m.abteilung_id) ?? 0) + 1)
  }
  const beste = [...zaehler.entries()].sort((a, b) => b[1] - a[1])[0]
  return beste ? beste[0] : null
}

watch(abteilungFilter, (id) => {
  if (id == null) localStorage.removeItem(ABTEILUNG_KEY)
  else localStorage.setItem(ABTEILUNG_KEY, String(id))
})

const modusOptionen = computed(() => {
  const m = zuMannschaft.value?.team
  return [
    { value: 'haupt',
      label: m?.dfbnet_name && m.dfbnet_name !== zuTeam.value?.name
        ? `Hauptnamen ersetzen (bisher „${m.dfbnet_name}")`
        : 'Als Hauptnamen setzen (mit Mannschaftsart)' },
    { value: 'alias', label: 'Als weiteren Namen ergänzen (Spielgemeinschaft)' },
  ]
})

async function ladeMannschaften() {
  mannschaftenLaden.value = true
  try {
    const { data } = await api.get('/api/mannschaften')
    mannschaften.value = data
    if (abteilungFilter.value == null) abteilungFilter.value = vorgabeAbteilung()
    return true
  } catch {
    mannschaften.value = []   // ohne Leserecht bleibt der Dialog leer
    return false
  } finally {
    mannschaftenLaden.value = false
  }
}

// Bewusst abgeleitet statt als Schnappschuss: sonst zeigte die Auswahl weiter den
// Stand von vorhin, obwohl gerade frisch nachgeladen wurde.
const mannschaftOptionen = computed(() => alleOptionen.value.filter(
  (o) => !mannschaftSuche.value || o.label.toLowerCase().includes(mannschaftSuche.value)
    || o.caption.toLowerCase().includes(mannschaftSuche.value)))

function abteilungGewechselt() {
  zuMannschaft.value = null            // die bisherige Wahl steht evtl. gar nicht mehr zur Auswahl
  mannschaftSuche.value = ''
}

function filterMannschaften(val, update) {
  update(() => { mannschaftSuche.value = (val || '').toLowerCase() })
}

// Wer schon einen Hauptnamen hat, bekommt den zweiten Namen per Default als
// Alias – sonst überschriebe die Zuordnung stillschweigend die bestehende.
watch(zuMannschaft, (opt) => {
  zuModus.value = opt?.team?.dfbnet_name ? 'alias' : 'haupt'
})

async function oeffneZuordnung(t) {
  zuTeam.value = t
  zuMannschaft.value = null
  zuModus.value = 'haupt'
  zuordnenFehler.value = ''
  mannschaftSuche.value = ''
  zuordnenOffen.value = true
  // Immer frisch lesen: Mannschaften entstehen typischerweise parallel in einem
  // zweiten Fenster („anlegen und zuordnen"), die beim Seitenaufruf geladene
  // Liste kennt sie sonst nie.
  if (!await ladeMannschaften()) {
    zuordnenFehler.value = 'Mannschaften konnten nicht geladen werden'
  }
}

async function zuordnungSpeichern() {
  const m = zuMannschaft.value?.team
  if (!m) return
  zuordnenBusy.value = true
  zuordnenFehler.value = ''
  const alsHaupt = zuModus.value === 'haupt'
  const aliasse = [...(m.dfbnet_aliasse ?? [])]
  if (!alsHaupt && !aliasse.some((a) => a.toLowerCase() === zuTeam.value.name.toLowerCase())) {
    aliasse.push(zuTeam.value.name)
  }
  try {
    await api.put(`/api/mannschaften/${m.id}`, {
      abteilung_id: m.abteilung_id,
      name: m.name,
      saison: m.saison || null,
      beschreibung: m.beschreibung || null,
      dfbnet_name: alsHaupt ? zuTeam.value.name : (m.dfbnet_name || null),
      dfbnet_mannschaftsart: alsHaupt
        ? (zuTeam.value.mannschaftsart || null)
        : (m.dfbnet_mannschaftsart || null),
      dfbnet_aliasse: aliasse,
      expected_version: m.version,
    })
    zugeordnet.value = { ...zugeordnet.value, [teamKey(zuTeam.value)]: m.name }
    await ladeMannschaften()   // frische Version, sonst scheitert die zweite Zuordnung
    zuordnenOffen.value = false
    $q.notify({ type: 'positive', message: `„${zuTeam.value.name}" → ${m.name}` })
  } catch (e) {
    zuordnenFehler.value = e.response?.data?.detail || 'Zuordnung fehlgeschlagen'
  } finally {
    zuordnenBusy.value = false
  }
}

onMounted(() => {
  if (darfZuordnen.value) ladeMannschaften()
})

// Refresh-Button/Rückkehr zum Fenster zieht die Stammdaten nach – die Vorschau
// selbst hängt an der hochgeladenen Datei und bleibt bewusst stehen.
usePageRefresh(() => (darfZuordnen.value ? ladeMannschaften() : undefined))

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
