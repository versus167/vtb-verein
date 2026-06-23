<template>
  <q-page padding>
    <div class="row items-center q-mb-md">
      <div class="text-h5 col">Abteilungen</div>
      <q-btn
        v-if="auth.hasPermission('abteilungen.write')"
        label="Neu"
        icon="add"
        color="primary"
        unelevated
        @click="openCreateDialog"
      />
    </div>

    <q-table
      :rows="abteilungen"
      :columns="columns"
      row-key="id"
      :loading="loading"
      :filter="filter"
      flat
      bordered
      :rows-per-page-options="[15, 25, 50, 0]"
      rows-per-page="15"
    >
      <template #top-right>
        <div class="row q-gutter-sm items-center">
          <q-input v-model="filter" placeholder="Suchen…" dense outlined clearable>
            <template #append><q-icon name="search" /></template>
          </q-input>
          <q-btn
            label="Papierkorb"
            icon="delete_sweep"
            flat
            color="secondary"
            @click="trashOpen = true"
          />
        </div>
      </template>

      <template #body-cell-actions="props">
        <q-td :props="props" class="q-gutter-xs">
          <q-btn
            v-if="auth.hasPermission('abteilungen.write')"
            flat dense round icon="edit" color="primary" size="sm"
            @click="openEditDialog(props.row)"
          />
          <q-btn
            v-if="auth.hasPermission('abteilungen.delete')"
            flat dense round icon="delete" color="negative" size="sm"
            @click="confirmDelete(props.row)"
          />
        </q-td>
      </template>
    </q-table>

    <!-- Erstellen-Dialog -->
    <q-dialog v-model="createOpen" persistent>
      <q-card style="min-width: 400px">
        <q-card-section class="text-h6">Neue Abteilung anlegen</q-card-section>
        <q-separator />
        <q-card-section class="q-gutter-sm">
          <q-input v-model="form.name" label="Name *" outlined autofocus
            :rules="[(v) => !!v || 'Pflichtfeld']" />
          <q-input v-model="form.kuerzel" label="Kürzel" outlined />
          <q-input v-model="form.beschreibung" label="Beschreibung" outlined type="textarea"
            rows="3" />
          <q-input v-model.number="form.kostenstelle" label="Kostenstelle (Fibu)" outlined
            type="number" clearable hint="für den Fibu-Export der Beiträge dieser Abteilung" />
          <div v-if="formError" class="text-negative">{{ formError }}</div>
        </q-card-section>
        <q-separator />
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn label="Anlegen" color="primary" unelevated :loading="saving" @click="onCreate" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Bearbeiten-Dialog -->
    <q-dialog v-model="editOpen" persistent>
      <q-card style="min-width: 400px">
        <q-card-section class="text-h6">Abteilung bearbeiten</q-card-section>
        <q-separator />
        <q-card-section class="q-gutter-sm">
          <q-input v-model="form.name" label="Name *" outlined
            :rules="[(v) => !!v || 'Pflichtfeld']" />
          <q-input v-model="form.kuerzel" label="Kürzel" outlined />
          <q-input v-model="form.beschreibung" label="Beschreibung" outlined type="textarea"
            rows="3" />
          <q-input v-model.number="form.kostenstelle" label="Kostenstelle (Fibu)" outlined
            type="number" clearable hint="für den Fibu-Export der Beiträge dieser Abteilung" />
          <div v-if="formError" class="text-negative">{{ formError }}</div>
        </q-card-section>
        <q-separator />
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn label="Speichern" color="primary" unelevated :loading="saving" @click="onEdit" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Papierkorb-Dialog -->
    <q-dialog v-model="trashOpen" full-width>
      <q-card>
        <q-card-section class="row items-center">
          <div class="text-h6">Gelöschte Abteilungen</div>
          <q-space />
          <q-btn flat round icon="close" v-close-popup />
        </q-card-section>
        <q-separator />
        <q-card-section>
          <div v-if="deleted.length === 0" class="text-grey text-center q-py-lg">
            Keine gelöschten Abteilungen vorhanden.
          </div>
          <q-table
            v-else
            :rows="deleted"
            :columns="deletedColumns"
            row-key="id"
            flat
            hide-bottom
          >
            <template #body-cell-actions="props">
              <q-td :props="props">
                <q-btn
                  flat dense round icon="restore" color="positive" size="sm"
                  title="Wiederherstellen"
                  @click="confirmRestore(props.row)"
                />
              </q-td>
            </template>
          </q-table>
        </q-card-section>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { useAuthStore } from 'src/stores/auth'
