<template>
  <q-page padding>
    <div class="row items-center q-mb-md">
      <div class="text-h5 col">Tickets</div>
      <q-btn
        label="Neues Ticket"
        icon="add"
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
        style="min-width: 180px"
        option-value="id"
        option-label="name"
        emit-value map-options
      />
      <q-select
        v-model="filterStatus"
        :options="statusOptions"
        label="Status"
        outlined dense clearable
        style="min-width: 160px"
        emit-value map-options
      />
    </div>

    <!-- Ticket-Tabelle -->
    <div v-if="loading" class="row justify-center q-py-xl">
      <q-spinner size="40px" color="primary" />
    </div>

    <q-table
      v-else
      :rows="filteredTickets"
      :columns="columns"
      row-key="id"
      flat bordered
      :rows-per-page-options="[25, 50, 0]"
    >
      <template #body-cell-status="props">
        <q-td :props="props">
          <q-chip
            dense
            :color="statusColor(props.row.status)"
            text-color="white"
            :label="statusLabel(props.row.status)"
            size="sm"
          />
        </q-td>
      </template>

      <template #body-cell-prioritaet="props">
        <q-td :props="props">
          <q-icon :name="prioritaetIcon(props.row.prioritaet)" :color="prioritaetColor(props.row.prioritaet)" size="sm">
            <q-tooltip>{{ props.row.prioritaet }}</q-tooltip>
          </q-icon>
        </q-td>
      </template>

      <template #body-cell-actions="props">
        <q-td :props="props">
          <q-btn flat dense round icon="open_in_new" size="sm" color="primary"
            @click="openDetailDialog(props.row)">
            <q-tooltip>Details</q-tooltip>
          </q-btn>
        </q-td>
      </template>
    </q-table>

    <!-- Ticket anlegen -->
    <q-dialog v-model="createDialogOpen" persistent>
      <q-card style="min-width: 500px">
        <q-card-section class="text-h6">Neues Ticket</q-card-section>
        <q-separator />
        <q-card-section class="q-gutter-sm">
          <q-input v-model="form.titel" label="Titel *" outlined />
          <q-input v-model="form.beschreibung" label="Beschreibung" outlined type="textarea" rows="3" />
          <div class="row q-gutter-sm">
            <q-select
              v-model="form.bereich_id"
              :options="bereichOptions"
              label="Bereich"
              outlined dense clearable
              class="col"
              option-value="id"
              option-label="name"
              emit-value map-options
            />
            <q-select
              v-model="form.prioritaet"
              :options="prioritaetOptions"
              label="Priorität"
              outlined dense
              class="col"
              emit-value map-options
            />
          </div>
        </q-card-section>
        <q-separator />
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn
            label="Ticket erstellen"
            color="primary"
            unelevated
            :loading="saving"
            @click="onSave"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Ticket-Detail -->
    <q-dialog v-model="detailDialogOpen" maximized>
      <q-card>
        <q-bar>
          <q-icon name="confirmation_number" />
          <div class="text-subtitle1 q-ml-sm">
            Ticket #{{ selectedTicket?.id }} – {{ selectedTicket?.titel }}
          </div>
          <q-space />
          <q-btn flat round dense icon="close" v-close-popup />
        </q-bar>

        <q-card-section v-if="selectedTicket" class="q-gutter-md">
          <!-- Metadaten -->
          <div class="row q-gutter-md">
            <div class="col">
              <div class="text-caption text-grey">Status</div>
              <q-chip dense :color="statusColor(selectedTicket.status)" text-color="white"
                :label="statusLabel(selectedTicket.status)" />
            </div>
            <div class="col">
              <div class="text-caption text-grey">Priorität</div>
              <div>{{ selectedTicket.prioritaet }}</div>
            </div>
            <div class="col" v-if="selectedTicket.faellig_am">
              <div class="text-caption text-grey">Fällig am</div>
              <div>{{ selectedTicket.faellig_am }}</div>
            </div>
          </div>

          <q-separator />

          <!-- Beschreibung -->
          <div>
            <div class="text-subtitle2 q-mb-xs">Beschreibung</div>
            <div class="text-body2" style="white-space: pre-wrap">{{ selectedTicket.beschreibung || '—' }}</div>
          </div>

          <q-separator />

          <!-- Statuswechsel -->
          <div v-if="!isAbgeschlossen(selectedTicket)">
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

          <q-separator />

          <!-- Anhänge -->
          <div>
            <div class="text-subtitle2 q-mb-sm">Anhänge ({{ detailAnhaenge.length }})</div>
            <anhang-panel
              :anhaenge="detailAnhaenge"
              :upload-url="`/api/tickets/${selectedTicket.id}/anhaenge`"
              :can-upload="!isAbgeschlossen(selectedTicket)"
              :can-delete="!isAbgeschlossen(selectedTicket)"
              @uploaded="onAnhangUploaded"
              @deleted="onAnhangDeleted"
            />
          </div>
        </q-card-section>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { useAuthStore } from 'src/stores/auth'
import AnhangPanel from 'src/components/AnhangPanel.vue'

const $q = useQuasar()
const auth = useAuthStore()
const isAdmin = computed(() => auth.user?.role === 'admin')

const tickets = ref([])
const bereiche = ref([])
const loading = ref(false)

const filterBereich = ref(null)
const filterStatus = ref(null)

