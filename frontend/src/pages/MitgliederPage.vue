<template>
  <q-page padding>
    <div class="row items-center q-mb-md">
      <div class="text-h5 col">Mitglieder</div>
      <q-btn
        v-if="auth.hasPermission('personen.write')"
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
          >
            <q-tooltip>Bearbeiten</q-tooltip>
          </q-btn>
          <q-btn
            flat dense round icon="group" color="secondary" size="sm"
            @click="openAbteilungenDialog(props.row)"
          >
            <q-tooltip>Abteilungen</q-tooltip>
          </q-btn>
          <q-btn
            flat dense round icon="badge" color="teal" size="sm"
            @click="openFunktionenDialog(props.row)"
          >
            <q-tooltip>Funktionen</q-tooltip>
          </q-btn>
          <q-btn
            v-if="auth.hasPermission('personen.delete')"
            flat dense round icon="delete" color="negative" size="sm"
            @click="confirmDelete(props.row)"
          >
            <q-tooltip>Löschen</q-tooltip>
          </q-btn>
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

    <!-- Abteilungen-Zuordnungs-Dialog -->
    <q-dialog v-model="abteilungenDialogOpen" persistent>
      <q-card style="min-width: 560px; max-width: 700px">
        <q-card-section class="row items-center">
          <div class="text-h6 col">
            Abteilungen –
            <span class="text-weight-regular">{{ aktivMitglied?.vorname }} {{ aktivMitglied?.nachname }}</span>
          </div>
          <q-btn
            v-if="auth.hasPermission('personen.write')"
            label="Hinzufügen"
            icon="add"
            color="primary"
            unelevated
            size="sm"
            @click="openZuordnungForm(null)"
          />
        </q-card-section>
        <q-separator />

        <q-card-section style="max-height: 50vh; overflow-y: auto">
          <q-inner-loading :showing="abteilungenLoading" />
          <div v-if="!abteilungenLoading && zuordnungen.length === 0" class="text-grey text-center q-py-md">
            Keine Abteilungszuordnungen vorhanden
          </div>
          <q-list separator>
            <q-item v-for="z in zuordnungen" :key="z.id">
              <q-item-section>
                <q-item-label>
                  {{ z.abteilung_name }}
                  <q-badge class="q-ml-sm" :color="statusColor(z.status)">{{ z.status }}</q-badge>
                </q-item-label>
                <q-item-label caption>
                  <span v-if="z.von">ab {{ z.von }}</span>
                  <span v-if="z.von && z.bis"> · </span>
                  <span v-if="z.bis">bis {{ z.bis }}</span>
                  <span v-if="!z.von && !z.bis">Kein Zeitraum angegeben</span>
                </q-item-label>
              </q-item-section>
              <q-item-section side>
                <div class="q-gutter-xs">
                  <q-btn
                    v-if="auth.hasPermission('personen.write')"
                    flat dense round icon="edit" color="primary" size="sm"
                    @click="openZuordnungForm(z)"
                  />
                  <q-btn
                    v-if="auth.hasPermission('personen.delete')"
                    flat dense round icon="delete" color="negative" size="sm"
                    @click="confirmDeleteZuordnung(z)"
                  />
                </div>
              </q-item-section>
            </q-item>
          </q-list>
        </q-card-section>

        <q-separator />
        <q-card-actions align="right">
          <q-btn flat label="Schließen" v-close-popup />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Zuordnung anlegen / bearbeiten -->
    <q-dialog v-model="zuordnungFormOpen" persistent>
      <q-card style="min-width: 400px">
        <q-card-section class="text-h6">
          {{ editingZuordnungId ? 'Zuordnung bearbeiten' : 'Neue Zuordnung' }}
        </q-card-section>
        <q-separator />
        <q-card-section class="q-gutter-sm">
          <q-select
            v-if="!editingZuordnungId"
            v-model="zuordnungForm.abteilung_id"
            label="Abteilung *"
            outlined
            :options="abteilungOptions"
            option-value="id"
            option-label="name"
            emit-value
            map-options
            :rules="[(v) => !!v || 'Pflichtfeld']"
          />
          <q-select
            v-model="zuordnungForm.status"
            label="Status *"
            outlined
            :options="statusOptionen"
          />
          <div class="row q-gutter-sm">
            <q-input v-model="zuordnungForm.von" label="Von" outlined mask="####-##-##" placeholder="JJJJ-MM-TT" class="col" clearable />
            <q-input v-model="zuordnungForm.bis" label="Bis" outlined mask="####-##-##" placeholder="JJJJ-MM-TT" class="col" clearable />
          </div>
        </q-card-section>
        <q-separator />
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn label="Speichern" color="primary" unelevated :loading="zuordnungSaving" @click="onSaveZuordnung" />
        </q-card-actions>
      </q-card>
    </q-dialog>
    <!-- Funktionen-Dialog -->
    <q-dialog v-model="funktionenDialogOpen" persistent>
      <q-card style="min-width: 560px; max-width: 700px">
        <q-card-section class="row items-center">
          <div class="text-h6 col">
            Funktionen –
            <span class="text-weight-regular">{{ aktivMitglied?.vorname }} {{ aktivMitglied?.nachname }}</span>
          </div>
          <q-btn
            v-if="auth.hasPermission('personen.write')"
            label="Hinzufügen"
            icon="add"
            color="primary"
            unelevated
            size="sm"
            @click="openFunktionForm(null)"
          />
        </q-card-section>
        <q-separator />

        <q-card-section style="max-height: 50vh; overflow-y: auto">
          <q-inner-loading :showing="funktionenLoading" />
          <div v-if="!funktionenLoading && funktionen.length === 0" class="text-grey text-center q-py-md">
            Keine Funktionen zugeordnet
          </div>
          <q-list separator>
            <q-item v-for="f in funktionen" :key="f.id">
              <q-item-section>
                <q-item-label>
                  {{ funktionLabel(f.funktion) }}
                  <q-badge class="q-ml-sm" color="teal">{{ f.abteilung_name ?? 'Verein' }}</q-badge>
                </q-item-label>
                <q-item-label caption>
                  <span v-if="f.von">ab {{ f.von }}</span>
                  <span v-if="f.von && f.bis"> · </span>
                  <span v-if="f.bis">bis {{ f.bis }}</span>
                  <span v-if="!f.von && !f.bis">Kein Zeitraum angegeben</span>
                </q-item-label>
              </q-item-section>
              <q-item-section side>
                <div class="q-gutter-xs">
                  <q-btn
                    v-if="auth.hasPermission('personen.write')"
                    flat dense round icon="edit" color="primary" size="sm"
                    @click="openFunktionForm(f)"
                  />
                  <q-btn
                    v-if="auth.hasPermission('personen.delete')"
                    flat dense round icon="delete" color="negative" size="sm"
                    @click="confirmDeleteFunktion(f)"
                  />
                </div>
              </q-item-section>
            </q-item>
          </q-list>
        </q-card-section>

        <q-separator />
        <q-card-actions align="right">
          <q-btn flat label="Schließen" v-close-popup />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Funktion anlegen / bearbeiten -->
    <q-dialog v-model="funktionFormOpen" persistent>
      <q-card style="min-width: 400px">
        <q-card-section class="text-h6">
          {{ editingFunktionId ? 'Funktion bearbeiten' : 'Neue Funktion' }}
        </q-card-section>
        <q-separator />
        <q-card-section class="q-gutter-sm">
          <q-select
            v-model="funktionForm.funktion"
            label="Funktion *"
            outlined
            :options="funktionOptionen"
            emit-value
            map-options
            :rules="[(v) => !!v || 'Pflichtfeld']"
          />
          <q-select
            v-model="funktionForm.abteilung_id"
            label="Abteilung"
            outlined
            :options="abteilungOptions"
            option-value="id"
            option-label="name"
            emit-value
            map-options
            clearable
          />
          <div class="row q-gutter-sm">
            <q-input v-model="funktionForm.von" label="Von" outlined mask="####-##-##" placeholder="JJJJ-MM-TT" class="col" clearable />
            <q-input v-model="funktionForm.bis" label="Bis" outlined mask="####-##-##" placeholder="JJJJ-MM-TT" class="col" clearable />
          </div>
        </q-card-section>
        <q-separator />
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn label="Speichern" color="primary" unelevated :loading="funktionSaving" @click="onSaveFunktion" />
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

