<template>
  <q-page class="q-pa-md">
    <div class="row items-center q-mb-md q-gutter-sm">
      <div class="text-h5">Passwörter</div>
      <q-space />
      <q-btn v-if="darfVerwalten" color="primary" unelevated icon="add" label="Neuer Tresor"
        @click="openTresorDialog()" />
    </div>

    <q-banner v-if="!konfiguriert" class="bg-orange-1 text-orange-9 q-mb-md" rounded dense>
      <template #avatar><q-icon name="warning" color="orange-9" /></template>
      Der Tresor ist serverseitig nicht konfiguriert (<code>VTB_VAULT_KEY</code> fehlt).
      Passwörter können derzeit weder angezeigt noch gespeichert werden.
    </q-banner>

    <div class="row q-col-gutter-md">
      <!-- Tresor-Liste -->
      <div class="col-12 col-md-4">
        <q-list bordered separator class="rounded-borders">
          <q-item v-for="t in tresore" :key="t.id" clickable
            :active="t.id === selectedId" active-class="bg-blue-1"
            @click="select(t.id)">
            <q-item-section avatar><q-icon name="folder" color="primary" /></q-item-section>
            <q-item-section>
              <q-item-label>{{ t.name }}</q-item-label>
              <q-item-label caption>
                {{ t.eintrag_anzahl }} {{ t.eintrag_anzahl === 1 ? 'Eintrag' : 'Einträge' }}
                <span v-if="!t.darf_schreiben" class="text-grey-6">· nur lesen</span>
              </q-item-label>
            </q-item-section>
            <q-item-section side v-if="darfVerwalten">
              <div class="row items-center no-wrap">
                <q-btn flat dense round size="sm" icon="group" color="grey-7"
                  @click.stop="openFreigaben(t)"><q-tooltip>Freigaben</q-tooltip></q-btn>
                <q-btn flat dense round size="sm" icon="history" color="grey-7"
                  @click.stop="openZugriffe(t)"><q-tooltip>Zugriffs-Log</q-tooltip></q-btn>
                <q-btn flat dense round size="sm" icon="edit" color="primary"
                  @click.stop="openTresorDialog(t)" />
                <q-btn flat dense round size="sm" icon="delete" color="negative"
                  @click.stop="deleteTresor(t)" />
              </div>
            </q-item-section>
          </q-item>
        </q-list>
        <div v-if="tresore.length === 0" class="text-grey text-center q-py-lg">
          Kein Tresor vorhanden.
          <span v-if="darfVerwalten">Lege den ersten an.</span>
        </div>
      </div>

      <!-- Einträge des gewählten Tresors -->
      <div class="col-12 col-md-8">
        <div v-if="selectedId">
          <div class="row items-center q-mb-sm">
            <div class="text-subtitle1 text-weight-medium">{{ selectedTresor?.name }}</div>
            <q-space />
            <q-btn v-if="selectedTresor?.darf_schreiben" color="primary" unelevated dense
              icon="add" label="Neuer Eintrag" :disable="!konfiguriert" @click="openEintragDialog()" />
          </div>

          <q-list bordered separator class="rounded-borders">
            <q-item v-for="e in eintraege" :key="e.id">
              <q-item-section>
                <q-item-label>{{ e.titel }}</q-item-label>
                <q-item-label caption>
                  <span v-if="e.benutzername">
                    <q-icon name="person" size="xs" /> {{ e.benutzername }}
                    <q-btn flat dense round size="xs" icon="content_copy"
                      @click="copy(e.benutzername, 'Benutzername kopiert')" />
                  </span>
                  <a v-if="e.url" :href="e.url" target="_blank" rel="noopener"
                    class="q-ml-sm text-primary">{{ e.url }}</a>
                </q-item-label>

                <!-- Enthülltes Passwort -->
                <div v-if="revealed[e.id]" class="q-mt-xs">
                  <q-chip dense square color="grey-2" text-color="grey-9" class="text-mono">
                    {{ revealed[e.id].passwort || '(leer)' }}
                  </q-chip>
                  <q-btn flat dense round size="sm" icon="content_copy" color="primary"
                    @click="copy(revealed[e.id].passwort, 'Passwort kopiert')" />
                  <q-btn flat dense round size="sm" icon="visibility_off" color="grey-7"
                    @click="hide(e.id)" />
                  <div v-if="revealed[e.id].notiz" class="text-caption text-grey-8 q-mt-xs">
                    <q-icon name="sticky_note_2" size="xs" /> {{ revealed[e.id].notiz }}
                  </div>
                </div>
              </q-item-section>

              <q-item-section side top>
                <div class="row items-center no-wrap">
                  <q-btn v-if="!revealed[e.id]" flat dense size="sm" no-caps icon="visibility"
                    color="primary" label="Anzeigen" :disable="!konfiguriert" @click="reveal(e)" />
                  <q-btn v-if="selectedTresor?.darf_schreiben" flat dense round size="sm"
                    icon="edit" color="grey-8" @click="openEintragDialog(e)" />
                  <q-btn v-if="selectedTresor?.darf_schreiben" flat dense round size="sm"
                    icon="delete" color="negative" @click="deleteEintrag(e)" />
                </div>
              </q-item-section>
            </q-item>
          </q-list>
          <div v-if="eintraege.length === 0" class="text-grey text-center q-py-lg">
            Noch keine Einträge in diesem Tresor.
          </div>
        </div>
        <div v-else class="text-grey text-center q-py-xl">
          Wähle links einen Tresor aus.
        </div>
      </div>
    </div>

    <!-- Tresor anlegen/bearbeiten -->
    <q-dialog v-model="tresorDialog" persistent :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card :style="$q.screen.lt.sm ? 'width:100%;border-radius:16px 16px 0 0' : 'min-width:420px'">
        <q-card-section class="text-h6">{{ tresorForm.id ? 'Tresor bearbeiten' : 'Neuer Tresor' }}</q-card-section>
        <q-card-section class="q-gutter-sm q-pt-none">
          <q-input v-model="tresorForm.name" label="Name *" outlined dense autofocus />
          <q-input v-model="tresorForm.beschreibung" label="Beschreibung" outlined dense type="textarea" autogrow />
          <div v-if="tresorError" class="text-negative text-caption">{{ tresorError }}</div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn unelevated color="primary" :label="tresorForm.id ? 'Speichern' : 'Anlegen'"
            :loading="saving" @click="saveTresor" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Eintrag anlegen/bearbeiten -->
    <q-dialog v-model="eintragDialog" persistent :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card :style="$q.screen.lt.sm ? 'width:100%;border-radius:16px 16px 0 0' : 'min-width:460px'">
        <q-card-section class="text-h6">{{ eintragForm.id ? 'Eintrag bearbeiten' : 'Neuer Eintrag' }}</q-card-section>
        <q-card-section class="q-gutter-sm q-pt-none">
          <q-input v-model="eintragForm.titel" label="Titel *" outlined dense autofocus />
          <q-input v-model="eintragForm.benutzername" label="Benutzername" outlined dense />
          <q-input v-model="eintragForm.url" label="URL" outlined dense />
          <q-input v-model="eintragForm.passwort" :label="eintragForm.id ? 'Neues Passwort' : 'Passwort'"
            outlined dense :type="showPw ? 'text' : 'password'"
            :disable="eintragForm.id && !eintragForm.passwort_aendern">
            <template #append>
              <q-icon :name="showPw ? 'visibility_off' : 'visibility'" class="cursor-pointer"
                @click="showPw = !showPw" />
            </template>
          </q-input>
          <q-toggle v-if="eintragForm.id" v-model="eintragForm.passwort_aendern"
            label="Passwort ändern" dense />
          <q-input v-model="eintragForm.notiz" label="Geheime Notiz (verschlüsselt)" outlined dense
            type="textarea" autogrow :disable="eintragForm.id && !eintragForm.passwort_aendern" />
          <div class="text-caption text-grey-6">
            Passwort &amp; Notiz werden verschlüsselt gespeichert. Titel/Benutzer/URL bleiben Klartext.
          </div>
          <div v-if="eintragError" class="text-negative text-caption">{{ eintragError }}</div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn unelevated color="primary" :label="eintragForm.id ? 'Speichern' : 'Anlegen'"
            :loading="saving" @click="saveEintrag" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Freigaben -->
    <q-dialog v-model="freigabenDialog" :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card :style="$q.screen.lt.sm ? 'width:100%;border-radius:16px 16px 0 0' : 'min-width:520px'">
        <q-card-section class="row items-center">
          <div class="text-h6">Freigaben · {{ freigabenTresor?.name }}</div>
          <q-space />
          <q-btn flat dense round icon="close" v-close-popup />
        </q-card-section>
        <q-card-section class="q-pt-none">
          <q-list bordered separator class="rounded-borders q-mb-md">
            <q-item v-for="f in freigaben" :key="f.id">
              <q-item-section avatar><q-icon :name="principalIcon(f.principal_typ)" color="grey-7" /></q-item-section>
              <q-item-section>
                <q-item-label>{{ f.principal_name || ('#' + f.principal_id) }}</q-item-label>
                <q-item-label caption>{{ principalLabel(f.principal_typ) }}</q-item-label>
              </q-item-section>
              <q-item-section side>
                <div class="row items-center no-wrap">
                  <q-chip dense :color="f.zugriff === 'write' ? 'green-7' : 'blue-grey'" text-color="white">
                    {{ f.zugriff === 'write' ? 'Schreiben' : 'Lesen' }}
                  </q-chip>
                  <q-btn flat dense round size="sm" icon="delete" color="negative" @click="revoke(f)" />
                </div>
              </q-item-section>
            </q-item>
          </q-list>
          <div v-if="freigaben.length === 0" class="text-grey text-center q-py-sm">
            Noch keine Freigaben – nur Verwalter/Admins sehen diesen Tresor.
          </div>

          <div class="text-subtitle2 q-mt-sm q-mb-xs">Freigabe hinzufügen</div>
          <div class="row q-col-gutter-sm items-end">
            <div class="col-12 col-sm-4">
              <q-select v-model="nf.typ" :options="typOptionen" emit-value map-options
                label="Typ" outlined dense @update:model-value="nf.pid = null" />
            </div>
            <div class="col-12 col-sm-5">
              <q-select v-model="nf.pid" :options="principalOptionen" option-value="id" option-label="name"
                emit-value map-options label="Empfänger" outlined dense use-input
                @filter="filterPrincipals" :loading="principalsLoading" />
            </div>
            <div class="col-8 col-sm-2">
              <q-select v-model="nf.zugriff" :options="zugriffOptionen" emit-value map-options
                label="Recht" outlined dense />
            </div>
            <div class="col-4 col-sm-1">
              <q-btn color="primary" unelevated icon="add" :loading="saving"
                :disable="!nf.pid" @click="addFreigabe" />
            </div>
          </div>
          <div v-if="freigabeError" class="text-negative text-caption q-mt-xs">{{ freigabeError }}</div>
        </q-card-section>
      </q-card>
    </q-dialog>

    <!-- Zugriffs-Log -->
    <q-dialog v-model="zugriffeDialog" :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card :style="$q.screen.lt.sm ? 'width:100%;border-radius:16px 16px 0 0' : 'min-width:520px;max-width:640px'">
        <q-card-section class="row items-center">
          <div class="text-h6">Zugriffs-Log · {{ zugriffeTresor?.name }}</div>
          <q-space />
          <q-btn flat dense round icon="close" v-close-popup />
        </q-card-section>
        <q-card-section class="q-pt-none">
          <q-list bordered separator class="rounded-borders">
            <q-item v-for="z in zugriffe" :key="z.id">
              <q-item-section avatar><q-icon name="visibility" color="grey-7" /></q-item-section>
              <q-item-section>
                <q-item-label>{{ z.eintrag_titel || '(gelöscht)' }}</q-item-label>
                <q-item-label caption>
                  {{ z.username || 'unbekannt' }} · {{ fmtTs(z.created_at) }}
                  <span v-if="z.ip" class="text-grey-6">· {{ z.ip }}</span>
                </q-item-label>
              </q-item-section>
            </q-item>
          </q-list>
          <div v-if="zugriffe.length === 0" class="text-grey text-center q-py-sm">
            Noch keine Zugriffe protokolliert.
          </div>
        </q-card-section>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useQuasar, copyToClipboard } from 'quasar'
