<template>
  <q-page padding>
    <!-- Kopfzeile -->
    <div class="row items-center q-mb-md">
      <div class="text-h5 col">Tickets</div>
      <q-btn
        icon="add"
        :label="$q.screen.gt.xs ? 'Neues Ticket' : undefined"
        :round="$q.screen.lt.sm"
        color="primary"
        unelevated
        @click="openCreateDialog"
      />
    </div>

    <!-- Filter -->
    <div class="row q-gutter-sm q-mb-md items-center">
      <q-select
        v-model="filterBereich"
        :options="bereichOptions"
        label="Bereich"
        outlined dense clearable
        style="min-width: 160px"
        option-value="id"
        option-label="name"
        emit-value map-options
      />
      <q-select
        v-model="filterStatus"
        :options="statusOptions"
        label="Status"
        outlined dense clearable
        style="min-width: 150px"
        emit-value map-options
      />
      <q-checkbox v-model="filterNurMeine" label="Nur meine" />
    </div>

    <!-- ── Mobile: Karten-Liste ── -->
    <template v-if="$q.screen.lt.sm">
      <div v-if="loading" class="row justify-center q-py-xl">
        <q-spinner size="40px" color="primary" />
      </div>
      <div v-else-if="filteredTickets.length === 0" class="text-center text-grey q-py-xl">
        Keine Tickets gefunden.
      </div>
      <q-card
        v-for="t in filteredTickets"
        :key="t.id"
        flat bordered
        class="q-mb-sm cursor-pointer"
        @click="openDetailDialog(t)"
      >
        <q-card-section class="q-py-sm q-px-md">
          <div class="row items-center q-mb-xs">
            <q-icon :name="prioritaetIcon(t.prioritaet)" :color="prioritaetColor(t.prioritaet)" size="xs" class="q-mr-xs" />
            <span class="text-caption text-grey col">#{{ t.id }}</span>
            <q-chip dense :color="statusColor(t.status)" text-color="white" :label="statusLabel(t.status)" size="xs" />
          </div>
          <div class="text-body2 text-weight-medium">{{ t.titel }}</div>
          <div v-if="t.bereich_name" class="text-caption text-grey">{{ t.bereich_name }}</div>
          <div class="row q-mt-xs text-caption text-grey q-gutter-sm">
            <span v-if="t.kommentar_count > 0"><q-icon name="chat_bubble_outline" size="xs" /> {{ t.kommentar_count }}</span>
            <span v-if="t.anhang_count > 0"><q-icon name="attach_file" size="xs" /> {{ t.anhang_count }}</span>
            <span class="col text-right">{{ formatDate(t.created_at) }}</span>
          </div>
        </q-card-section>
      </q-card>
    </template>

    <!-- ── Desktop: Tabelle ── -->
    <q-table
      v-else
      :rows="filteredTickets"
      :columns="columns"
      row-key="id"
      flat bordered
      :loading="loading"
      :rows-per-page-options="[25, 50, 0]"
    >
      <template #body-cell-status="props">
        <q-td :props="props">
          <q-chip dense :color="statusColor(props.row.status)" text-color="white"
            :label="statusLabel(props.row.status)" size="sm" />
        </q-td>
      </template>
      <template #body-cell-prioritaet="props">
        <q-td :props="props">
          <q-icon :name="prioritaetIcon(props.row.prioritaet)" :color="prioritaetColor(props.row.prioritaet)" size="sm">
            <q-tooltip>{{ prioritaetLabel(props.row.prioritaet) }}</q-tooltip>
          </q-icon>
        </q-td>
      </template>
      <template #body-cell-counts="props">
        <q-td :props="props" class="text-grey">
          <span v-if="props.row.kommentar_count > 0" class="q-mr-sm">
            <q-icon name="chat_bubble_outline" size="xs" /> {{ props.row.kommentar_count }}
          </span>
          <span v-if="props.row.anhang_count > 0">
            <q-icon name="attach_file" size="xs" /> {{ props.row.anhang_count }}
          </span>
        </q-td>
      </template>
      <template #body-cell-actions="props">
        <q-td :props="props">
          <q-btn flat dense round icon="open_in_new" size="sm" color="primary" @click="openDetailDialog(props.row)">
            <q-tooltip>Details</q-tooltip>
          </q-btn>
        </q-td>
      </template>
    </q-table>


    <!-- ═══════════════════════════════════════════════════════
         Ticket anlegen
    ════════════════════════════════════════════════════════ -->
    <q-dialog
      v-model="createDialogOpen"
      persistent
      :position="$q.screen.lt.sm ? 'bottom' : 'standard'"
    >
      <q-card :style="$q.screen.lt.sm ? 'width:100%;border-radius:16px 16px 0 0' : 'min-width:500px'">
        <q-card-section class="text-h6">Neues Ticket</q-card-section>
        <q-separator />
        <q-card-section class="q-gutter-sm">
          <q-input v-model="createForm.titel" label="Titel *" outlined autofocus />
          <q-input v-model="createForm.beschreibung" label="Beschreibung" outlined type="textarea" rows="3" />
          <div class="row q-gutter-sm">
            <q-select
              v-model="createForm.bereich_id"
              :options="bereichOptions"
              label="Bereich"
              outlined dense clearable
              class="col"
              option-value="id"
              option-label="name"
              emit-value map-options
            />
            <q-select
              v-model="createForm.kategorie_id"
              :options="kategorieOptions"
              label="Kategorie"
              outlined dense clearable
              class="col"
              option-value="id"
              option-label="name"
              emit-value map-options
            />
          </div>
          <div class="row q-gutter-sm">
            <q-select
              v-model="createForm.prioritaet"
              :options="prioritaetOptions"
              label="Priorität"
              outlined dense
              class="col"
              emit-value map-options
            />
            <q-input v-model="createForm.faellig_am" type="date" label="Fällig am" outlined dense clearable class="col" />
          </div>
          <q-select
            v-if="isAdmin"
            v-model="createForm.zugewiesen_an"
            :options="userOptions"
            label="Zugewiesen an"
            outlined dense clearable
            emit-value map-options
          />
        </q-card-section>
        <q-separator />
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn
            label="Erstellen"
            icon="arrow_forward"
            color="primary"
            unelevated
            :loading="saving"
            @click="onCreateSave"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>


    <!-- ═══════════════════════════════════════════════════════
         Ticket-Detail  (mit Inline-Bearbeitung)
    ════════════════════════════════════════════════════════ -->
    <q-dialog v-model="detailDialogOpen" maximized>
      <q-card>
        <q-bar class="bg-primary text-white">
          <q-icon name="confirmation_number" />
          <div class="text-subtitle1 q-ml-sm ellipsis" style="max-width:70vw">
            #{{ selectedTicket?.id }}
            <span v-if="!canWrite"> – {{ selectedTicket?.titel }}</span>
          </div>
          <q-space />
          <q-btn flat round dense icon="close" v-close-popup />
        </q-bar>

        <q-scroll-area style="height: calc(100vh - 50px)">
          <div class="q-pa-md" style="max-width: 800px; margin: 0 auto">
            <template v-if="selectedTicket">

              <!-- ── Editierbare Felder (wenn Schreibrecht) ── -->
              <template v-if="canWrite">
                <q-input
                  v-model="detailForm.titel"
                  label="Titel *"
                  outlined
                  class="q-mb-sm"
                />
                <q-input
                  v-model="detailForm.beschreibung"
                  label="Beschreibung"
                  outlined
                  type="textarea"
                  rows="4"
                  class="q-mb-sm"
                />
                <div class="row q-gutter-sm q-mb-sm">
                  <q-select
                    v-model="detailForm.bereich_id"
                    :options="bereichOptions"
                    label="Bereich"
                    outlined dense clearable
                    class="col"
                    option-value="id"
                    option-label="name"
                    emit-value map-options
                  />
                  <q-select
                    v-model="detailForm.kategorie_id"
                    :options="kategorieOptions"
                    label="Kategorie"
                    outlined dense clearable
                    class="col"
                    option-value="id"
                    option-label="name"
                    emit-value map-options
                  />
                </div>
                <div class="row q-gutter-sm q-mb-sm">
                  <q-select
                    v-model="detailForm.prioritaet"
                    :options="prioritaetOptions"
                    label="Priorität"
                    outlined dense
                    class="col"
                    emit-value map-options
                  />
                  <q-input
                    v-model="detailForm.faellig_am"
                    type="date"
                    label="Fällig am"
                    outlined dense
                    clearable
                    class="col"
                  />
                  <q-select
                    v-if="isAdmin"
                    v-model="detailForm.zugewiesen_an"
                    :options="userOptions"
                    label="Zugewiesen an"
                    outlined dense clearable
                    class="col"
                    emit-value map-options
                  />
                </div>
                <div class="row justify-end q-mb-md">
                  <q-btn
                    v-if="detailFormDirty"
                    label="Speichern"
                    icon="save"
                    color="primary"
                    unelevated
                    size="sm"
                    :loading="detailSaving"
                    @click="onDetailSave"
                  />
                </div>
              </template>

              <!-- ── Nur-Lesen-Ansicht ── -->
              <template v-else>
                <div class="text-h6 q-mb-sm">{{ selectedTicket.titel }}</div>
                <div class="text-body2 q-mb-md" style="white-space: pre-wrap">
                  {{ selectedTicket.beschreibung || '—' }}
                </div>
              </template>

              <!-- Metadaten-Zeile -->
              <div class="row q-gutter-md q-mb-md items-center">
                <div>
                  <div class="text-caption text-grey">Status</div>
                  <q-chip dense :color="statusColor(selectedTicket.status)" text-color="white"
                    :label="statusLabel(selectedTicket.status)" />
                </div>
                <div v-if="!canWrite">
                  <div class="text-caption text-grey">Priorität</div>
                  <div class="row items-center q-gutter-xs">
                    <q-icon :name="prioritaetIcon(selectedTicket.prioritaet)" :color="prioritaetColor(selectedTicket.prioritaet)" />
                    <span>{{ prioritaetLabel(selectedTicket.prioritaet) }}</span>
                  </div>
                </div>
                <div v-if="selectedTicket.faellig_am && !canWrite">
                  <div class="text-caption text-grey">Fällig am</div>
                  <div>{{ formatDate(selectedTicket.faellig_am) }}</div>
                </div>
              </div>

              <!-- Statuswechsel -->
              <div v-if="!isAbgeschlossen(selectedTicket) && canWrite" class="q-mb-md">
                <div class="text-subtitle2 q-mb-xs">Status ändern</div>
                <div class="row q-gutter-sm">
                  <q-btn
                    v-for="s in erlaubteStatus(selectedTicket)"
                    :key="s"
                    outline
                    :color="statusColor(s)"
                    :label="statusLabel(s)"
                    size="sm"
                    @click="doStatusChange(s)"
                  />
                </div>
              </div>

              <q-separator class="q-mb-md" />

              <!-- Anhänge -->
              <div class="q-mb-md">
                <div class="text-subtitle2 q-mb-sm">Anhänge</div>
                <anhang-panel
                  :anhaenge="detailAnhaenge"
                  :upload-url="`/api/tickets/${selectedTicket.id}/anhaenge`"
                  :can-upload="!isAbgeschlossen(selectedTicket)"
                  :can-delete="!isAbgeschlossen(selectedTicket)"
                  @uploaded="onAnhangUploaded"
                  @deleted="onAnhangDeleted"
                />
              </div>

              <q-separator class="q-mb-md" />

              <!-- Kommentar-Thread -->
              <div>
                <div class="text-subtitle2 q-mb-sm">
                  Kommentare
                  <q-badge v-if="kommentare.length > 0" color="grey" class="q-ml-xs">{{ kommentare.length }}</q-badge>
                </div>

                <div v-if="kommentareLoading" class="row justify-center q-py-md">
                  <q-spinner color="primary" />
                </div>

                <div v-for="k in kommentare" :key="k.id" class="q-mb-sm">
                  <q-card flat :class="k.sichtbarkeit === 'intern' ? 'bg-amber-1' : 'bg-grey-1'">
                    <q-card-section class="q-py-sm q-px-md">
                      <div class="row items-center q-mb-xs">
                        <span class="text-caption text-weight-bold col">{{ k.autor_username }}</span>
                        <q-badge v-if="k.sichtbarkeit === 'intern'" color="amber-8" label="intern" class="q-mr-sm" />
                        <span class="text-caption text-grey">{{ formatDateTime(k.created_at) }}</span>
                        <q-btn
                          v-if="k.autor_id === currentUserId || isAdmin"
                          flat round dense icon="delete" size="xs" color="negative"
                          class="q-ml-xs"
                          @click="deleteKommentar(k)"
                        />
                      </div>
                      <div class="text-body2" style="white-space: pre-wrap">{{ k.inhalt }}</div>
                    </q-card-section>
                  </q-card>
                </div>

                <!-- Neuer Kommentar -->
                <div v-if="!isAbgeschlossen(selectedTicket)" class="q-mt-md">
                  <q-input
                    v-model="neuerKommentar"
                    outlined
                    type="textarea"
                    rows="3"
                    label="Kommentar schreiben…"
                  />
                  <div class="row items-center q-mt-sm q-gutter-sm">
                    <q-toggle
                      v-if="canWrite"
                      v-model="kommentarIntern"
                      label="Intern"
                      color="amber-8"
                      size="sm"
                    />
                    <q-space />
                    <q-btn
                      label="Absenden"
                      icon="send"
                      color="primary"
                      unelevated
                      size="sm"
                      :loading="kommentarSaving"
                      :disable="!neuerKommentar.trim()"
                      @click="sendKommentar"
                    />
                  </div>
                </div>
              </div>

            </template>
          </div>
        </q-scroll-area>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { useAuthStore } from 'src/stores/auth'