import { formatDateTime } from 'src/utils/datetime'

const $q = useQuasar()
const auth = useAuthStore()

const abteilungen = ref([])
const deleted = ref([])
const loading = ref(false)
const filter = ref('')
const saving = ref(false)
const formError = ref('')

const createOpen = ref(false)
const editOpen = ref(false)
const trashOpen = ref(false)

const emptyForm = () => ({ name: '', kuerzel: '', beschreibung: '', kostenstelle: null, id: null, version: null })
const form = ref(emptyForm())

const columns = [
  { name: 'name',         label: 'Name',         field: 'name',         sortable: true, align: 'left' },
  { name: 'kuerzel',      label: 'Kürzel',       field: 'kuerzel',      align: 'left' },
  { name: 'beschreibung', label: 'Beschreibung', field: 'beschreibung', align: 'left' },
  { name: 'actions',      label: '',             field: 'actions',      align: 'right' },
]

const deletedColumns = [
  { name: 'name',       label: 'Name',          field: 'name',       sortable: true, align: 'left' },
  { name: 'kuerzel',    label: 'Kürzel',        field: 'kuerzel',    align: 'left' },
  { name: 'deleted_at', label: 'Gelöscht am',   field: 'deleted_at', align: 'left', format: v => formatDateTime(v) },
  { name: 'deleted_by', label: 'Gelöscht von',  field: 'deleted_by', align: 'left' },
  { name: 'actions',    label: '',              field: 'actions',    align: 'right' },
]

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/api/abteilungen/')
    abteilungen.value = data
  } catch {
    $q.notify({ type: 'negative', message: 'Fehler beim Laden' })
  } finally {
    loading.value = false
  }
}

async function loadDeleted() {
  const { data } = await api.get('/api/abteilungen/deleted')
  deleted.value = data
}

// Papierkorb beim Öffnen laden
watch(trashOpen, (open) => { if (open) loadDeleted() })

// --- Erstellen ---
function openCreateDialog() {
  form.value = emptyForm()
  formError.value = ''
  createOpen.value = true
}

async function onCreate() {
  formError.value = ''
  saving.value = true
  try {
    await api.post('/api/abteilungen/', {
      name: form.value.name,
      kuerzel: form.value.kuerzel || null,
      beschreibung: form.value.beschreibung || null,
      kostenstelle: form.value.kostenstelle ?? null,
    })
    $q.notify({ type: 'positive', message: 'Abteilung angelegt' })
    createOpen.value = false
    await load()
  } catch (e) {
    formError.value = e.response?.data?.detail || 'Fehler beim Anlegen'
  } finally {
    saving.value = false
  }
}

// --- Bearbeiten ---
function openEditDialog(row) {
  form.value = { ...row }
  formError.value = ''
  editOpen.value = true
}

async function onEdit() {
  formError.value = ''
  saving.value = true
  try {
    await api.put(`/api/abteilungen/${form.value.id}`, {
      name: form.value.name,
      kuerzel: form.value.kuerzel || null,
      beschreibung: form.value.beschreibung || null,
      kostenstelle: form.value.kostenstelle ?? null,
      expected_version: form.value.version,
    })
    $q.notify({ type: 'positive', message: 'Gespeichert' })
    editOpen.value = false
    await load()
  } catch (e) {
    formError.value = e.response?.data?.detail || 'Fehler beim Speichern'
  } finally {
    saving.value = false
  }
}

// --- Löschen ---
function confirmDelete(row) {
  $q.dialog({
    title: 'Abteilung löschen',
    message: `"${row.name}" wirklich löschen? Gelöschte Abteilungen können wiederhergestellt werden.`,
    cancel: true,
    persistent: true,
  }).onOk(async () => {
    try {
      await api.delete(`/api/abteilungen/${row.id}`)
      $q.notify({ type: 'positive', message: 'Gelöscht' })
      await load()
    } catch (e) {
      $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Löschen' })
    }
  })
}

// --- Wiederherstellen ---
function confirmRestore(row) {
  $q.dialog({
    title: 'Wiederherstellen',
    message: `"${row.name}" wiederherstellen?`,
    cancel: true,
  }).onOk(async () => {
    try {
      await api.post(`/api/abteilungen/${row.id}/restore`)
      $q.notify({ type: 'positive', message: 'Wiederhergestellt' })
      await Promise.all([load(), loadDeleted()])
      if (deleted.value.length === 0) trashOpen.value = false
    } catch (e) {
      $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' })
    }
  })
}

onMounted(load)
</script>
