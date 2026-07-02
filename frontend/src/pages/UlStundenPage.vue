<template>
  <q-page class="q-pa-md">
    <div class="row items-center q-mb-md">
      <div class="text-h5">Stundenerfassung</div>
      <q-space />
      <q-btn color="primary" unelevated icon="add" label="Neue Abrechnung" @click="openCreate" />
    </div>

    <!-- Fremderfassung (Geschäftsstelle): zwischen eigener und fremder ÜL-Sicht wechseln -->
    <q-select v-if="kannFremd" v-model="zielMitgliedId" :options="uebungsleiterOptions" option-value="id"
      :option-label="ulLabel" emit-value map-options clearable dense outlined
      use-input input-debounce="0" @filter="filterUebungsleiter"
      class="q-mb-md" label="Für Übungsleiter (leer = eigene)" @update:model-value="onZielChange">
      <template #prepend><q-icon name="badge" /></template>
      <template #option="{ itemProps, opt }">
        <q-item v-bind="itemProps">
          <q-item-section>{{ ulLabel(opt) }}</q-item-section>
          <q-item-section side>
            <q-chip dense size="sm"
              :color="opt.lizenz_aktuell_gueltig ? 'green-2' : 'blue-grey-2'"
              :text-color="opt.lizenz_aktuell_gueltig ? 'green-9' : 'blue-grey-8'">
              {{ opt.lizenz_aktuell_gueltig ? 'Lizenz' : 'keine Lizenz' }}
            </q-chip>
          </q-item-section>
        </q-item>
      </template>
      <template #no-option>
        <q-item><q-item-section class="text-grey">kein Treffer</q-item-section></q-item>
      </template>
    </q-select>
    <q-banner v-if="zielMitgliedId" dense class="bg-amber-1 text-amber-9 q-mb-md rounded-borders">
      <template #avatar><q-icon name="edit_note" /></template>
      Fremderfassung für <b>{{ zielLabel }}</b> – Anlegen und Bearbeiten erfolgen für diesen Übungsleiter.
    </q-banner>

    <q-list bordered separator>
      <q-item v-for="a in abrechnungen" :key="a.id" clickable @click="openDetail(a)">
        <q-item-section>
          <q-item-label>
            {{ a.abteilung_name }}
            <span class="text-grey-7">· {{ a.zeitraum_von }} – {{ a.zeitraum_bis }}</span>
          </q-item-label>
          <q-item-label caption>
            <q-chip dense size="sm" :color="statusChip(a.status).color" text-color="white">
              {{ statusChip(a.status).label }}
            </q-chip>
            <span class="q-mx-xs">{{ a.summen.summe_stunden }} Std.</span>
            <span v-if="a.summen.gesamtbetrag != null">· {{ fmtEuro(a.summen.gesamtbetrag) }}</span>
            <q-chip dense size="sm" outline :color="a.lizenz_klassifikation === 'mit_lizenz' ? 'green-8' : 'blue-grey'">
              {{ a.lizenz_klassifikation === 'mit_lizenz' ? 'mit Lizenz' : 'ohne Lizenz' }}
            </q-chip>
          </q-item-label>
        </q-item-section>
        <q-item-section side>
          <q-icon name="chevron_right" color="grey-6" />
        </q-item-section>
      </q-item>
    </q-list>
    <div v-if="abrechnungen.length === 0" class="text-grey text-center q-py-lg">
      Noch keine Abrechnungen. Lege deine erste an.
    </div>

    <!-- ════════════ Neue Abrechnung ════════════ -->
    <q-dialog v-model="createOpen" persistent :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card :style="$q.screen.lt.sm ? 'width:100%;border-radius:16px 16px 0 0' : 'min-width:440px'">
        <q-card-section class="text-h6">Neue Abrechnung</q-card-section>
        <q-card-section class="q-gutter-sm q-pt-none">
          <!-- Abteilung nur zur Auswahl, wenn der ÜL in mehreren tätig ist -->
          <q-select v-if="abteilungen.length > 1" v-model="cForm.abteilung_id" :options="abteilungen"
            option-value="id" option-label="name" emit-value map-options label="Abteilung *"
            outlined dense @update:model-value="onAbteilungChange" />
          <div v-else-if="abteilungen.length === 1" class="text-body2 q-py-xs">
            <q-icon name="account_tree" size="xs" /> {{ abteilungen[0].name }}
          </div>
          <div v-else-if="kontextGeladen" class="text-negative text-caption">
            Du bist in keiner Abteilung als Übungsleiter hinterlegt.
          </div>
          <div class="row q-gutter-sm">
            <q-input v-model="cForm.zeitraum_von" label="Von *" outlined dense type="date" class="col" />
            <q-input v-model="cForm.zeitraum_bis" label="Bis *" outlined dense type="date" class="col" />
          </div>
          <div v-if="cError" class="text-negative text-caption">{{ cError }}</div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn unelevated color="primary" label="Anlegen" :disable="!cForm.abteilung_id"
            :loading="cSaving" @click="saveCreate" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- ════════════ Detail / Bearbeiten ════════════ -->
    <q-dialog v-model="detailOpen" persistent :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card :style="$q.screen.lt.sm ? 'width:100%;border-radius:16px 16px 0 0' : 'min-width:560px;max-width:680px'">
        <q-card-section class="row items-center">
          <div class="text-h6">Abrechnung</div>
          <q-space />
          <q-chip v-if="detail" dense :color="statusChip(detail.status).color" text-color="white">
            {{ statusChip(detail.status).label }}
          </q-chip>
          <q-btn flat dense round icon="close" v-close-popup />
        </q-card-section>

        <q-card-section v-if="detail" class="q-pt-none">
          <div class="text-body2 q-mb-sm">
            <q-icon name="account_tree" size="xs" /> {{ detail.abteilung_name }}
            · {{ detail.zeitraum_von }} – {{ detail.zeitraum_bis }}
            · {{ detail.lizenz_klassifikation === 'mit_lizenz' ? 'mit Lizenz' : 'ohne Lizenz' }}
          </div>
          <div v-if="detail.status === 'abgelehnt' && detail.abgelehnt_grund"
            class="text-negative text-caption q-mb-sm">
            <q-icon name="error" size="xs" /> Abgelehnt: {{ detail.abgelehnt_grund }}
          </div>

          <!-- Erfasste Termine: Kalender (Standard) oder Liste -->
          <div class="row items-center q-mb-xs">
            <div class="text-caption text-grey-7">Erfasste Stunden</div>
            <q-space />
            <q-btn-toggle v-model="ansicht" dense no-caps unelevated size="sm"
              toggle-color="primary" color="grey-3" text-color="grey-8"
              :options="[{ label: 'Kalender', value: 'kalender', icon: 'calendar_month' },
                         { label: 'Liste', value: 'liste', icon: 'list' }]" />
          </div>

          <!-- Kalender: Tage mit Einträgen zeigen die Stunden als umkreiste Zahl -->
          <StundenKalender v-if="ansicht === 'kalender'" class="q-mb-sm"
            :termine="detail.stunden" :von="detail.zeitraum_von" :bis="detail.zeitraum_bis"
            :editable="isEntwurf" @delete="deleteTermin" />
          <div v-if="ansicht === 'kalender' && detail.stunden.length === 0"
            class="text-grey text-center q-pb-sm">Noch keine Termine erfasst.</div>

          <!-- Termine -->
          <q-markup-table v-if="ansicht === 'liste'" flat bordered dense class="q-mb-sm">
            <thead>
              <tr><th class="text-left">Datum</th><th class="text-left">Wo.</th>
                <th class="text-right">Stunden</th><th class="text-left">Angebot</th><th></th></tr>
            </thead>
            <tbody>
              <tr v-for="s in detail.stunden" :key="s.id">
                <td>{{ s.datum }}</td>
                <td>{{ wochentagKurz(s.wochentag) }}</td>
                <td class="text-right">{{ s.stunden }}</td>
                <td>{{ s.angebot || '' }}</td>
                <td class="text-right">
                  <q-btn v-if="isEntwurf" flat dense round size="sm" icon="delete" color="negative"
                    @click="deleteTermin(s)" />
                </td>
              </tr>
              <tr v-if="detail.stunden.length === 0">
                <td colspan="5" class="text-grey text-center">Noch keine Termine erfasst.</td>
              </tr>
            </tbody>
          </q-markup-table>

          <!-- Termine erfassen (nur im Entwurf) -->
          <div v-if="isEntwurf" class="q-mb-sm">
            <q-btn-toggle v-model="erfassModus" spread no-caps unelevated dense
              toggle-color="primary" color="grey-3" text-color="grey-8" class="q-mb-sm"
              :options="[{ label: 'Serie', value: 'serie', icon: 'repeat' },
                         { label: 'Einzeltage', value: 'einzeltage', icon: 'event' }]" />

            <!-- Serie: Wochentage antippen → Termine für den ganzen Zeitraum erzeugen -->
            <div v-if="erfassModus === 'serie'">
              <div v-if="detail.vorlage && detail.vorlage.length" class="q-mb-xs">
                <span class="text-caption text-grey-7 q-mr-xs">Aus letzter Abrechnung:</span>
                <q-chip v-for="(v, i) in detail.vorlage" :key="i" clickable dense
                  color="blue-1" text-color="primary" icon="content_copy"
                  @click="vorlageUebernehmen(v)">
                  {{ v.wochentage.map(wochentagKurz).join('+') }} · {{ v.stunden }} Std.<!--
                  -->{{ v.angebot ? ' · ' + v.angebot : '' }}
                </q-chip>
              </div>
              <div class="q-gutter-xs q-mb-sm">
                <q-btn v-for="w in 7" :key="w" :label="wochentagKurz(w)" dense no-caps
                  :outline="!sForm.wochentage.includes(w)"
                  :unelevated="sForm.wochentage.includes(w)"
                  :color="sForm.wochentage.includes(w) ? 'primary' : 'grey-6'"
                  style="min-width:42px" @click="toggleWochentag(w)" />
              </div>
              <div class="row q-gutter-sm items-end">
                <q-input v-model.number="sForm.stunden" label="Std." outlined dense type="number"
                  step="0.25" style="width:90px" />
                <q-input v-model="sForm.angebot" label="Angebot" outlined dense class="col" />
              </div>
              <div class="row items-center q-mt-sm">
                <div class="text-caption" :class="serieAnzahl ? 'text-grey-7' : 'text-grey-5'">
                  {{ serieVorschau }}
                </div>
                <q-space />
                <q-btn color="primary" unelevated icon="playlist_add" no-caps
                  label="Termine erzeugen" :disable="!serieAnzahl" :loading="sSaving"
                  @click="addSerie" />
              </div>
            </div>

            <!-- Einzeltage: Std./Angebot setzen, dann Tage im Kalender antippen (z. B. Spiele) -->
            <div v-else>
              <div class="row q-gutter-sm items-end q-mb-sm">
                <q-input v-model.number="tageForm.stunden" label="Std." outlined dense
                  type="number" step="0.25" style="width:90px" />
                <q-input v-model="tageForm.angebot" label="Angebot" outlined dense class="col"
                  placeholder="z. B. Spiel" />
              </div>
              <div class="row justify-center">
                <q-date v-model="tageForm.datums" multiple minimal mask="YYYY-MM-DD"
                  :first-day-of-week="1" :default-year-month="ymOf(detail.zeitraum_von)"
                  :navigation-min-year-month="ymOf(detail.zeitraum_von)"
                  :navigation-max-year-month="ymOf(detail.zeitraum_bis)"
                  :options="tagWaehlbar" :events="tagHatTermin" event-color="grey-5" />
              </div>
              <div class="row items-center q-mt-sm">
                <div class="text-caption" :class="tageAnzahl ? 'text-grey-7' : 'text-grey-5'">
                  {{ tageVorschau }}
                </div>
                <q-space />
                <q-btn color="primary" unelevated icon="playlist_add" no-caps
                  label="Termine erzeugen" :disable="!tageAnzahl || !tageForm.stunden"
                  :loading="tageSaving" @click="addTage" />
              </div>
            </div>
          </div>

          <div class="row items-center q-mt-sm">
            <div class="text-subtitle2">
              Summe: {{ detail.summen.summe_stunden }} Std.
              <span v-if="detail.summen.gesamtbetrag != null">
                · {{ fmtEuro(detail.summen.gesamtbetrag) }}
                <span class="text-grey-7">({{ fmtEuro(detail.summen.verguetung_pro_stunde) }}/h)</span>
              </span>
              <!-- Entwurf: Satz ist noch nicht eingefroren → voraussichtliche Vergütung -->
              <span v-else-if="detail.summen.vorschau_gesamtbetrag != null" class="text-grey-7">
                · voraussichtlich {{ fmtEuro(detail.summen.vorschau_gesamtbetrag) }}
                ({{ fmtEuro(detail.summen.vorschau_pro_stunde) }}/h)
              </span>
              <span v-else-if="detail.status !== 'entwurf'" class="text-orange">
                · kein Vergütungssatz hinterlegt
              </span>
            </div>
          </div>
          <div v-if="dError" class="text-negative text-caption q-mt-xs">{{ dError }}</div>
        </q-card-section>

        <q-card-actions align="right">
          <q-btn v-if="isEntwurf" flat color="negative" label="Löschen" @click="deleteAbrechnung" />
          <q-btn v-if="detail && detail.stunden.length > 0" flat color="primary"
            icon="picture_as_pdf" label="Beleg" @click="downloadBeleg" />
          <q-space />
          <q-btn v-if="detail && detail.status === 'abgelehnt'" flat color="primary"
            label="Erneut bearbeiten" :loading="dBusy" @click="zuruecksetzen" />
          <q-btn v-if="detail && detail.status === 'eingereicht'" flat color="primary"
            label="Zurückziehen" :loading="dBusy" @click="zuruecksetzen" />
          <q-btn v-if="isEntwurf" unelevated color="primary" label="Einreichen"
            :loading="dBusy" @click="einreichen" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { usePageRefresh } from 'src/composables/useRefresh'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { useAuthStore } from 'src/stores/auth'