const createDialogOpen = ref(false)
const saving = ref(false)
const form = ref(emptyForm())

const detailDialogOpen = ref(false)
const selectedTicket = ref(null)
const detailAnhaenge = ref([])

const STATUS_UEBERGAENGE = {
  offen:       ['in_pruefung', 'erledigt', 'abgelehnt'],
  in_pruefung: ['eingeplant', 'rueckfrage', 'erledigt', 'abgelehnt'],
  eingeplant:  ['in_pruefung', 'erledigt'],
  rueckfrage:  ['in_pruefung', 'abgelehnt'],
  erledigt:    [],
  abgelehnt:   [],
}

const STATUS_LABELS = {
  offen: 'Offen',
  in_pruefung: 'In Prüfung',
  eingeplant: 'Eingeplant',
  rueckfrage: 'Rückfrage',
  erledigt: 'Erledigt',
  abgelehnt: 'Abgelehnt',
}

const STATUS_COLORS = {
  offen: 'blue',
  in_pruefung: 'orange',
  eingeplant: 'purple',
  rueckfrage: 'amber-8',
  erledigt: 'positive',
  abgelehnt: 'negative',
}

const statusOptions = Object.entries(STATUS_LABELS).map(([value, label]) => ({ value, label }))

const prioritaetOptions = [
  { value: 'niedrig', label: 'Niedrig' },
  { value: 'normal', label: 'Normal' },
  { value: 'hoch', label: 'Hoch' },
  { value: 'sicherheit', label: 'Sicherheit' },
]

const bereichOptions = computed(() => bereiche.value)

const filteredTickets = computed(() => {
  let result = tickets.value
  if (filterBereich.value) result = result.filter(t => t.bereich_id === filterBereich.value)
  if (filterStatus.value) result = result.filter(t => t.status === filterStatus.value)
  return result
})

const columns = [
  { name: 'id', label: '#', field: 'id', align: 'left', sortable: true, style: 'width: 60px' },
  { name: 'prioritaet', label: '', field: 'prioritaet', align: 'center', style: 'width: 40px' },
  { name: 'titel', label: 'Titel', field: 'titel', align: 'left', sortable: true },
  { name: 'status', label: 'Status', field: 'status', align: 'left' },
  { name: 'created_at', label: 'Erstellt', field: 'created_at', align: 'left', sortable: true },
  { name: 'actions', label: '', field: 'actions', align: 'right', style: 'width: 60px' },
]

function statusLabel(s) { return STATUS_LABELS[s] ?? s }
function statusColor(s) { return STATUS_COLORS[s] ?? 'grey' }

function prioritaetIcon(p) {
  return { niedrig: 'keyboard_arrow_down', normal: 'remove', hoch: 'keyboard_arrow_up', sicherheit: 'warning' }[p] ?? 'remove'
}

function prioritaetColor(p) {
  return { niedrig: 'grey', normal: 'primary', hoch: 'orange', sicherheit: 'negative' }[p] ?? 'grey'
}

function isAbgeschlossen(ticket) {
  return ticket?.status === 'erledigt' || ticket?.status === 'abgelehnt'
}

function erlaubteStatus(ticket) {
  return STATUS_UEBERGAENGE[ticket?.status] ?? []
}

function emptyForm() {
  return { titel: '', beschreibung: '', bereich_id: null, prioritaet: 'normal' }
}

async function loadAll() {
  loading.value = true
  try {
    const [ticketsRes, bereicheRes] = await Promise.all([
      api.get('/api/tickets/'),
      api.get('/api/tickets/bereiche'),
    ])
    tickets.value = ticketsRes.data
    bereiche.value = bereicheRes.data
  } catch {
    $q.notify({ type: 'negative', message: 'Fehler beim Laden der Tickets.' })
  } finally {
    loading.value = false
  }
}

function openCreateDialog() {
  form.value = emptyForm()
  createDialogOpen.value = true
}

async function onSave() {
  if (!form.value.titel.trim()) {
    $q.notify({ type: 'warning', message: 'Bitte einen Titel eingeben.' })
    return
  }
  saving.value = true
  try {
    await api.post('/api/tickets/', form.value)
    $q.notify({ type: 'positive', message: 'Ticket erstellt.' })
    createDialogOpen.value = false
    await loadAll()
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Speichern.' })
  } finally {
    saving.value = false
  }
}

async function openDetailDialog(ticket) {
  selectedTicket.value = ticket
  detailAnhaenge.value = []
  detailDialogOpen.value = true
  try {
    const { data } = await api.get(`/api/tickets/${ticket.id}/anhaenge`)
    detailAnhaenge.value = data
  } catch { /* ignorieren */ }
}

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

function onAnhangUploaded(newAnhang) {
  detailAnhaenge.value = [...detailAnhaenge.value, newAnhang]
  if (selectedTicket.value) {
    selectedTicket.value = { ...selectedTicket.value, anhang_count: (selectedTicket.value.anhang_count || 0) + 1 }
  }
}

function onAnhangDeleted(anhangId) {
  detailAnhaenge.value = detailAnhaenge.value.filter(a => a.id !== anhangId)
  if (selectedTicket.value && selectedTicket.value.anhang_count > 0) {
    selectedTicket.value = { ...selectedTicket.value, anhang_count: selectedTicket.value.anhang_count - 1 }
  }
}

onMounted(loadAll)
</script>