// Abteilungen-Dialog
const abteilungenDialogOpen = ref(false)
const abteilungenLoading = ref(false)
const aktivMitglied = ref(null)
const zuordnungen = ref([])
const abteilungOptions = ref([])

// Zuordnung-Formular
const zuordnungFormOpen = ref(false)
const zuordnungSaving = ref(false)
const editingZuordnungId = ref(null)
const editingZuordnungVersion = ref(null)

const statusOptionen = ['aktiv', 'passiv', 'trainer', 'vorstand', 'ehrenmitglied']

const funktionOptionen = [
  { label: 'Schiedsrichter',  value: 'schiedsrichter' },
  { label: 'Übungsleiter',    value: 'uebungsleiter' },
  { label: 'Abteilungsleiter', value: 'abteilungsleiter' },
]

function funktionLabel(f) {
  return { schiedsrichter: 'Schiedsrichter', uebungsleiter: 'Übungsleiter', abteilungsleiter: 'Abteilungsleiter' }[f] ?? f
}

// Funktionen-Dialog
const funktionenDialogOpen = ref(false)
const funktionenLoading = ref(false)
const funktionen = ref([])

// Funktion-Formular
const funktionFormOpen = ref(false)
const funktionSaving = ref(false)
const editingFunktionId = ref(null)
const editingFunktionVersion = ref(null)