import { usePageRefresh } from 'src/composables/useRefresh'
import { api } from 'src/boot/axios'

defineOptions({ name: 'TresorPage' })

const $q = useQuasar()

const konfiguriert = ref(true)
const darfVerwalten = ref(false)
const tresore = ref([])
const selectedId = ref(null)
const eintraege = ref([])
const revealed = ref({})           // eintrag_id -> { passwort, notiz }
const revealTimers = {}
const saving = ref(false)
const showPw = ref(false)

const selectedTresor = computed(() => tresore.value.find(t => t.id === selectedId.value) || null)

// ── Laden ──
async function loadStatus() {
  try {
    const { data } = await api.get('/api/tresor/status')
    konfiguriert.value = data.konfiguriert
    darfVerwalten.value = data.darf_verwalten
  } catch { /* ignorieren */ }
}
async function loadTresore() {
  const { data } = await api.get('/api/tresor')
  tresore.value = data
  if (selectedId.value && !data.some(t => t.id === selectedId.value)) {
    selectedId.value = null
    eintraege.value = []
  }
}
async function loadEintraege(id) {
  const { data } = await api.get(`/api/tresor/${id}/eintraege`)
  eintraege.value = data.eintraege
}
async function select(id) {
  selectedId.value = id
  clearReveals()
  try { await loadEintraege(id) }
  catch { $q.notify({ type: 'negative', message: 'Einträge konnten nicht geladen werden' }) }
}
async function refreshAll() {
  await loadStatus()
  await loadTresore()
  if (selectedId.value) await loadEintraege(selectedId.value)
}
usePageRefresh(refreshAll)
onMounted(async () => {
  try { await loadStatus(); await loadTresore() }
  catch { $q.notify({ type: 'negative', message: 'Fehler beim Laden' }) }
})
onUnmounted(clearReveals)

