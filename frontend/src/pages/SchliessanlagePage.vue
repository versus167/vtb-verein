<template>
  <q-page class="q-pa-md">
    <div class="row items-center q-mb-md">
      <div class="text-h5">Schließanlage</div>
      <q-space />
      <span v-if="status.letzter_sync_at" class="text-caption text-grey-7 q-mr-sm">
        letzter Sync: {{ fmtDateTime(status.letzter_sync_at) }}
      </span>
      <q-btn v-if="status.darf_verwalten" color="primary" unelevated icon="sync"
        label="Jetzt synchronisieren" :loading="syncing" @click="doSync" />
    </div>

    <q-banner v-if="!status.konfiguriert" class="bg-amber-2 text-amber-10 q-mb-md" rounded dense>
      <template #avatar><q-icon name="warning" /></template>
      Kein TTLock-Konto konfiguriert (TTLOCK_* in der .env). Inventar/Logs können nicht
      synchronisiert werden.
    </q-banner>

    <q-tabs v-model="tab" dense align="left" class="text-grey-8 q-mb-sm" active-color="primary"
      indicator-color="primary">
      <q-tab name="schloesser" icon="meeting_room" label="Schlösser" />
      <q-tab name="chips" icon="badge" label="Chips" />
    </q-tabs>
    <q-separator class="q-mb-md" />

    <!-- ====================== Schlösser ====================== -->
    <div v-if="tab === 'schloesser'">
      <q-list bordered separator>
        <q-item v-for="s in schloesser" :key="s.id" clickable @click="openSchloss(s.id)">
          <q-item-section avatar>
            <q-icon name="meeting_room" :color="s.aktiv ? 'primary' : 'grey'" />
          </q-item-section>
          <q-item-section>
            <q-item-label>
              {{ s.name }}
              <q-chip v-if="s.standort" dense size="sm" outline>{{ s.standort }}</q-chip>
              <q-chip v-if="s.abteilung_name" dense size="sm" color="blue-grey-2">{{ s.abteilung_name }}</q-chip>
            </q-item-label>
            <q-item-label caption>
              <span v-if="s.letztes_event_at">
                letzter Vorgang: {{ fmtDateTime(s.letztes_event_at) }}
                ({{ recordTypeLabel(s.letztes_event_type) }})
              </span>
              <span v-else>noch keine Zutritte</span>
            </q-item-label>
          </q-item-section>
          <q-item-section side>
            <div class="row items-center q-gutter-sm">
              <q-icon :name="onlineIcon(s.gateway_online)" :color="onlineColor(s.gateway_online)" size="14px">
                <q-tooltip>{{ onlineLabel(s.gateway_online) }}</q-tooltip>
              </q-icon>
              <span v-if="s.akku_prozent != null" class="row items-center text-caption"
                :class="akkuLow(s.akku_prozent) ? 'text-negative' : 'text-grey-7'">
                <q-icon :name="akkuIcon(s.akku_prozent)" size="18px" /> {{ s.akku_prozent }}%
              </span>
              <q-btn v-if="status.darf_oeffnen" flat dense round size="sm" icon="lock_open"
                color="primary" :loading="opening === s.id" @click.stop="doOeffnen(s)">
                <q-tooltip>Fernöffnen</q-tooltip>
              </q-btn>
            </div>
          </q-item-section>
        </q-item>
      </q-list>
      <div v-if="schloesser.length === 0" class="text-grey text-center q-py-lg">
        Keine Schlösser. {{ status.darf_verwalten ? 'Synchronisiere, um das Inventar zu laden.' : '' }}
      </div>
    </div>

    <!-- ====================== Chips ====================== -->
    <div v-if="tab === 'chips'">
      <div class="row q-mb-sm">
        <q-space />
        <q-btn v-if="status.darf_verwalten" color="primary" unelevated icon="add"
          label="Neuer Chip" @click="openChipCreate" />
      </div>
      <q-list bordered separator>
        <q-item v-for="c in chips" :key="c.id" clickable @click="openChip(c.id)">
          <q-item-section avatar>
            <q-icon name="badge" :color="c.status === 'aktiv' ? 'primary' : 'grey'" />
          </q-item-section>
          <q-item-section>
            <q-item-label>
              {{ c.bezeichnung || ('Chip #' + c.id) }}
              <q-chip dense size="sm" outline>Nr. {{ c.kartennummer }}</q-chip>
              <q-chip v-if="c.status !== 'aktiv'" dense size="sm" color="orange-3">{{ c.status }}</q-chip>
            </q-item-label>
            <q-item-label caption>
              <span v-if="c.mitglied_id">ausgegeben an {{ mitgliedName(c) }}</span>
              <span v-else-if="c.aufbewahrungsort">liegt: {{ c.aufbewahrungsort }}</span>
              <span v-else>nicht zugeordnet</span>
            </q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
      <div v-if="chips.length === 0" class="text-grey text-center q-py-lg">Noch keine Chips erfasst.</div>
    </div>

    <!-- ====================== Schloss-Detail ====================== -->
    <q-dialog v-model="schlossDialog" :maximized="$q.screen.lt.sm">
      <q-card style="min-width:min(680px,96vw)">
        <q-card-section class="row items-center">
          <div class="text-h6">{{ schlossDetail.schloss?.name }}</div>
          <q-space />
          <q-btn v-if="status.darf_oeffnen" flat dense icon="lock_open" color="primary"
            :loading="opening === schlossDetail.schloss?.id" @click="doOeffnen(schlossDetail.schloss)">
            <q-tooltip>Fernöffnen</q-tooltip>
          </q-btn>
          <q-btn v-if="status.darf_oeffnen" flat dense icon="lock" color="grey-8"
            @click="doVerriegeln(schlossDetail.schloss)">
            <q-tooltip>Fernverriegeln</q-tooltip>
          </q-btn>
          <q-btn v-if="status.darf_verwalten" flat dense icon="edit" @click="openSchlossEdit" />
          <q-btn flat dense icon="close" v-close-popup />
        </q-card-section>
        <q-card-section class="q-pt-none">
          <q-list dense>
            <q-item><q-item-section>Standort</q-item-section>
              <q-item-section side>{{ schlossDetail.schloss?.standort || '–' }}</q-item-section></q-item>
            <q-item><q-item-section>Gateway / Online</q-item-section>
              <q-item-section side>{{ onlineLabel(schlossDetail.schloss?.gateway_online) }}</q-item-section></q-item>
            <q-item><q-item-section>Akku</q-item-section>
              <q-item-section side>{{ schlossDetail.schloss?.akku_prozent ?? '–' }}%</q-item-section></q-item>
          </q-list>

          <div class="text-subtitle2 q-mt-md">Zugeteilte Chips</div>
          <q-list dense bordered separator>
            <q-item v-for="b in schlossDetail.berechtigungen" :key="b.id">
              <q-item-section>
                <q-item-label>{{ b.chip_bezeichnung || ('Chip #' + b.chip_id) }}
                  <span class="text-grey-6">Nr. {{ b.kartennummer }}</span></q-item-label>
                <q-item-label caption>
                  {{ b.mitglied_vorname ? (b.mitglied_vorname + ' ' + (b.mitglied_nachname||'')) : '—' }}
                  <span v-if="b.gueltig_bis">· gültig bis {{ b.gueltig_bis }}</span>
                </q-item-label>
              </q-item-section>
              <q-item-section side><q-chip dense size="sm" :color="syncColor(b.sync_status)">{{ b.sync_status }}</q-chip></q-item-section>
            </q-item>
            <q-item v-if="!schlossDetail.berechtigungen?.length"><q-item-section class="text-grey">
              keine Chips zugeteilt</q-item-section></q-item>
          </q-list>

          <div class="text-subtitle2 q-mt-md">Zutrittslog</div>
          <div v-if="!schlossDetail.darf_protokoll" class="text-grey text-caption">
            Kein Recht für das Zutrittsprotokoll (schliessanlage.protokoll).
          </div>
          <q-list v-else dense bordered separator>
            <q-item v-for="l in schlossDetail.logs" :key="l.id">
              <q-item-section avatar>
                <q-icon :name="l.erfolg ? 'check_circle' : 'cancel'"
                  :color="l.erfolg ? 'positive' : 'negative'" size="18px" />
              </q-item-section>
              <q-item-section>
                <q-item-label>{{ l.methode }}</q-item-label>
                <q-item-label caption>{{ fmtDateTime(l.lock_date) }}
                  <span v-if="logWer(l)">· {{ logWer(l) }}</span></q-item-label>
              </q-item-section>
            </q-item>
            <q-item v-if="!schlossDetail.logs?.length"><q-item-section class="text-grey">
              keine Einträge im Zeitraum</q-item-section></q-item>
          </q-list>
        </q-card-section>
      </q-card>
    </q-dialog>

    <!-- ====================== Chip-Detail ====================== -->
    <q-dialog v-model="chipDialog" :maximized="$q.screen.lt.sm">
      <q-card style="min-width:min(640px,96vw)">
        <q-card-section class="row items-center">
          <div class="text-h6">{{ chipDetail.chip?.bezeichnung || ('Chip #' + chipDetail.chip?.id) }}</div>
          <q-space />
          <q-btn v-if="status.darf_verwalten" flat dense icon="edit" @click="openChipEdit" />
          <q-btn v-if="status.darf_verwalten" flat dense icon="delete" color="negative" @click="deleteChip" />
          <q-btn flat dense icon="close" v-close-popup />
        </q-card-section>
        <q-card-section class="q-pt-none">
          <div class="text-caption text-grey-7">
            Nr. {{ chipDetail.chip?.kartennummer }} ·
            {{ chipDetail.chip?.mitglied_id ? ('ausgegeben an ' + mitgliedName(chipDetail.chip))
               : ('liegt: ' + (chipDetail.chip?.aufbewahrungsort || '—')) }}
          </div>

          <div class="text-subtitle2 q-mt-md">Öffnet diese Schlösser</div>
          <q-list dense bordered separator>
            <q-item v-for="b in chipDetail.berechtigungen" :key="b.id">
              <q-item-section>{{ b.schloss_name }}</q-item-section>
              <q-item-section side><q-chip dense size="sm" :color="syncColor(b.sync_status)">{{ b.sync_status }}</q-chip></q-item-section>
            </q-item>
            <q-item v-if="!chipDetail.berechtigungen?.length"><q-item-section class="text-grey">
              keine Berechtigungen</q-item-section></q-item>
          </q-list>

          <div class="text-subtitle2 q-mt-md">Benutzt (Nutzungs-Log)</div>
          <div v-if="!chipDetail.darf_protokoll" class="text-grey text-caption">
            Kein Recht für das Zutrittsprotokoll (schliessanlage.protokoll).
          </div>
          <q-list v-else dense bordered separator>
            <q-item v-for="l in chipDetail.logs" :key="l.id">
              <q-item-section avatar>
                <q-icon :name="l.erfolg ? 'check_circle' : 'cancel'"
                  :color="l.erfolg ? 'positive' : 'negative'" size="18px" />
              </q-item-section>
              <q-item-section>
                <q-item-label>{{ l.schloss_name }}</q-item-label>
                <q-item-label caption>{{ fmtDateTime(l.lock_date) }} · {{ l.methode }}</q-item-label>
              </q-item-section>
            </q-item>
            <q-item v-if="!chipDetail.logs?.length"><q-item-section class="text-grey">
              noch nicht benutzt</q-item-section></q-item>
          </q-list>
        </q-card-section>
      </q-card>
    </q-dialog>

    <!-- ====================== Chip anlegen/bearbeiten ====================== -->
    <q-dialog v-model="chipFormDialog" persistent :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card :style="$q.screen.lt.sm ? 'width:100%;border-radius:16px 16px 0 0' : 'min-width:440px'">
        <q-card-section class="text-h6">{{ chipForm.id ? 'Chip bearbeiten' : 'Neuer Chip' }}</q-card-section>
        <q-card-section class="q-gutter-sm q-pt-none">
          <q-input v-model="chipForm.kartennummer" label="Kartennummer *" outlined dense
            :readonly="!!chipForm.id" :hint="chipForm.id ? 'Kartennummer ist fix' : ''" />
          <q-input v-model="chipForm.bezeichnung" label="Bezeichnung (z. B. Chip blau 14)" outlined dense />
          <q-input v-model.number="chipForm.mitglied_id" type="number" label="Mitglieds-ID (optional)"
            outlined dense hint="Wem ausgegeben – leer = Pool-Chip mit Standort" />
          <q-input v-model="chipForm.aufbewahrungsort" label="Standardstandort (wenn nicht ausgegeben)"
            outlined dense />
          <q-select v-model="chipForm.status" :options="['aktiv','gesperrt','verloren']" label="Status"
            outlined dense />
          <div v-if="chipError" class="text-negative text-caption">{{ chipError }}</div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn unelevated color="primary" :label="chipForm.id ? 'Speichern' : 'Anlegen'"
            :loading="saving" @click="saveChip" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- ====================== Schloss-Stammdaten bearbeiten ====================== -->
    <q-dialog v-model="schlossFormDialog" persistent :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card :style="$q.screen.lt.sm ? 'width:100%;border-radius:16px 16px 0 0' : 'min-width:440px'">
        <q-card-section class="text-h6">Schloss bearbeiten</q-card-section>
        <q-card-section class="q-gutter-sm q-pt-none">
          <q-input v-model="schlossForm.name" label="Name *" outlined dense />
          <q-input v-model="schlossForm.standort" label="Standort" outlined dense />
          <q-select v-model="schlossForm.abteilung_id" :options="abteilungen" option-value="id"
            option-label="name" emit-value map-options clearable label="Abteilung (leer = vereinsweit)"
            outlined dense />
          <q-input v-model="schlossForm.notiz" label="Notiz" outlined dense type="textarea" autogrow />
          <q-toggle v-model="schlossForm.aktiv" label="aktiv" />
          <div v-if="schlossError" class="text-negative text-caption">{{ schlossError }}</div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn unelevated color="primary" label="Speichern" :loading="saving" @click="saveSchloss" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useQuasar } from 'quasar'