const emptyFunktionForm = () => ({ funktion: null, abteilung_id: null, von: null, bis: null })
const funktionForm = ref(emptyFunktionForm())

const emptyZuordnungForm = () => ({ abteilung_id: null, status: 'aktiv', von: null, bis: null })
const zuordnungForm = ref(emptyZuordnungForm())

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

function statusColor(s) {
  return { aktiv: 'positive', passiv: 'grey', trainer: 'blue', vorstand: 'purple', ehrenmitglied: 'amber-8' }[s] ?? 'grey'
}

async function loadMitglieder() {
  loading.value = true
  try {
    const { data } = await api.get('/api/mitglieder/')
    mitglieder.value = data
  } catch {
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
    } catch {
      $q.notify({ type: 'negative', message: 'Fehler beim Löschen' })
    }
  })
}

// --- Abteilungen-Dialog ---

async function openAbteilungenDialog(mitglied) {
  aktivMitglied.value = mitglied
  abteilungenDialogOpen.value = true
  await loadZuordnungen()
  await loadAbteilungOptions()
}

async function loadZuordnungen() {
  abteilungenLoading.value = true
  try {
    const { data } = await api.get(`/api/mitglieder/${aktivMitglied.value.id}/abteilungen`)
    zuordnungen.value = data
  } catch {
    $q.notify({ type: 'negative', message: 'Fehler beim Laden der Zuordnungen' })
  } finally {
    abteilungenLoading.value = false
  }
}

async function loadAbteilungOptions() {
  try {
    const { data } = await api.get('/api/abteilungen/')
    abteilungOptions.value = data
  } catch { /* ignore */ }
}

function openZuordnungForm(zuordnung) {
  if (zuordnung) {
    editingZuordnungId.value = zuordnung.id
    editingZuordnungVersion.value = zuordnung.version
    zuordnungForm.value = { abteilung_id: zuordnung.abteilung_id, status: zuordnung.status, von: zuordnung.von, bis: zuordnung.bis }
  } else {
    editingZuordnungId.value = null
    editingZuordnungVersion.value = null
    zuordnungForm.value = emptyZuordnungForm()
  }
  zuordnungFormOpen.value = true
}

