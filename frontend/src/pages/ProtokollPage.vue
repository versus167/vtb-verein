<template>
  <q-page padding>
    <div class="row items-center q-mb-md">
      <div class="text-h5">Zugriffsprotokoll</div>
      <q-space />
      <q-btn
        flat round icon="refresh" :loading="loading"
        @click="reload" aria-label="Aktualisieren"
      >
        <q-tooltip>Aktualisieren</q-tooltip>
      </q-btn>
    </div>

    <q-card flat bordered class="q-mb-md">
      <q-card-section class="row q-col-gutter-md items-end">
        <q-select
          v-model="filter.category" :options="categoryOptions" label="Kategorie"
          emit-value map-options dense outline clearable
          class="col-12 col-sm-3" @update:model-value="reload"
        />
        <q-select
          v-model="filter.event_type" :options="eventTypeOptions" label="Ereignis"
          emit-value map-options dense outline clearable
          class="col-12 col-sm-3" @update:model-value="reload"
        />
        <q-select
          v-model="filter.username" :options="usernameOptions" label="Benutzer"
          dense outline clearable use-input input-debounce="0" @filter="filterUsernames"
          class="col-12 col-sm-2" @update:model-value="reload"
        />
        <q-input
          v-model="filter.since" type="date" label="von" dense outline clearable
          class="col-6 col-sm-2" @update:model-value="reload"
        />
        <q-input
          v-model="filter.until" type="date" label="bis" dense outline clearable
          class="col-6 col-sm-2" @update:model-value="reload"
        />
      </q-card-section>
    </q-card>

    <q-table
      flat bordered
      :rows="rows"
      :columns="columns"
      row-key="id"
      :loading="loading"
      v-model:pagination="pagination"
      :rows-per-page-options="[25, 50, 100, 200]"
      @request="onRequest"
      no-data-label="Keine Protokolleinträge"
      binary-state-sort
    >
      <template #body-cell-event_type="props">
        <q-td :props="props">
          <q-chip
            dense :color="eventColor(props.row.event_type)" text-color="white"
            :label="eventLabel(props.row.event_type)"
          />
        </q-td>
      </template>
      <template #body-cell-user_agent="props">
        <q-td :props="props">
          <span class="ellipsis-2-lines" :title="props.row.user_agent || ''">
            {{ props.row.user_agent || '–' }}
          </span>
        </q-td>
      </template>
    </q-table>
  </q-page>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'

const $q = useQuasar()
const loading = ref(false)
const rows = ref([])

const filter = ref({
  category: null,
  event_type: null,
  username: '',
  since: null,
  until: null,
})

const pagination = ref({
  sortBy: 'created_at',
  descending: true,
  page: 1,
  rowsPerPage: 25,
  rowsNumber: 0,
})

// Benutzer-Dropdown: nur die im Protokoll vorkommenden Benutzer (Ticket #34).
const allUsernames = ref([])
const usernameOptions = ref([])

async function loadUsernames() {
  try {
    const { data } = await api.get('/api/protokoll/benutzer')
    allUsernames.value = data
    usernameOptions.value = data
  } catch {
    // Dropdown bleibt leer; der Filter ist optional
  }
}

function filterUsernames(val, update) {
  update(() => {
    const needle = val.toLowerCase()
    usernameOptions.value = needle
      ? allUsernames.value.filter((u) => u.toLowerCase().includes(needle))
      : allUsernames.value
  })
}

const categoryOptions = [
  { label: 'Anmeldung (auth)', value: 'auth' },
  { label: 'Seitenaufrufe (page)', value: 'page' },
  { label: 'Datenbereinigung (prune)', value: 'prune' },
]

const EVENT_META = {
  login_success: { label: 'Login OK', color: 'positive' },
  login_failed: { label: 'Login fehlgeschlagen', color: 'negative' },
  logout: { label: 'Logout', color: 'grey' },
  magic_link_request: { label: 'Magic-Link angefordert', color: 'info' },
  magic_link_login: { label: 'Magic-Link Login', color: 'positive' },
  magic_link_failed: { label: 'Magic-Link fehlgeschlagen', color: 'negative' },
  page_view: { label: 'Seitenaufruf', color: 'primary' },
  prune_executed: { label: 'Bereinigung ausgeführt', color: 'negative' },
  prune_config_changed: { label: 'Bereinigung: Einstellung geändert', color: 'warning' },
  prune_config_reset: { label: 'Bereinigung: Einstellung zurückgesetzt', color: 'grey' },
}

const eventTypeOptions = Object.entries(EVENT_META).map(([value, m]) => ({ label: m.label, value }))

const eventLabel = (t) => EVENT_META[t]?.label || t
const eventColor = (t) => EVENT_META[t]?.color || 'grey'

const fmtDate = (v) => (v ? new Date(v).toLocaleString('de-DE') : '–')

const columns = [
  { name: 'created_at', label: 'Zeitpunkt', field: 'created_at', align: 'left', format: fmtDate },
  { name: 'event_type', label: 'Ereignis', field: 'event_type', align: 'left' },
  { name: 'username', label: 'Benutzer', field: (r) => r.username || '–', align: 'left' },
  { name: 'detail', label: 'Detail', field: (r) => r.detail || '–', align: 'left' },
  { name: 'ip', label: 'IP', field: (r) => r.ip || '–', align: 'left' },
  { name: 'user_agent', label: 'Gerät', field: 'user_agent', align: 'left' },
]

async function onRequest(props) {
  const { page, rowsPerPage } = props.pagination
  loading.value = true
  try {
    const params = {
      limit: rowsPerPage,
      offset: (page - 1) * rowsPerPage,
    }
    if (filter.value.category) params.category = filter.value.category
    if (filter.value.event_type) params.event_type = filter.value.event_type
    if (filter.value.username) params.username = filter.value.username
    if (filter.value.since) params.since = `${filter.value.since} 00:00:00`
    if (filter.value.until) params.until = `${filter.value.until} 23:59:59`

    const { data } = await api.get('/api/protokoll', { params })
    rows.value = data.items
    pagination.value.rowsNumber = data.total
    pagination.value.page = page
    pagination.value.rowsPerPage = rowsPerPage
  } catch {
    $q.notify({ type: 'negative', message: 'Protokoll konnte nicht geladen werden' })
  } finally {
    loading.value = false
  }
}

function reload() {
  onRequest({ pagination: { ...pagination.value, page: 1 } })
}

onMounted(() => {
  loadUsernames()
  reload()
})
</script>