import StundenKalender from 'src/components/StundenKalender.vue'

defineOptions({ name: 'UlStundenPage' })

const $q = useQuasar()
const auth = useAuthStore()

const abrechnungen = ref([])
const abteilungen = ref([])

// Fremderfassung (Geschäftsstelle): Abrechnungen für einen anderen ÜL anlegen/pflegen.
const kannFremd = computed(() => auth.hasPermission('ulstunden.erfassen_fremd'))
const uebungsleiter = ref([])          // Auswahl-Liste (nur mit Fremderfassungs-Recht)
const uebungsleiterOptions = ref([])   // gefilterte Sicht für die Textsuche
const zielMitgliedId = ref(null)       // null = eigene Abrechnungen
const ulLabel = (u) => (u ? `${u.nachname}, ${u.vorname}` : '')
const zielLabel = computed(() => {
  const ul = uebungsleiter.value.find(u => u.id === zielMitgliedId.value)
  return ul ? ulLabel(ul) : ''
})
function filterUebungsleiter(val, update) {
  const n = (val || '').toLowerCase()
  update(() => {
    uebungsleiterOptions.value = n
      ? uebungsleiter.value.filter(u => ulLabel(u).toLowerCase().includes(n))
      : uebungsleiter.value
  })
}

function statusChip(status) {
  return {
    entwurf: { label: 'Entwurf', color: 'blue-grey' },
    eingereicht: { label: 'Eingereicht', color: 'orange' },
    bestaetigt: { label: 'Bestätigt', color: 'green' },
    abgelehnt: { label: 'Abgelehnt', color: 'red' },
  }[status] || { label: status, color: 'grey' }
}