// ── Reveal ──
function clearReveals() {
  Object.values(revealTimers).forEach(clearTimeout)
  revealed.value = {}
}
function hide(id) {
  if (revealTimers[id]) { clearTimeout(revealTimers[id]); delete revealTimers[id] }
  const r = { ...revealed.value }; delete r[id]; revealed.value = r
}
async function reveal(e) {
  try {
    const { data } = await api.get(`/api/tresor/eintraege/${e.id}/reveal`)
    revealed.value = { ...revealed.value, [e.id]: { passwort: data.passwort, notiz: data.notiz } }
    revealTimers[e.id] = setTimeout(() => hide(e.id), 30000)   // Auto-Verbergen nach 30 s
  } catch (err) {
    $q.notify({ type: 'negative', message: err.response?.data?.detail || 'Anzeigen fehlgeschlagen' })
  }
}
async function copy(text, msg) {
  try { await copyToClipboard(text || ''); $q.notify({ type: 'positive', message: msg, timeout: 1200 }) }
  catch { $q.notify({ type: 'negative', message: 'Kopieren nicht möglich' }) }
}

// ── Tresor CRUD ──
const tresorDialog = ref(false)
const tresorForm = ref({})
const tresorError = ref('')
function openTresorDialog(t = null) {
  tresorError.value = ''
  tresorForm.value = t
    ? { id: t.id, name: t.name, beschreibung: t.beschreibung || '', version: t.version }
    : { id: null, name: '', beschreibung: '' }
  tresorDialog.value = true
}
async function saveTresor() {
  if (!tresorForm.value.name.trim()) { tresorError.value = 'Name darf nicht leer sein.'; return }
  saving.value = true; tresorError.value = ''
  try {
    const payload = { name: tresorForm.value.name.trim(), beschreibung: tresorForm.value.beschreibung || null }
    if (tresorForm.value.id) {
      await api.put(`/api/tresor/${tresorForm.value.id}`, { ...payload, expected_version: tresorForm.value.version })
    } else {
      await api.post('/api/tresor', payload)
    }
    tresorDialog.value = false
    await loadTresore()
  } catch (e) {
    tresorError.value = e.response?.data?.detail || 'Speichern fehlgeschlagen'
  } finally { saving.value = false }
}
function deleteTresor(t) {
  $q.dialog({
    title: 'Tresor löschen',
    message: `Tresor „${t.name}" samt aller ${t.eintrag_anzahl} Einträge löschen?`,
    cancel: true, ok: { label: 'Löschen', color: 'negative' },
  }).onOk(async () => {
    try {
      await api.delete(`/api/tresor/${t.id}`)
      if (selectedId.value === t.id) { selectedId.value = null; eintraege.value = [] }
      await loadTresore()
    } catch (e) {
      $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Löschen fehlgeschlagen' })
    }
  })
}