import AnhangPanel from 'src/components/AnhangPanel.vue'

const $q = useQuasar()
const auth = useAuthStore()
const isAdmin = computed(() => auth.user?.role === 'admin')
const currentUserId = computed(() => auth.user?.id)

// ── Daten ──────────────────────────────────────────────────────────────────
const tickets = ref([])
const bereiche = ref([])
const kategorien = ref([])
const users = ref([])
const loading = ref(false)

// ── Filter ─────────────────────────────────────────────────────────────────
const filterBereich = ref(null)
const filterStatus = ref(null)
const filterNurMeine = ref(false)

// ── Erstellen-Dialog ───────────────────────────────────────────────────────
const createDialogOpen = ref(false)
const saving = ref(false)
const createForm = ref(emptyCreateForm())

// ── Detail-Dialog ──────────────────────────────────────────────────────────
const detailDialogOpen = ref(false)
const selectedTicket = ref(null)
const detailAnhaenge = ref([])

// Inline-Edit-Formular im Detail-Dialog
const detailForm = ref({})
const detailSaving = ref(false)
const detailFormDirty = computed(() => {
  if (!selectedTicket.value) return false
  const t = selectedTicket.value
  return (
    detailForm.value.titel !== t.titel ||
    detailForm.value.beschreibung !== (t.beschreibung || '') ||
    detailForm.value.bereich_id !== t.bereich_id ||
    detailForm.value.kategorie_id !== t.kategorie_id ||
    detailForm.value.prioritaet !== t.prioritaet ||
    detailForm.value.faellig_am !== (t.faellig_am || '') ||
    detailForm.value.zugewiesen_an !== t.zugewiesen_an
  )
})

