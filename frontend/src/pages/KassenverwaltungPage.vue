<template>
  <q-page padding>
    <div class="row items-center q-mb-md">
      <div class="text-h5 col">Kassenverwaltung</div>
      <q-btn label="Neue Kasse" icon="add" color="primary" unelevated @click="openCreateDialog" />
    </div>

    <div v-if="loading" class="row justify-center q-py-xl">
      <q-spinner size="40px" color="primary" />
    </div>

    <div v-else-if="kassen.length === 0" class="text-center text-grey q-py-xl">
      <q-icon name="account_balance_wallet" size="48px" class="q-mb-sm" />
      <div>Noch keine Kassen angelegt.</div>
    </div>

    <div v-else class="row q-gutter-md">
      <q-card
        v-for="k in kassen"
        :key="k.id"
        class="col-12 col-sm-5 col-md-3"
        bordered
        flat
      >
        <q-card-section>
          <div class="text-h6">{{ k.name }}</div>
          <div v-if="k.beschreibung" class="text-caption text-grey q-mt-xs">{{ k.beschreibung }}</div>
          <div class="text-subtitle1 q-mt-sm" :class="k.bestand_cent < 0 ? 'text-negative' : 'text-positive'">
            {{ formatEuro(k.bestand_cent) }}
          </div>
          <div class="text-caption text-grey">Anfangsbestand: {{ formatEuro(k.anfangsbestand_cent) }}</div>
        </q-card-section>

        <q-separator />

        <q-card-actions>
          <q-btn flat label="Buchungen" color="primary"
            :to="{ name: 'kassenbuch-detail', params: { kasseId: k.id } }" />
          <q-space />
          <q-btn flat dense round icon="people" color="secondary" @click="openBerechtigungDialog(k)">
            <q-tooltip>Berechtigungen</q-tooltip>
          </q-btn>
          <q-btn flat dense round icon="edit" color="grey-7" @click="openEditDialog(k)">
            <q-tooltip>Bearbeiten</q-tooltip>
          </q-btn>
          <q-btn flat dense round icon="delete" color="negative" @click="confirmDelete(k)">
            <q-tooltip>Löschen</q-tooltip>
          </q-btn>
        </q-card-actions>
      </q-card>
    </div>

    <!-- Kasse anlegen / bearbeiten -->
    <q-dialog v-model="kasseDialogOpen" persistent>
      <q-card style="min-width: 420px">
        <q-card-section class="text-h6">
          {{ editingKasseId ? 'Kasse bearbeiten' : 'Neue Kasse' }}
        </q-card-section>
        <q-separator />
        <q-card-section class="q-gutter-sm">
          <q-input v-model="kasseForm.name" label="Name *" outlined :rules="[v => !!v || 'Pflichtfeld']" />
          <q-input v-model="kasseForm.beschreibung" label="Beschreibung" outlined />
          <q-input
            v-model.number="anfangsbestandEuro"
            label="Anfangsbestand (€)"
            outlined
            type="number"
            step="0.01"
            :disable="!!editingKasseId"
            :hint="editingKasseId ? 'Anfangsbestand kann nach dem Anlegen nicht geändert werden.' : ''"
          />
        </q-card-section>
        <q-separator />
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn label="Speichern" color="primary" unelevated :loading="saving" @click="onSaveKasse" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Berechtigungen verwalten -->
    <q-dialog v-model="berechtigungDialogOpen" persistent>
      <q-card style="min-width: 520px; max-width: 640px">
        <q-card-section class="row items-center">
          <div class="text-h6">Berechtigungen – {{ selectedKasse?.name }}</div>
          <q-space />
          <q-btn icon="close" flat round dense v-close-popup />
        </q-card-section>
        <q-separator />

        <q-card-section>
          <q-table
            :rows="berechtigungen"
            :columns="berechtigungColumns"
            row-key="user_id"
            :loading="berechtigungLoading"
            flat
            dense
            hide-bottom
            no-data-label="Noch keine Berechtigungen vergeben."
          >
            <template #body-cell-darf_lesen="props">
              <q-td :props="props">
                <q-checkbox
                  :model-value="props.row.darf_lesen"
                  @update:model-value="v => updateBerechtigung(props.row, 'darf_lesen', v)"
                />
              </q-td>
            </template>
            <template #body-cell-darf_schreiben="props">
              <q-td :props="props">
                <q-checkbox
                  :model-value="props.row.darf_schreiben"
                  @update:model-value="v => updateBerechtigung(props.row, 'darf_schreiben', v)"
                />
              </q-td>
            </template>
            <template #body-cell-darf_exportieren="props">
              <q-td :props="props">
                <q-checkbox
                  :model-value="props.row.darf_exportieren"
                  @update:model-value="v => updateBerechtigung(props.row, 'darf_exportieren', v)"
                />
              </q-td>
            </template>
            <template #body-cell-actions="props">
              <q-td :props="props">
                <q-btn flat dense round icon="delete" color="negative" size="sm"
                  @click="revokeBerechtigung(props.row)" />
              </q-td>
            </template>
          </q-table>
        </q-card-section>

        <q-separator />
        <q-card-section>
          <div class="text-subtitle2 q-mb-sm">Benutzer hinzufügen</div>
          <div class="row q-gutter-sm items-center">
            <q-select
              v-model="newBerechtigungUser"
              :options="verfuegbareUsers"
              option-label="username"
              option-value="id"
              label="Benutzer"
              outlined
              dense
              class="col"
            />
            <q-btn
              label="Hinzufügen"
              color="primary"
              unelevated
              dense
              :disable="!newBerechtigungUser"
              @click="addBerechtigung"
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

const $q = useQuasar()

