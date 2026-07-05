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

    <!-- Kategorien -->
    <q-card flat bordered class="q-mt-lg">
      <q-card-section class="row items-center">
        <div class="text-h6 col">Kategorien</div>
        <q-btn label="Neue Kategorie" icon="add" color="primary" unelevated dense @click="openCreateKategorie" />
      </q-card-section>
      <q-separator />
      <q-card-section class="q-pa-none">
        <q-table
          :rows="kategorien"
          :columns="kategorieColumns"
          row-key="id"
          :loading="kategorienLoading"
          flat
          :pagination="{ rowsPerPage: 0 }"
          hide-bottom
          no-data-label="Noch keine Kategorien angelegt."
        >
          <template #body-cell-geltungsbereich="props">
            <q-td :props="props">
              <q-chip v-if="props.row.ist_allgemein" dense square color="primary" text-color="white" icon="public">
                Alle Kassen
              </q-chip>
              <q-chip v-else dense square color="grey-3" text-color="grey-9" icon="account_balance_wallet">
                {{ props.row.kasse_name }}
              </q-chip>
            </q-td>
          </template>
          <template #body-cell-zaehlung="props">
            <q-td :props="props">
              <q-icon v-if="props.row.loest_zaehlung_aus" name="pin" color="primary" size="20px">
                <q-tooltip>Betrag per Kassenzählung (Zählung − Altbestand)</q-tooltip>
              </q-icon>
              <span v-else class="text-grey-5">–</span>
            </q-td>
          </template>
          <template #body-cell-actions="props">
            <q-td :props="props">
              <q-btn flat dense round icon="edit" color="grey-7" size="sm" @click="openEditKategorie(props.row)">
                <q-tooltip>Bearbeiten</q-tooltip>
              </q-btn>
              <q-btn flat dense round icon="delete" color="negative" size="sm" @click="confirmDeleteKategorie(props.row)">
                <q-tooltip>Löschen</q-tooltip>
              </q-btn>
            </q-td>
          </template>
        </q-table>
      </q-card-section>
    </q-card>

    <!-- Kategorie anlegen / bearbeiten -->
    <q-dialog v-model="kategorieDialogOpen" persistent>
      <q-card style="min-width: 420px">
        <q-card-section class="text-h6">
          {{ editingKategorieId ? 'Kategorie bearbeiten' : 'Neue Kategorie' }}
        </q-card-section>
        <q-separator />
        <q-card-section class="q-gutter-sm">
          <q-input v-model="kategorieForm.name" label="Name *" outlined :rules="[v => !!v || 'Pflichtfeld']" />
          <q-select
            v-model="kategorieForm.kasse_id"
            :options="geltungsbereichOptionen"
            label="Geltungsbereich"
            outlined
            emit-value
            map-options
            hint="„Alle Kassen“ = allgemein; sonst nur bei der gewählten Kasse wählbar."
          />
          <q-toggle
            v-model="kategorieForm.loest_zaehlung_aus"
            label="Betrag per Zählung"
            color="primary"
          />
          <div class="text-caption text-grey-7 q-pl-sm" style="margin-top: -8px">
            Statt eines Betrags wird im Buchungsdialog die Kasse gezählt; gebucht wird
            Zählung − Altbestand (z. B. Imbiss-Tageseinnahmen).
          </div>
          <q-input
            v-model="kategorieForm.gegenkonto"
            label="Gegenkonto (Fibu, FBASC Feld 01)"
            outlined
            hint="Leer = Kategorie ist nicht exportierbar."
          />
          <q-input
            v-model.number="kategorieForm.kostentraeger"
            label="Kostenträger (Fibu, FBASC Feld 08)"
            type="number"
            outlined
            hint="Leer = Default aus den Fibu-Einstellungen."
          />
        </q-card-section>
        <q-separator />
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn label="Speichern" color="primary" unelevated :loading="savingKategorie" @click="onSaveKategorie" />
        </q-card-actions>
      </q-card>
    </q-dialog>

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
          <q-select
            v-model="kasseForm.abteilung_id"
            :options="abteilungOptionen"
            label="Abteilung (liefert die Kostenstelle, FBASC Feld 07)"
            outlined
            emit-value
            map-options
            clearable
            hint="Leer = Verein-Kostenstelle aus den Fibu-Einstellungen."
          />
          <q-input
            v-model="kasseForm.sachkonto"
            label="Sachkonto (Fibu, FBASC Feld 00)"
            outlined
            hint="Leer = Kasse ist nicht exportierbar."
          />
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
import { usePageRefresh } from 'src/composables/useRefresh'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'

const $q = useQuasar()

const kassen = ref([])
const loading = ref(false)
const abteilungen = ref([])

const kasseDialogOpen = ref(false)
const saving = ref(false)
const editingKasseId = ref(null)
const editingKasseVersion = ref(null)
const anfangsbestandEuro = ref(0)
const kasseForm = ref({ name: '', beschreibung: '', abteilung_id: null, sachkonto: '' })

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