// ── Kommentare ─────────────────────────────────────────────────────────────
const kommentare = ref([])
const kommentareLoading = ref(false)
const neuerKommentar = ref('')
const kommentarIntern = ref(false)
const kommentarSaving = ref(false)

// ── Berechtigungen ─────────────────────────────────────────────────────────
const canWrite = computed(() => {
  if (!selectedTicket.value) return false
  return isAdmin.value || selectedTicket.value.gemeldet_von === currentUserId.value
})

// ── Status-/Prioritäts-Konstanten ──────────────────────────────────────────
const STATUS_UEBERGAENGE = {
  offen:       ['in_pruefung', 'erledigt', 'abgelehnt'],
  in_pruefung: ['eingeplant', 'rueckfrage', 'erledigt', 'abgelehnt'],
  eingeplant:  ['in_pruefung', 'erledigt'],
  rueckfrage:  ['in_pruefung', 'abgelehnt'],
  erledigt:    [],
  abgelehnt:   [],
}

const STATUS_LABELS = {
  offen: 'Offen', in_pruefung: 'In Prüfung', eingeplant: 'Eingeplant',
  rueckfrage: 'Rückfrage', erledigt: 'Erledigt', abgelehnt: 'Abgelehnt',
}

const STATUS_COLORS = {
  offen: 'blue', in_pruefung: 'orange', eingeplant: 'purple',
  rueckfrage: 'amber-8', erledigt: 'positive', abgelehnt: 'negative',
}

