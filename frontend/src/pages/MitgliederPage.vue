<template>
  <q-page padding>
    <div class="row items-center q-mb-md">
      <div class="text-h5 col">Mitglieder</div>
      <q-btn
        v-if="auth.hasPermission('mitglieder.write')"
        label="Neu"
        icon="add"
        color="primary"
        unelevated
        @click="openCreateDialog"
      />
    </div>

    <q-table
      :rows="mitglieder"
      :columns="columns"
      row-key="id"
      :loading="loading"
      :filter="filter"
      flat
      bordered
    >
      <template #top-right>
        <q-input v-model="filter" placeholder="Suchen…" dense outlined clearable>
          <template #append>
            <q-icon name="search" />
          </template>
        </q-input>
      </template>

      <template #body-cell-status="props">
        <q-td :props="props">
          <q-badge :color="props.value === 'aktiv' ? 'positive' : 'grey'">
            {{ props.value }}
          </q-badge>
        </q-td>
      </template>

      <template #body-cell-actions="props">
        <q-td :props="props" class="q-gutter-xs">
          <q-btn
            flat dense round icon="edit" color="primary" size="sm"
            @click="openEditDialog(props.row)"
          />
          <q-btn
            v-if="auth.hasPermission('mitglieder.delete')"
            flat dense round icon="delete" color="negative" size="sm"
            @click="confirmDelete(props.row)"
          />
        </q-td>
      </template>
    </q-table>

    <!-- Erstellen / Bearbeiten Dialog -->
    <q-dialog v-model="dialogOpen" persistent>
      <q-card style="min-width: 480px; max-width: 600px">
        <q-card-section class="text-h6">
          {{ editingId ? 'Mitglied bearbeiten' : 'Neues Mitglied' }}
        </q-card-section>
        <q-separator />
        <q-card-section class="q-gutter-sm scroll" style="max-height: 60vh">
          <div class="row q-gutter-sm">
            <q-input v-model="form.vorname" label="Vorname *" outlined class="col" :rules="[(v) => !!v || 'Pflichtfeld']" />
            <q-input v-model="form.nachname" label="Nachname *" outlined class="col" :rules="[(v) => !!v || 'Pflichtfeld']" />
          </div>
          <div class="row q-gutter-sm">
            <q-input v-model="form.mitgliedsnummer" label="Mitgliedsnr." outlined type="number" class="col" />
            <q-input v-model="form.geburtsdatum" label="Geburtsdatum" outlined mask="####-##-##" placeholder="JJJJ-MM-TT" class="col" />
          </div>
          <q-input v-model="form.email" label="E-Mail" outlined type="email" />
          <q-input v-model="form.telefon" label="Telefon" outlined />
          <div class="row q-gutter-sm">
            <q-input v-model="form.strasse" label="Straße" outlined class="col-8" />
            <q-input v-model="form.plz" label="PLZ" outlined class="col" />
          </div>
          <div class="row q-gutter-sm">
            <q-input v-model="form.ort" label="Ort" outlined class="col" />
            <q-input v-model="form.land" label="Land" outlined class="col" />
          </div>
          <div class="row q-gutter-sm">
            <q-input v-model="form.eintrittsdatum" label="Eintrittsdatum" outlined mask="####-##-##" placeholder="JJJJ-MM-TT" class="col" />
            <q-select
              v-model="form.status"
              label="Status"
              outlined
              class="col"
              :options="['aktiv', 'passiv', 'ausgetreten']"
            />
          </div>
        </q-card-section>
        <q-separator />
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn label="Speichern" color="primary" unelevated :loading="saving" @click="onSave" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { useAuthStore } from 'src/stores/auth'

const $q = useQuasar()
const auth = useAuthStore()

const mitglieder = ref([])
const loading = ref(false)
const filter = ref('')
const dialogOpen = ref(false)
const saving = ref(false)
const editingId = ref(null)

const emptyForm = () => ({
  vorname: '', nachname: '', mitgliedsnummer: null, geburtsdatum: null,
  email: null, telefon: null, strasse: null, plz: null, ort: null, land: null,
  eintrittsdatum: null, austrittsdatum: null, status: 'aktiv', zahlungsart: '',
  iban: null, bic: null, kontoinhaber: null, abgerechnet_bis: null,
})

const form = ref(emptyForm())

const columns = [
  { name: 'mitgliedsnummer', label: 'Nr.', field: 'mitgliedsnummer', sortable: true, align: 'left' },
  { name: 'nachname', label: 'Nachname', field: 'nachname', sortable: true, align: 'left' },
  { name: 'vorname', label: 'Vorname', field: 'vorname', sortable: true, align: 'left' },
  { name: 'email', label: 'E-Mail', field: 'email', align: 'left' },
  { name: 'status', label: 'Status', field: 'status', sortable: true, align: 'left' },
  { name: 'actions', label: '', field: 'actions', align: 'right' },
]

async function loadMitglieder() {
  loading.value = true
  try {
    const { data } = await api.get('/api/mitglieder/')
    mitglieder.value = data
  } catch (e) {
    $q.notify({ type: 'negative', message: 'Fehler beim Laden' })
  } finally {
    loading.value = false
  }
}

function openCreateDialog() {
  editingId.value = null
  form.value = emptyForm()
  dialogOpen.value = true
}

function openEditDialog(row) {
  editingId.value = row.id
  form.value = { ...row }
  dialogOpen.value = true
}

async function onSave() {
  saving.value = true
  try {
    if (editingId.value) {
      await api.put(`/api/mitglieder/${editingId.value}`, form.value)
    } else {
      await api.post('/api/mitglieder/', form.value)
    }
    $q.notify({ type: 'positive', message: 'Gespeichert' })
    dialogOpen.value = false
    await loadMitglieder()
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Speichern' })
  } finally {
    saving.value = false
  }
}

function confirmDelete(row) {
  $q.dialog({
    title: 'Mitglied löschen',
    message: `${row.vorname} ${row.nachname} wirklich löschen?`,
    cancel: true,
    persistent: true,
  }).onOk(async () => {
    try {
      await api.delete(`/api/mitglieder/${row.id}`)
      $q.notify({ type: 'positive', message: 'Gelöscht' })
      await loadMitglieder()
    } catch (e) {
      $q.notify({ type: 'negative', message: 'Fehler beim Löschen' })
    }
  })
}

onMounted(loadMitglieder)
</script>