// --- Kategorien ---
const kategorien = ref([])
const kategorienLoading = ref(false)
const kategorieDialogOpen = ref(false)
const savingKategorie = ref(false)
const editingKategorieId = ref(null)
const editingKategorieVersion = ref(null)
const kategorieForm = ref({ name: '', kasse_id: null, loest_zaehlung_aus: false, gegenkonto: '', kostentraeger: null })

const kategorieColumns = [
  { name: 'name', label: 'Name', field: 'name', align: 'left' },
  { name: 'geltungsbereich', label: 'Geltungsbereich', field: 'kasse_name', align: 'left' },
  { name: 'zaehlung', label: 'Zählung', field: 'loest_zaehlung_aus', align: 'center' },
  { name: 'actions', label: '', field: 'actions', align: 'right' },
]

const geltungsbereichOptionen = computed(() => [
  { label: 'Alle Kassen (allgemein)', value: null },
  ...kassen.value.map(k => ({ label: k.name, value: k.id })),
])

const abteilungOptionen = computed(() =>
  abteilungen.value.map(a => ({
    label: a.kostenstelle != null ? `${a.name} (KoSt ${a.kostenstelle})` : `${a.name} (keine KoSt hinterlegt)`,
    value: a.id,
  })),
)

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

async function loadAbteilungen() {
  try {
    const { data } = await api.get('/api/abteilungen/')
    abteilungen.value = data
  } catch { /* ignorieren – Selektor bleibt dann leer */ }
}

function openCreateDialog() {
  editingKasseId.value = null
  editingKasseVersion.value = null
  anfangsbestandEuro.value = 0
  kasseForm.value = { name: '', beschreibung: '', abteilung_id: null, sachkonto: '' }
  kasseDialogOpen.value = true
}

function openEditDialog(kasse) {
  editingKasseId.value = kasse.id
  editingKasseVersion.value = kasse.version
  anfangsbestandEuro.value = kasse.anfangsbestand_cent / 100
  kasseForm.value = {
    name: kasse.name,
    beschreibung: kasse.beschreibung || '',
    abteilung_id: kasse.abteilung_id ?? null,
    sachkonto: kasse.sachkonto || '',
  }
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
      abteilung_id: kasseForm.value.abteilung_id ?? null,
      sachkonto: kasseForm.value.sachkonto?.trim() || null,
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

// -----------------------------------------------------------------------
// Kategorien-Verwaltung
// -----------------------------------------------------------------------

async function loadKategorien() {
  kategorienLoading.value = true
  try {
    const { data } = await api.get('/api/kassen/kategorien')
    kategorien.value = data
  } catch {
    $q.notify({ type: 'negative', message: 'Fehler beim Laden der Kategorien.' })
  } finally {
    kategorienLoading.value = false
  }
}

function openCreateKategorie() {
  editingKategorieId.value = null
  editingKategorieVersion.value = null
  kategorieForm.value = { name: '', kasse_id: null, loest_zaehlung_aus: false, gegenkonto: '', kostentraeger: null }
  kategorieDialogOpen.value = true
}

function openEditKategorie(kat) {
  editingKategorieId.value = kat.id
  editingKategorieVersion.value = kat.version
  kategorieForm.value = { name: kat.name, kasse_id: kat.kasse_id, loest_zaehlung_aus: !!kat.loest_zaehlung_aus, gegenkonto: kat.gegenkonto || '', kostentraeger: kat.kostentraeger ?? null }
  kategorieDialogOpen.value = true
}

async function onSaveKategorie() {
  if (!kategorieForm.value.name.trim()) return
  savingKategorie.value = true
  try {
    const payload = {
      name: kategorieForm.value.name.trim(),
      kasse_id: kategorieForm.value.kasse_id ?? null,
      loest_zaehlung_aus: !!kategorieForm.value.loest_zaehlung_aus,
      gegenkonto: kategorieForm.value.gegenkonto?.trim() || null,
      kostentraeger: kategorieForm.value.kostentraeger ?? null,
    }
    if (editingKategorieId.value) {
      await api.put(`/api/kassen/kategorien/${editingKategorieId.value}`, {
        ...payload,
        expected_version: editingKategorieVersion.value,
      })
    } else {
      await api.post('/api/kassen/kategorien', payload)
    }
    $q.notify({ type: 'positive', message: 'Gespeichert.' })
    kategorieDialogOpen.value = false
    await loadKategorien()
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Speichern.' })
  } finally {
    savingKategorie.value = false
  }
}

function confirmDeleteKategorie(kat) {
  $q.dialog({
    title: 'Kategorie löschen',
    message: `Kategorie „${kat.name}" wirklich löschen? Bestehende Buchungen behalten ihren Text.`,
    cancel: true,
    persistent: true,
  }).onOk(async () => {
    try {
      await api.delete(`/api/kassen/kategorien/${kat.id}`)
      $q.notify({ type: 'positive', message: 'Kategorie gelöscht.' })
      await loadKategorien()
    } catch (e) {
      $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Löschen.' })
    }
  })
}

usePageRefresh(() => Promise.all([loadKassen(), loadKategorien(), loadAbteilungen()]))
onMounted(() => {
  loadKassen()
  loadKategorien()
  loadAbteilungen()
})
</script>