// ── Eintrag CRUD ──
const eintragDialog = ref(false)
const eintragForm = ref({})
const eintragError = ref('')
function openEintragDialog(e = null) {
  eintragError.value = ''; showPw.value = false
  eintragForm.value = e
    ? { id: e.id, titel: e.titel, benutzername: e.benutzername || '', url: e.url || '',
        passwort: '', notiz: '', passwort_aendern: false, version: e.version }
    : { id: null, titel: '', benutzername: '', url: '', passwort: '', notiz: '', passwort_aendern: true }
  eintragDialog.value = true
}
async function saveEintrag() {
  if (!eintragForm.value.titel.trim()) { eintragError.value = 'Titel darf nicht leer sein.'; return }
  saving.value = true; eintragError.value = ''
  try {
    const f = eintragForm.value
    if (f.id) {
      await api.put(`/api/tresor/eintraege/${f.id}`, {
        titel: f.titel.trim(), benutzername: f.benutzername || null, url: f.url || null,
        passwort_aendern: f.passwort_aendern, passwort: f.passwort, notiz: f.notiz,
        expected_version: f.version,
      })
    } else {
      await api.post(`/api/tresor/${selectedId.value}/eintraege`, {
        titel: f.titel.trim(), benutzername: f.benutzername || null, url: f.url || null,
        passwort: f.passwort, notiz: f.notiz,
      })
    }
    eintragDialog.value = false
    await Promise.all([loadEintraege(selectedId.value), loadTresore()])
  } catch (e) {
    eintragError.value = e.response?.data?.detail || 'Speichern fehlgeschlagen'
  } finally { saving.value = false }
}
function deleteEintrag(e) {
  $q.dialog({
    title: 'Eintrag löschen', message: `Eintrag „${e.titel}" löschen?`,
    cancel: true, ok: { label: 'Löschen', color: 'negative' },
  }).onOk(async () => {
    try {
      await api.delete(`/api/tresor/eintraege/${e.id}`)
      await Promise.all([loadEintraege(selectedId.value), loadTresore()])
    } catch (err) {
      $q.notify({ type: 'negative', message: err.response?.data?.detail || 'Löschen fehlgeschlagen' })
    }
  })
}