async function onSaveZuordnung() {
  zuordnungSaving.value = true
  try {
    const mitgliedId = aktivMitglied.value.id
    if (editingZuordnungId.value) {
      await api.put(`/api/mitglieder/${mitgliedId}/abteilungen/${editingZuordnungId.value}`, {
        ...zuordnungForm.value,
        expected_version: editingZuordnungVersion.value,
      })
    } else {
      await api.post(`/api/mitglieder/${mitgliedId}/abteilungen`, zuordnungForm.value)
    }
    $q.notify({ type: 'positive', message: 'Gespeichert' })
    zuordnungFormOpen.value = false
    await loadZuordnungen()
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Speichern' })
  } finally {
    zuordnungSaving.value = false
  }
}

function confirmDeleteZuordnung(zuordnung) {
  $q.dialog({
    title: 'Zuordnung entfernen',
    message: `Zuordnung zu „${zuordnung.abteilung_name}" wirklich entfernen?`,
    cancel: true,
    persistent: true,
  }).onOk(async () => {
    try {
      await api.delete(`/api/mitglieder/${aktivMitglied.value.id}/abteilungen/${zuordnung.id}`)
      $q.notify({ type: 'positive', message: 'Zuordnung entfernt' })
      await loadZuordnungen()
    } catch {
      $q.notify({ type: 'negative', message: 'Fehler beim Löschen' })
    }
  })
}

// --- Funktionen-Dialog ---

async function openFunktionenDialog(mitglied) {
  aktivMitglied.value = mitglied
  funktionenDialogOpen.value = true
  await loadFunktionen()
  await loadAbteilungOptions()
}

async function loadFunktionen() {
  funktionenLoading.value = true
  try {
    const { data } = await api.get(`/api/mitglieder/${aktivMitglied.value.id}/funktionen`)
    funktionen.value = data
  } catch {
    $q.notify({ type: 'negative', message: 'Fehler beim Laden der Funktionen' })
  } finally {
    funktionenLoading.value = false
  }
}

function openFunktionForm(funktion) {
  if (funktion) {
    editingFunktionId.value = funktion.id
    editingFunktionVersion.value = funktion.version
    funktionForm.value = { funktion: funktion.funktion, abteilung_id: funktion.abteilung_id, von: funktion.von, bis: funktion.bis }
  } else {
    editingFunktionId.value = null
    editingFunktionVersion.value = null
    funktionForm.value = emptyFunktionForm()
  }
  funktionFormOpen.value = true
}

async function onSaveFunktion() {
  funktionSaving.value = true
  try {
    const mitgliedId = aktivMitglied.value.id
    if (editingFunktionId.value) {
      await api.put(`/api/mitglieder/${mitgliedId}/funktionen/${editingFunktionId.value}`, {
        ...funktionForm.value,
        expected_version: editingFunktionVersion.value,
      })
    } else {
      await api.post(`/api/mitglieder/${mitgliedId}/funktionen`, funktionForm.value)
    }
    $q.notify({ type: 'positive', message: 'Gespeichert' })
    funktionFormOpen.value = false
    await loadFunktionen()
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Speichern' })
  } finally {
    funktionSaving.value = false
  }
}

function confirmDeleteFunktion(funktion) {
  $q.dialog({
    title: 'Funktion entfernen',
    message: `Funktion „${funktionLabel(funktion.funktion)}" wirklich entfernen?`,
    cancel: true,
    persistent: true,
  }).onOk(async () => {
    try {
      await api.delete(`/api/mitglieder/${aktivMitglied.value.id}/funktionen/${funktion.id}`)
      $q.notify({ type: 'positive', message: 'Funktion entfernt' })
      await loadFunktionen()
    } catch {
      $q.notify({ type: 'negative', message: 'Fehler beim Löschen' })
    }
  })
}

onMounted(loadMitglieder)
</script>