import { usePageRefresh } from 'src/composables/useRefresh'
import { api } from 'src/boot/axios'

defineOptions({ name: 'SchliessanlagePage' })

const $q = useQuasar()

// recordType → Label (gespiegelt aus app/models/schliessanlage.py, Referenzdaten).
const RECORD_TYPES = {
  1: 'App', 2: 'Parklücke berührt', 3: 'Gateway (remote)', 4: 'Passcode',
  5: 'Parksperre hoch', 6: 'Parksperre runter', 7: 'IC-Karte', 8: 'Fingerprint',
  9: 'Armband', 10: 'mech. Schlüssel', 11: 'Bluetooth-Verriegeln', 12: 'Gateway (remote)',
  29: 'Unerwartet entriegelt', 30: 'Türmagnet zu', 31: 'Türmagnet auf', 32: 'Von innen geöffnet',
  33: 'Verriegelt (Fingerprint)', 34: 'Verriegelt (Passcode)', 35: 'Verriegelt (IC-Karte)',
  36: 'Verriegelt (mech. Schlüssel)', 37: 'Fernbedienung', 44: 'Sabotage-Alarm', 45: 'Auto-Lock',
  46: 'Entriegeln (Unlock-Key)', 47: 'Verriegeln (Lock-Key)', 48: 'Mehrf. Falsch-Passcode',
}
const recordTypeLabel = (t) => (t == null ? '–' : (RECORD_TYPES[t] || ('?' + t)))