const statusOptions = Object.entries(STATUS_LABELS).map(([value, label]) => ({ value, label }))

const prioritaetOptions = [
  { value: 'niedrig', label: 'Niedrig' },
  { value: 'normal',  label: 'Normal'  },
  { value: 'hoch',    label: 'Hoch'    },
  { value: 'sicherheit', label: 'Sicherheit' },
]

const bereichOptions = computed(() => bereiche.value)
const kategorieOptions = computed(() => kategorien.value)
const userOptions = computed(() => users.value.map(u => ({ value: u.id, label: u.username })))

const filteredTickets = computed(() => {
  let result = tickets.value
  if (filterBereich.value) result = result.filter(t => t.bereich_id === filterBereich.value)
  if (filterStatus.value)  result = result.filter(t => t.status === filterStatus.value)
  if (filterNurMeine.value) result = result.filter(t => t.gemeldet_von === currentUserId.value)
  return result
})

const columns = [
  { name: 'id',         label: '#',        field: 'id',         align: 'left',   sortable: true, style: 'width:55px' },
  { name: 'prioritaet', label: '',         field: 'prioritaet', align: 'center', style: 'width:40px' },
  { name: 'titel',      label: 'Titel',    field: 'titel',      align: 'left',   sortable: true },
  { name: 'status',     label: 'Status',   field: 'status',     align: 'left'  },
  { name: 'counts',     label: '',         field: 'id',         align: 'left',   style: 'width:80px' },
  { name: 'created_at', label: 'Erstellt', field: 'created_at', align: 'left',   sortable: true, format: v => formatDate(v) },
  { name: 'actions',    label: '',         field: 'actions',    align: 'right',  style: 'width:60px' },
]