// ── Freigaben ──
const freigabenDialog = ref(false)
const freigabenTresor = ref(null)
const freigaben = ref([])
const freigabeError = ref('')
const principals = ref({ users: [], abteilungen: [], funktionen: [] })
const principalsLoading = ref(false)
const principalFilter = ref('')
const nf = ref({ typ: 'user', pid: null, zugriff: 'read' })
const typOptionen = [
  { label: 'Benutzer', value: 'user' },
  { label: 'Abteilung', value: 'abteilung' },
  { label: 'Funktion', value: 'funktion' },
]
const zugriffOptionen = [
  { label: 'Lesen', value: 'read' },
  { label: 'Schreiben', value: 'write' },
]
const principalOptionen = computed(() => {
  const list = { user: principals.value.users, abteilung: principals.value.abteilungen,
    funktion: principals.value.funktionen }[nf.value.typ] || []
  const f = principalFilter.value.toLowerCase()
  return f ? list.filter(p => p.name.toLowerCase().includes(f)) : list
})
function filterPrincipals(val, update) {
  update(() => { principalFilter.value = val || '' })
}
function principalLabel(typ) {
  return { user: 'Benutzer', abteilung: 'Abteilung', funktion: 'Funktion' }[typ] || typ
}
function principalIcon(typ) {
  return { user: 'person', abteilung: 'account_tree', funktion: 'badge' }[typ] || 'help'
}
async function openFreigaben(t) {
  freigabenTresor.value = t; freigabeError.value = ''
  nf.value = { typ: 'user', pid: null, zugriff: 'read' }
  freigabenDialog.value = true
  principalsLoading.value = true
  try {
    const [fr, pr] = await Promise.all([
      api.get(`/api/tresor/${t.id}/freigaben`),
      api.get('/api/tresor/principals'),
    ])
    freigaben.value = fr.data
    principals.value = pr.data
  } catch (e) {
    freigabeError.value = e.response?.data?.detail || 'Laden fehlgeschlagen'
  } finally { principalsLoading.value = false }
}
async function addFreigabe() {
  saving.value = true; freigabeError.value = ''
  try {
    await api.put(`/api/tresor/${freigabenTresor.value.id}/freigaben`, {
      principal_typ: nf.value.typ, principal_id: nf.value.pid, zugriff: nf.value.zugriff,
    })
    const { data } = await api.get(`/api/tresor/${freigabenTresor.value.id}/freigaben`)
    freigaben.value = data
    nf.value.pid = null
    await loadTresore()
  } catch (e) {
    freigabeError.value = e.response?.data?.detail || 'Hinzufügen fehlgeschlagen'
  } finally { saving.value = false }
}
async function revoke(f) {
  try {
    await api.delete(`/api/tresor/${freigabenTresor.value.id}/freigaben/${f.principal_typ}/${f.principal_id}`)
    freigaben.value = freigaben.value.filter(x => x.id !== f.id)
    await loadTresore()
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Entziehen fehlgeschlagen' })
  }
}

// ── Zugriffs-Log ──
const zugriffeDialog = ref(false)
const zugriffeTresor = ref(null)
const zugriffe = ref([])
async function openZugriffe(t) {
  zugriffeTresor.value = t
  zugriffeDialog.value = true
  try {
    const { data } = await api.get(`/api/tresor/${t.id}/zugriffe`)
    zugriffe.value = data
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Log konnte nicht geladen werden' })
  }
}
function fmtTs(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  return isNaN(d) ? ts : d.toLocaleString('de-DE')
}
</script>

<style scoped>
.text-mono {
  font-family: 'Roboto Mono', monospace;
}
</style>