function fmtEuro(v) {
  if (v == null) return ''
  return Number(v).toLocaleString('de-DE', { style: 'currency', currency: 'EUR' })
}
function wochentagKurz(w) {
  return ['', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'][w] || ''
}
// Lokales ISO-Datum (kein toISOString → keine Zeitzonen-Verschiebung)
function isoOf(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
function isoWeekday(d) {
  return d.getDay() === 0 ? 7 : d.getDay()  // So=7 statt 0
}
function ymOf(iso) {                     // 'YYYY-MM-DD' → 'YYYY/MM' (q-date-Navigation)
  return iso ? iso.slice(0, 7).replace('-', '/') : ''
}
function normIso(dateStr) {              // q-date liefert teils 'YYYY/MM/DD'
  return (dateStr || '').replace(/\//g, '-').slice(0, 10)
}
function endOfPrevMonthIso() {           // letzter Tag des Vormonats (Default „bis")
  const n = new Date()
  return isoOf(new Date(n.getFullYear(), n.getMonth(), 0))
}
function firstOfPrevMonthIso() {         // erster Tag des Vormonats (Fallback „von")
  const n = new Date()
  return isoOf(new Date(n.getFullYear(), n.getMonth() - 1, 1))
}
function endOfMonthIso(iso) {            // letzter Tag des Monats von iso
  const d = new Date(iso + 'T00:00:00')
  return isoOf(new Date(d.getFullYear(), d.getMonth() + 1, 0))
}

async function loadAbrechnungen() {
  const params = zielMitgliedId.value ? { mitglied_id: zielMitgliedId.value } : {}
  const { data } = await api.get('/api/ul-stunden/meine', { params })
  abrechnungen.value = data
}
async function loadUebungsleiter() {
  if (!kannFremd.value) return
  try {
    const { data } = await api.get('/api/ul-stunden/uebungsleiter')
    uebungsleiter.value = data; uebungsleiterOptions.value = data
  } catch { uebungsleiter.value = []; uebungsleiterOptions.value = [] }
}
function onZielChange() {
  loadAbrechnungen().catch(() => $q.notify({ type: 'negative', message: 'Fehler beim Laden' }))
}
usePageRefresh(loadAbrechnungen)
onMounted(async () => {
  try { await Promise.all([loadAbrechnungen(), loadUebungsleiter()]) }
  catch { $q.notify({ type: 'negative', message: 'Fehler beim Laden' }) }
})

// ── Neue Abrechnung ────────────────────────────────────────
const createOpen = ref(false)
const cSaving = ref(false)
const cError = ref('')
const cForm = ref({})
const kontextGeladen = ref(false)

// von-Vorschlag (Tag nach letzter Abrechnung, sonst Monatsanfang) übernehmen;
// liegt er nach „bis", „bis" auf das Monatsende von „von" ziehen.
function applyVonVorschlag(abt) {
  const von = abt?.zeitraum_von_vorschlag || firstOfPrevMonthIso()
  cForm.value.zeitraum_von = von
  if (von > cForm.value.zeitraum_bis) cForm.value.zeitraum_bis = endOfMonthIso(von)
}
function onAbteilungChange(id) {
  const abt = abteilungen.value.find(a => a.id === id)
  if (abt) applyVonVorschlag(abt)
}
async function openCreate() {
  cError.value = ''
  kontextGeladen.value = false
  abteilungen.value = []
  cForm.value = {
    abteilung_id: null, zeitraum_von: firstOfPrevMonthIso(), zeitraum_bis: endOfPrevMonthIso(),
    mitglied_id: zielMitgliedId.value || null,   // bei Fremderfassung: Ziel-ÜL
  }
  createOpen.value = true
  try {
    const params = zielMitgliedId.value ? { mitglied_id: zielMitgliedId.value } : {}
    const { data } = await api.get('/api/ul-stunden/erfassung-kontext', { params })
    abteilungen.value = data.abteilungen || []
    if (abteilungen.value.length === 1) {
      cForm.value.abteilung_id = abteilungen.value[0].id
      applyVonVorschlag(abteilungen.value[0])
    }
  } catch (e) {
    cError.value = e.response?.data?.detail || 'Abteilungen konnten nicht geladen werden'
  } finally {
    kontextGeladen.value = true
  }
}
async function saveCreate() {
  if (!cForm.value.abteilung_id || !cForm.value.zeitraum_von || !cForm.value.zeitraum_bis) {
    cError.value = 'Abteilung und Zeitraum sind erforderlich.'; return
  }
  cSaving.value = true; cError.value = ''
  try {
    const { data } = await api.post('/api/ul-stunden', cForm.value)
    createOpen.value = false
    await loadAbrechnungen()
    openDetail(data)
  } catch (e) {
    cError.value = e.response?.data?.detail || 'Fehler beim Anlegen'
  } finally {
    cSaving.value = false
  }
}

// ── Detail / Termine ───────────────────────────────────────
const detailOpen = ref(false)
const detail = ref(null)
const dError = ref('')
const dBusy = ref(false)
const ansicht = ref('kalender')   // 'kalender' (Standard) | 'liste'

// Erfassungs-Modus: 'serie' (Wochenplan, z. B. Training) | 'einzeltage' (Kalender, z. B. Spiele)
const erfassModus = ref('serie')
const sForm = ref({ wochentage: [], stunden: null, angebot: '' })
const sSaving = ref(false)
const tageForm = ref({ datums: [], stunden: null, angebot: '' })
const tageSaving = ref(false)

const isEntwurf = computed(() => detail.value?.status === 'entwurf')

// Bereits erfasste Tage (ISO) – für Dedup-Vorschau in beiden Modi.
const vorhandeneTage = computed(
  () => new Set((detail.value?.stunden || []).map(s => s.datum.slice(0, 10))))

// Wie viele neue Termine würde die Serie erzeugen (bereits erfasste Tage ausgenommen)?
const serieAnzahl = computed(() => {
  if (!detail.value || !sForm.value.wochentage.length || !sForm.value.stunden) return 0
  const bis = new Date(detail.value.zeitraum_bis + 'T00:00:00')
  const d = new Date(detail.value.zeitraum_von + 'T00:00:00')
  let n = 0
  while (d <= bis) {
    if (sForm.value.wochentage.includes(isoWeekday(d)) && !vorhandeneTage.value.has(isoOf(d))) n++
    d.setDate(d.getDate() + 1)
  }
  return n
})
const serieVorschau = computed(() => {
  if (!sForm.value.wochentage.length) return 'Wochentage wählen'
  if (!sForm.value.stunden) return 'Stunden angeben'
  const n = serieAnzahl.value
  return n ? `→ ${n} Termin${n === 1 ? '' : 'e'} werden erzeugt` : 'Keine neuen Termine im Zeitraum'
})

// Einzeltage: gewählte, noch nicht erfasste Tage.
const tageAnzahl = computed(
  () => (tageForm.value.datums || []).filter(d => !vorhandeneTage.value.has(d)).length)
const tageVorschau = computed(() => {
  if (!tageForm.value.datums?.length) return 'Tage im Kalender wählen'
  if (!tageForm.value.stunden) return 'Stunden angeben'
  const n = tageAnzahl.value
  return n ? `→ ${n} Termin${n === 1 ? '' : 'e'} werden erzeugt` : 'Alle gewählten Tage schon erfasst'
})
function tagWaehlbar(dateStr) {           // nur Tage im Abrechnungszeitraum anklickbar
  const iso = normIso(dateStr)
  return iso >= detail.value.zeitraum_von && iso <= detail.value.zeitraum_bis
}
function tagHatTermin(dateStr) {          // markiert bereits erfasste Tage im Kalender
  return vorhandeneTage.value.has(normIso(dateStr))
}

function toggleWochentag(w) {
  const i = sForm.value.wochentage.indexOf(w)
  if (i >= 0) sForm.value.wochentage.splice(i, 1)
  else sForm.value.wochentage.push(w)
}
function vorlageUebernehmen(v) {
  erfassModus.value = 'serie'
  sForm.value = { wochentage: [...v.wochentage], stunden: v.stunden, angebot: v.angebot || '' }
}

async function openDetail(a) {
  dError.value = ''
  detailOpen.value = true
  await reloadDetail(a.id)
  erfassModus.value = 'serie'
  sForm.value = { wochentage: [], stunden: null, angebot: '' }
  tageForm.value = { datums: [], stunden: null, angebot: '' }
  // Frischer, leerer Entwurf mit Vorlage → Serien-Modus mit dem dominanten Muster
  // der letzten Abrechnung vorbelegen (1 Tap zum Erzeugen).
  const vorlage = detail.value?.vorlage || []
  if (isEntwurf.value && detail.value.stunden.length === 0 && vorlage.length) {
    vorlageUebernehmen(vorlage[0])
  }
}
async function reloadDetail(id) {
  const { data } = await api.get(`/api/ul-stunden/${id}`)
  detail.value = data
}
function setDetail(data) {
  detail.value = data
  const idx = abrechnungen.value.findIndex(a => a.id === data.id)
  if (idx >= 0) abrechnungen.value[idx] = data
}

async function addTage() {
  if (!tageForm.value.datums?.length || !tageForm.value.stunden) {
    dError.value = 'Tage und Stunden sind erforderlich.'; return
  }
  tageSaving.value = true; dError.value = ''
  try {
    const vorher = detail.value.stunden.length
    const { data } = await api.post(`/api/ul-stunden/${detail.value.id}/stunden/mehrfach`, {
      datums: tageForm.value.datums,
      stunden: Number(tageForm.value.stunden),
      angebot: tageForm.value.angebot || null,
    })
    setDetail(data)
    tageForm.value.datums = []
    const neu = data.stunden.length - vorher
    $q.notify({ type: 'positive', message: neu > 0 ? `${neu} Termine erzeugt` : 'Keine neuen Termine' })
  } catch (e) {
    dError.value = e.response?.data?.detail || 'Fehler'
  } finally {
    tageSaving.value = false
  }
}
async function addSerie() {
  if (!sForm.value.wochentage.length || !sForm.value.stunden) {
    dError.value = 'Wochentage und Stunden sind erforderlich.'; return
  }
  sSaving.value = true; dError.value = ''
  try {
    const { data } = await api.post(`/api/ul-stunden/${detail.value.id}/stunden/serie`, {
      wochentage: [...sForm.value.wochentage].sort((a, b) => a - b),
      stunden: Number(sForm.value.stunden),
      angebot: sForm.value.angebot || null,
    })
    const vorher = detail.value.stunden.length
    setDetail(data)
    const neu = data.stunden.length - vorher
    $q.notify({ type: 'positive', message: neu > 0 ? `${neu} Termine erzeugt` : 'Keine neuen Termine' })
  } catch (e) {
    dError.value = e.response?.data?.detail || 'Fehler'
  } finally {
    sSaving.value = false
  }
}
async function deleteTermin(s) {
  try {
    const { data } = await api.delete(`/api/ul-stunden/${detail.value.id}/stunden/${s.id}`)
    setDetail(data)
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' })
  }
}

async function einreichen() {
  dBusy.value = true; dError.value = ''
  try {
    const { data } = await api.post(`/api/ul-stunden/${detail.value.id}/einreichen`)
    setDetail(data)
    $q.notify({ type: 'positive', message: 'Eingereicht – zur Bestätigung durch den Abteilungsleiter' })
    detailOpen.value = false
    await loadAbrechnungen()
  } catch (e) {
    dError.value = e.response?.data?.detail || 'Einreichen fehlgeschlagen'
  } finally {
    dBusy.value = false
  }
}
async function zuruecksetzen() {
  dBusy.value = true
  try {
    const { data } = await api.post(`/api/ul-stunden/${detail.value.id}/zuruecksetzen`)
    setDetail(data)
    await loadAbrechnungen()
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' })
  } finally {
    dBusy.value = false
  }
}
async function downloadBeleg() {
  try {
    const res = await api.get(`/api/ul-stunden/${detail.value.id}/beleg.pdf`, { responseType: 'blob' })
    const url = URL.createObjectURL(res.data)
    const a = document.createElement('a')
    a.href = url
    a.download = `Stundennachweis_${detail.value.mitglied_nachname || 'UL'}_${detail.value.zeitraum_von}.pdf`
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Beleg konnte nicht erstellt werden' })
  }
}
function deleteAbrechnung() {
  $q.dialog({ title: 'Abrechnung löschen', message: 'Diese Abrechnung wirklich löschen?', cancel: true })
    .onOk(async () => {
      try {
        await api.delete(`/api/ul-stunden/${detail.value.id}`)
        detailOpen.value = false
        await loadAbrechnungen()
      } catch (e) {
        $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' })
      }
    })
}
</script>