// ── Hilfsfunktionen ────────────────────────────────────────────────────────
function statusLabel(s)    { return STATUS_LABELS[s] ?? s }
function statusColor(s)    { return STATUS_COLORS[s] ?? 'grey' }
function isAbgeschlossen(t){ return t?.status === 'erledigt' || t?.status === 'abgelehnt' }
function erlaubteStatus(t) { return STATUS_UEBERGAENGE[t?.status] ?? [] }

function prioritaetIcon(p)  { return { niedrig: 'keyboard_arrow_down', normal: 'remove', hoch: 'keyboard_arrow_up', sicherheit: 'warning' }[p] ?? 'remove' }
function prioritaetColor(p) { return { niedrig: 'grey', normal: 'primary', hoch: 'orange', sicherheit: 'negative' }[p] ?? 'grey' }
function prioritaetLabel(p) { return { niedrig: 'Niedrig', normal: 'Normal', hoch: 'Hoch', sicherheit: 'Sicherheit' }[p] ?? p }

function formatDate(iso) {
  if (!iso) return '—'
  return iso.substring(0, 10).split('-').reverse().join('.')
}
function formatDateTime(iso) {
  if (!iso) return '—'
  const [date, time] = iso.split(' ')
  return `${date.split('-').reverse().join('.')} ${(time ?? '').substring(0, 5)}`
}