const tab = ref('schloesser')
const status = ref({ konfiguriert: false, darf_verwalten: false, darf_protokoll: false, letzter_sync_at: null })
const schloesser = ref([])
const chips = ref([])
const abteilungen = ref([])
const syncing = ref(false)
const saving = ref(false)
const opening = ref(null)

function fmtDateTime(iso) {
  if (!iso) return '–'
  const d = new Date(iso)
  return isNaN(d) ? iso : d.toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'short' })
}
const onlineIcon = (o) => (o === true ? 'cloud_done' : o === false ? 'cloud_off' : 'cloud_queue')
const onlineColor = (o) => (o === true ? 'positive' : o === false ? 'negative' : 'grey')
const onlineLabel = (o) => (o === true ? 'Gateway online' : o === false ? 'Gateway offline' : 'unbekannt')
const akkuIcon = (p) => (p > 80 ? 'battery_full' : p > 40 ? 'battery_5_bar' : p > 20 ? 'battery_3_bar' : 'battery_alert')
const akkuLow = (p) => p != null && p <= 20
const syncColor = (s) => ({ aktiv: 'green-3', pending: 'grey-3', fehler: 'red-3', gesperrt: 'orange-3' }[s] || 'grey-3')
const mitgliedName = (x) => `${x.mitglied_vorname || ''} ${x.mitglied_nachname || ''}`.trim() || ('Mitglied #' + x.mitglied_id)
const logWer = (l) => (l.mitglied_vorname ? `${l.mitglied_vorname} ${l.mitglied_nachname || ''}`.trim()
  : l.chip_bezeichnung || l.ttlock_username || '')