const kassen = ref([])
const loading = ref(false)

const kasseDialogOpen = ref(false)
const saving = ref(false)
const editingKasseId = ref(null)
const editingKasseVersion = ref(null)
const anfangsbestandEuro = ref(0)
const kasseForm = ref({ name: '', beschreibung: '' })

const berechtigungDialogOpen = ref(false)
const berechtigungLoading = ref(false)
const selectedKasse = ref(null)
const berechtigungen = ref([])
const alleUsers = ref([])
const newBerechtigungUser = ref(null)

const berechtigungColumns = [
  { name: 'username', label: 'Benutzer', field: 'username', align: 'left' },
  { name: 'darf_lesen', label: 'Lesen', field: 'darf_lesen', align: 'center' },
  { name: 'darf_schreiben', label: 'Schreiben', field: 'darf_schreiben', align: 'center' },
  { name: 'darf_exportieren', label: 'Exportieren', field: 'darf_exportieren', align: 'center' },
  { name: 'actions', label: '', field: 'actions', align: 'right' },
]

const verfuegbareUsers = computed(() => {
  const bereitsVorhanden = new Set(berechtigungen.value.map(b => b.user_id))
  return alleUsers.value.filter(u => !bereitsVorhanden.has(u.id) && u.role !== 'admin')
})

function formatEuro(cent) {
  return new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR' }).format(cent / 100)
}

async function loadKassen() {
  loading.value = true
  try {
    const { data } = await api.get('/api/kassen/')
    kassen.value = data
  } catch {
    $q.notify({ type: 'negative', message: 'Fehler beim Laden der Kassen.' })
  } finally {
    loading.value = false
  }
}

function openCreateDialog() {
  editingKasseId.value = null
  editingKasseVersion.value = null
  anfangsbestandEuro.value = 0
  kasseForm.value = { name: '', beschreibung: '' }
  kasseDialogOpen.value = true
}

function openEditDialog(kasse) {
  editingKasseId.value = kasse.id
  editingKasseVersion.value = kasse.version
  anfangsbestandEuro.value = kasse.anfangsbestand_cent / 100
  kasseForm.value = { name: kasse.name, beschreibung: kasse.beschreibung || '' }
  kasseDialogOpen.value = true
}

async function onSaveKasse() {
  if (!kasseForm.value.name.trim()) return
  saving.value = true
  try {
    const payload = {
      name: kasseForm.value.name.trim(),
      beschreibung: kasseForm.value.beschreibung || null,
      anfangsbestand_cent: Math.round(anfangsbestandEuro.value * 100),
    }
    if (editingKasseId.value) {
      await api.put(`/api/kassen/${editingKasseId.value}`, {
        ...payload,
        expected_version: editingKasseVersion.value,
      })
    } else {
      await api.post('/api/kassen/', payload)
    }
    $q.notify({ type: 'positive', message: 'Gespeichert.' })
    kasseDialogOpen.value = false
    await loadKassen()
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Speichern.' })
  } finally {
    saving.value = false
  }
}

function confirmDelete(kasse) {
  $q.dialog({
    title: 'Kasse löschen',
    message: `Kasse „${kasse.name}" wirklich löschen? Dies ist nur möglich wenn keine aktiven Buchungen vorhanden sind.`,
    cancel: true,
    persistent: true,
  }).onOk(async () => {
    try {
      await api.delete(`/api/kassen/${kasse.id}`)
      $q.notify({ type: 'positive', message: 'Kasse gelöscht.' })
      await loadKassen()
    } catch (e) {
      $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Löschen.' })
    }
  })
}

async function openBerechtigungDialog(kasse) {
  selectedKasse.value = kasse
  berechtigungDialogOpen.value = true
  newBerechtigungUser.value = null
  await Promise.all([loadBerechtigungen(kasse.id), loadAlleUsers()])
}

async function loadBerechtigungen(kasseId) {
  berechtigungLoading.value = true
  try {
    const { data } = await api.get(`/api/kassen/${kasseId}/berechtigungen`)
    berechtigungen.value = data
  } catch {
    $q.notify({ type: 'negative', message: 'Fehler beim Laden der Berechtigungen.' })
  } finally {
    berechtigungLoading.value = false
  }
}

async function loadAlleUsers() {
  if (alleUsers.value.length > 0) return
  try {
    const { data } = await api.get('/api/users/')
    alleUsers.value = data.filter(u => u.active)
  } catch { /* ignorieren */ }
}

async function updateBerechtigung(row, field, value) {
  try {
    await api.put(`/api/kassen/${selectedKasse.value.id}/berechtigungen/${row.user_id}`, {
      darf_lesen: field === 'darf_lesen' ? value : row.darf_lesen,
      darf_schreiben: field === 'darf_schreiben' ? value : row.darf_schreiben,
      darf_exportieren: field === 'darf_exportieren' ? value : row.darf_exportieren,
    })
    row[field] = value
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler.' })
  }
}

async function addBerechtigung() {
  if (!newBerechtigungUser.value) return
  try {
    const { data } = await api.put(
      `/api/kassen/${selectedKasse.value.id}/berechtigungen/${newBerechtigungUser.value.id}`,
      { darf_lesen: true, darf_schreiben: false, darf_exportieren: false },
    )
    berechtigungen.value.push(data)
    newBerechtigungUser.value = null
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler.' })
  }
}

async function revokeBerechtigung(row) {
  try {
    await api.delete(`/api/kassen/${selectedKasse.value.id}/berechtigungen/${row.user_id}`)
    berechtigungen.value = berechtigungen.value.filter(b => b.user_id !== row.user_id)
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler.' })
  }
}

onMounted(loadKassen)
</script>