function emptyCreateForm() {
  return { titel: '', beschreibung: '', bereich_id: null, kategorie_id: null, prioritaet: 'normal', faellig_am: '', zugewiesen_an: null }
}

function syncDetailForm(ticket) {
  detailForm.value = {
    titel:         ticket.titel,
    beschreibung:  ticket.beschreibung || '',
    bereich_id:    ticket.bereich_id,
    kategorie_id:  ticket.kategorie_id,
    prioritaet:    ticket.prioritaet,
    faellig_am:    ticket.faellig_am || '',
    zugewiesen_an: ticket.zugewiesen_an,
  }
}

// ── Laden ──────────────────────────────────────────────────────────────────
async function loadAll() {
  loading.value = true
  try {
    const requests = [
      api.get('/api/tickets/'),
      api.get('/api/tickets/bereiche'),
      api.get('/api/tickets/kategorien'),
    ]
    if (isAdmin.value) requests.push(api.get('/api/users/'))
    const results = await Promise.all(requests)
    tickets.value = results[0].data
    bereiche.value = results[1].data
    kategorien.value = results[2].data
    if (isAdmin.value) users.value = results[3].data
  } catch {
    $q.notify({ type: 'negative', message: 'Fehler beim Laden der Tickets.' })
  } finally {
    loading.value = false
  }
}

// ── Erstellen ──────────────────────────────────────────────────────────────
function openCreateDialog() {
  createForm.value = emptyCreateForm()
  createDialogOpen.value = true
}

async function onCreateSave() {
  if (!createForm.value.titel.trim()) {
    $q.notify({ type: 'warning', message: 'Bitte einen Titel eingeben.' })
    return
  }
  saving.value = true
  try {
    const { data } = await api.post('/api/tickets/', createForm.value)
    createDialogOpen.value = false
    await loadAll()
    // Direkt in den Detail-Dialog wechseln
    const fresh = tickets.value.find(t => t.id === data.id) ?? data
    openDetailDialog(fresh)
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Speichern.' })
  } finally {
    saving.value = false
  }
}

// ── Detail ─────────────────────────────────────────────────────────────────
async function openDetailDialog(ticket) {
  selectedTicket.value = ticket
  syncDetailForm(ticket)
  detailAnhaenge.value = []
  kommentare.value = []
  detailDialogOpen.value = true
  await Promise.all([loadAnhaenge(ticket.id), loadKommentare(ticket.id)])
}

// Wenn selectedTicket von außen aktualisiert wird (Statuswechsel), Form nachziehen
watch(selectedTicket, (t) => { if (t) syncDetailForm(t) }, { deep: false })

async function loadAnhaenge(ticketId) {
  try {
    const { data } = await api.get(`/api/tickets/${ticketId}/anhaenge`)
    detailAnhaenge.value = data
  } catch { /* ignorieren */ }
}