async function loadStatus() {
  const { data } = await api.get('/api/schliessanlage/status')
  status.value = data
}
async function loadSchloesser() {
  const { data } = await api.get('/api/schliessanlage/schloesser')
  schloesser.value = data
}
async function loadChips() {
  const { data } = await api.get('/api/schliessanlage/chips')
  chips.value = data
}
async function loadAbteilungen() {
  try { const { data } = await api.get('/api/abteilungen/'); abteilungen.value = data }
  catch { abteilungen.value = [] }
}
async function reloadAll() {
  await Promise.all([loadStatus(), loadSchloesser(), loadChips()])
}
usePageRefresh(reloadAll)
onMounted(async () => {
  try { await Promise.all([reloadAll(), loadAbteilungen()]) }
  catch { $q.notify({ type: 'negative', message: 'Fehler beim Laden der Schließanlage' }) }
})

async function doSync() {
  syncing.value = true
  try {
    const { data } = await api.post('/api/schliessanlage/sync')
    $q.notify({ type: 'positive', message: `Sync ok: ${data.schloesser ?? 0} Schlösser, ${data.neu ?? 0} neue Logs` })
    await reloadAll()
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Sync fehlgeschlagen' })
  } finally { syncing.value = false }
}

function doOeffnen(s) {
  if (!s) return
  $q.dialog({
    title: 'Schloss fernöffnen',
    message: `„${s.name}" jetzt per Gateway öffnen?`,
    cancel: true, ok: { label: 'Öffnen', color: 'primary' },
  }).onOk(async () => {
    opening.value = s.id
    try {
      await api.post(`/api/schliessanlage/schloesser/${s.id}/oeffnen`)
      $q.notify({ type: 'positive', message: `„${s.name}" geöffnet` })
    } catch (e) {
      $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Öffnen fehlgeschlagen' })
    } finally { opening.value = null }
  })
}
function doVerriegeln(s) {
  if (!s) return
  $q.dialog({
    title: 'Schloss fernverriegeln',
    message: `„${s.name}" jetzt per Gateway verriegeln?`,
    cancel: true, ok: { label: 'Verriegeln', color: 'grey-8' },
  }).onOk(async () => {
    try {
      await api.post(`/api/schliessanlage/schloesser/${s.id}/verriegeln`)
      $q.notify({ type: 'positive', message: `„${s.name}" verriegelt` })
    } catch (e) {
      $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Verriegeln fehlgeschlagen' })
    }
  })
}

// --- Schloss-Detail/Edit ---
const schlossDialog = ref(false)
const schlossDetail = ref({})
async function openSchloss(id) {
  try {
    const { data } = await api.get(`/api/schliessanlage/schloesser/${id}`)
    schlossDetail.value = data; schlossDialog.value = true
  } catch (e) { $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Detail fehlgeschlagen' }) }
}
const schlossFormDialog = ref(false)
const schlossForm = ref({})
const schlossError = ref('')
function openSchlossEdit() {
  const s = schlossDetail.value.schloss
  schlossForm.value = { id: s.id, name: s.name, standort: s.standort, abteilung_id: s.abteilung_id,
    notiz: s.notiz, aktiv: s.aktiv, version: s.version }
  schlossError.value = ''; schlossFormDialog.value = true
}
async function saveSchloss() {
  if (!schlossForm.value.name) { schlossError.value = 'Name ist erforderlich.'; return }
  saving.value = true; schlossError.value = ''
  try {
    await api.put(`/api/schliessanlage/schloesser/${schlossForm.value.id}`, {
      name: schlossForm.value.name, standort: schlossForm.value.standort || null,
      abteilung_id: schlossForm.value.abteilung_id || null, notiz: schlossForm.value.notiz || null,
      aktiv: schlossForm.value.aktiv, version: schlossForm.value.version,
    })
    schlossFormDialog.value = false; schlossDialog.value = false
    await loadSchloesser()
  } catch (e) { schlossError.value = e.response?.data?.detail || 'Speichern fehlgeschlagen' }
  finally { saving.value = false }
}

// --- Chip-Detail/Edit ---
const chipDialog = ref(false)
const chipDetail = ref({})
async function openChip(id) {
  try {
    const { data } = await api.get(`/api/schliessanlage/chips/${id}`)
    chipDetail.value = data; chipDialog.value = true
  } catch (e) { $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Detail fehlgeschlagen' }) }
}
const chipFormDialog = ref(false)
const chipForm = ref({})
const chipError = ref('')
function openChipCreate() {
  chipForm.value = { id: null, kartennummer: '', bezeichnung: '', mitglied_id: null,
    aufbewahrungsort: '', status: 'aktiv' }
  chipError.value = ''; chipFormDialog.value = true
}
function openChipEdit() {
  const c = chipDetail.value.chip
  chipForm.value = { id: c.id, kartennummer: c.kartennummer, bezeichnung: c.bezeichnung,
    mitglied_id: c.mitglied_id, aufbewahrungsort: c.aufbewahrungsort, status: c.status, version: c.version }
  chipError.value = ''; chipFormDialog.value = true
}
async function saveChip() {
  if (!chipForm.value.kartennummer) { chipError.value = 'Kartennummer ist erforderlich.'; return }
  saving.value = true; chipError.value = ''
  const payload = {
    bezeichnung: chipForm.value.bezeichnung || null,
    mitglied_id: chipForm.value.mitglied_id || null,
    aufbewahrungsort: chipForm.value.aufbewahrungsort || null,
    status: chipForm.value.status || 'aktiv',
  }
  try {
    if (chipForm.value.id) {
      await api.put(`/api/schliessanlage/chips/${chipForm.value.id}`, { ...payload, version: chipForm.value.version })
    } else {
      await api.post('/api/schliessanlage/chips', { ...payload, kartennummer: chipForm.value.kartennummer })
    }
    chipFormDialog.value = false; chipDialog.value = false
    await loadChips()
  } catch (e) { chipError.value = e.response?.data?.detail || 'Speichern fehlgeschlagen' }
  finally { saving.value = false }
}
function deleteChip() {
  const c = chipDetail.value.chip
  $q.dialog({ title: 'Chip löschen', message: `Chip „${c.bezeichnung || c.kartennummer}" löschen?`, cancel: true })
    .onOk(async () => {
      try {
        await api.delete(`/api/schliessanlage/chips/${c.id}`)
        chipDialog.value = false; await loadChips()
      } catch (e) { $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Löschen fehlgeschlagen' }) }
    })
}
</script>