// ── Inline-Speichern ───────────────────────────────────────────────────────
async function onDetailSave() {
  if (!detailForm.value.titel.trim()) {
    $q.notify({ type: 'warning', message: 'Bitte einen Titel eingeben.' })
    return
  }
  detailSaving.value = true
  try {
    const { data } = await api.put(`/api/tickets/${selectedTicket.value.id}`, {
      ...detailForm.value,
      expected_version: selectedTicket.value.version,
    })
    selectedTicket.value = data
    const idx = tickets.value.findIndex(t => t.id === data.id)
    if (idx >= 0) tickets.value[idx] = data
    $q.notify({ type: 'positive', message: 'Gespeichert.' })
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Speichern.' })
  } finally {
    detailSaving.value = false
  }
}

// ── Statuswechsel ──────────────────────────────────────────────────────────
async function doStatusChange(newStatus) {
  if (!selectedTicket.value) return
  try {
    const { data } = await api.patch(`/api/tickets/${selectedTicket.value.id}/status`, {
      status: newStatus,
      expected_version: selectedTicket.value.version,
    })
    selectedTicket.value = data
    const idx = tickets.value.findIndex(t => t.id === data.id)
    if (idx >= 0) tickets.value[idx] = data
    $q.notify({ type: 'positive', message: `Status auf „${statusLabel(newStatus)}" gesetzt.` })
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Statuswechsel.' })
  }
}

// ── Anhänge ────────────────────────────────────────────────────────────────
function onAnhangUploaded(newAnhang) {
  detailAnhaenge.value = [...detailAnhaenge.value, newAnhang]
  if (selectedTicket.value) {
    selectedTicket.value = { ...selectedTicket.value, anhang_count: (selectedTicket.value.anhang_count || 0) + 1 }
  }
}

function onAnhangDeleted(anhangId) {
  detailAnhaenge.value = detailAnhaenge.value.filter(a => a.id !== anhangId)
  if (selectedTicket.value?.anhang_count > 0) {
    selectedTicket.value = { ...selectedTicket.value, anhang_count: selectedTicket.value.anhang_count - 1 }
  }
}

// ── Kommentare ─────────────────────────────────────────────────────────────
async function loadKommentare(ticketId) {
  kommentareLoading.value = true
  try {
    const { data } = await api.get(`/api/tickets/${ticketId}/kommentare`)
    kommentare.value = data
  } catch { /* ignorieren */ } finally {
    kommentareLoading.value = false
  }
}

async function sendKommentar() {
  if (!neuerKommentar.value.trim() || !selectedTicket.value) return
  kommentarSaving.value = true
  try {
    const { data } = await api.post(`/api/tickets/${selectedTicket.value.id}/kommentare`, {
      inhalt: neuerKommentar.value,
      sichtbarkeit: kommentarIntern.value ? 'intern' : 'oeffentlich',
    })
    kommentare.value = [...kommentare.value, data]
    neuerKommentar.value = ''
    kommentarIntern.value = false
    const cnt = (selectedTicket.value.kommentar_count || 0) + 1
    selectedTicket.value = { ...selectedTicket.value, kommentar_count: cnt }
    const idx = tickets.value.findIndex(t => t.id === selectedTicket.value.id)
    if (idx >= 0) tickets.value[idx] = { ...tickets.value[idx], kommentar_count: cnt }
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Senden.' })
  } finally {
    kommentarSaving.value = false
  }
}

async function deleteKommentar(k) {
  $q.dialog({ title: 'Kommentar löschen', message: 'Wirklich löschen?', cancel: true })
    .onOk(async () => {
      try {
        await api.delete(`/api/tickets/${selectedTicket.value.id}/kommentare/${k.id}`)
        kommentare.value = kommentare.value.filter(c => c.id !== k.id)
        if (selectedTicket.value?.kommentar_count > 0) {
          selectedTicket.value = { ...selectedTicket.value, kommentar_count: selectedTicket.value.kommentar_count - 1 }
        }
      } catch (e) {
        $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Löschen.' })
      }
    })
}

onMounted(loadAll)
</script>
