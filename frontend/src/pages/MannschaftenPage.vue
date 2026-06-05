<template>
  <q-page class="q-pa-md">
    <div class="row items-center q-mb-md">
      <div class="text-h5">Mannschaften</div>
      <q-space />
      <q-btn v-if="auth.hasPermission('mannschaften.write')" color="primary" unelevated
        icon="add" label="Neue Mannschaft" :round="$q.screen.lt.sm" @click="openCreate" />
    </div>

    <q-inner-loading :showing="loading" />
    <div v-if="!loading && mannschaften.length === 0" class="text-grey text-center q-py-xl">
      Noch keine Mannschaften angelegt.
    </div>

    <div class="row q-col-gutter-md">
      <div v-for="m in mannschaften" :key="m.id" class="col-12 col-md-6 col-lg-4">
        <q-card flat bordered>
          <q-card-section class="q-pb-xs">
            <div class="row items-center">
              <div class="text-h6">{{ m.name }}</div>
              <q-space />
              <q-chip dense size="sm" color="purple" text-color="white">{{ m.abteilung_name }}</q-chip>
            </div>
            <div class="text-caption text-grey-7">
              <span v-if="m.saison">Saison {{ m.saison }}</span>
              <span v-if="m.beschreibung"> · {{ m.beschreibung }}</span>
            </div>
          </q-card-section>
          <q-separator />
          <q-card-actions class="q-px-sm q-py-xs">
            <q-btn flat dense round icon="groups" color="cyan-8" size="sm" @click="openKader(m)">
              <q-tooltip>Kader</q-tooltip>
            </q-btn>
            <q-btn v-if="auth.hasPermission('mannschaften.write')" flat dense round icon="edit"
              color="primary" size="sm" @click="openEdit(m)">
              <q-tooltip>Bearbeiten</q-tooltip>
            </q-btn>
            <q-space />
            <q-btn v-if="auth.hasPermission('mannschaften.delete')" flat dense round icon="delete"
              color="negative" size="sm" @click="confirmDelete(m)">
              <q-tooltip>Löschen</q-tooltip>
            </q-btn>
          </q-card-actions>
        </q-card>
      </div>
    </div>

    <!-- Mannschaft anlegen/bearbeiten -->
    <q-dialog v-model="formOpen" persistent :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card :style="$q.screen.lt.sm ? 'width:100%;border-radius:16px 16px 0 0' : 'min-width:420px'">
        <q-card-section class="text-h6">{{ form.id ? 'Mannschaft bearbeiten' : 'Neue Mannschaft' }}</q-card-section>
        <q-card-section class="q-gutter-sm q-pt-none">
          <q-select v-model="form.abteilung_id" :options="abteilungen" option-value="id" option-label="name"
            emit-value map-options label="Abteilung *" outlined dense />
          <q-input v-model="form.name" label="Name *" outlined dense />
          <q-input v-model="form.saison" label="Saison (z.B. 2026/27)" outlined dense />
          <q-input v-model="form.beschreibung" label="Beschreibung" outlined dense type="textarea" autogrow />
          <div v-if="formError" class="text-negative text-caption">{{ formError }}</div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn unelevated color="primary" :label="form.id ? 'Speichern' : 'Anlegen'"
            :loading="saving" @click="save" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Kader -->
    <q-dialog v-model="kaderOpen" :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card :style="$q.screen.lt.sm ? 'width:100%;border-radius:16px 16px 0 0' : 'min-width:520px'">
        <q-card-section class="row items-center q-pb-none">
          <div class="text-h6">Kader</div>
          <div v-if="aktivMannschaft" class="text-caption text-grey q-ml-sm">{{ aktivMannschaft.name }}</div>
          <q-space />
          <q-btn icon="close" flat round dense v-close-popup />
        </q-card-section>
        <q-card-section>
          <q-inner-loading :showing="kaderLoading" />
          <div v-if="!kaderLoading && kader.length === 0" class="text-grey text-center q-py-md">
            Noch keine Mitglieder im Kader.
          </div>
          <q-list separator>
            <q-item v-for="z in kader" :key="z.id">
              <q-item-section>
                <q-item-label>{{ z.mitglied_nachname }}, {{ z.mitglied_vorname }}</q-item-label>
                <q-item-label caption>
                  <q-chip dense size="xs" :color="rolleColor(z.rolle)" text-color="white">{{ rolleLabel(z.rolle) }}</q-chip>
                  <span class="q-ml-xs">{{ z.von }} – {{ z.bis ?? 'heute' }}</span>
                </q-item-label>
              </q-item-section>
              <q-item-section side v-if="auth.hasPermission('mannschaften.write')">
                <div class="row q-gutter-xs">
                  <q-btn flat dense round icon="edit" color="primary" size="sm" @click="openEditKader(z)" />
                  <q-btn flat dense round icon="delete" color="negative" size="sm" @click="removeKader(z)" />
                </div>
              </q-item-section>
            </q-item>
          </q-list>
          <q-btn v-if="auth.hasPermission('mannschaften.write')" flat icon="person_add"
            label="Mitglied hinzufügen" color="primary" class="q-mt-sm" @click="openAddKader" />
          <div v-if="kaderFormOpen" class="q-mt-md q-gutter-sm">
            <q-select v-if="!editingKaderId" v-model="kaderForm.mitglied_id" :options="mitgliedOptions"
              option-value="id" :option-label="mitgliedLabel" emit-value map-options use-input
              input-debounce="0" @filter="filterMitglieder" label="Mitglied *" outlined dense />
            <q-select v-model="kaderForm.rolle" :options="rolleOptionen" option-value="value" option-label="label"
              emit-value map-options label="Rolle *" outlined dense />
            <div class="row q-gutter-sm">
              <q-input v-model="kaderForm.von" label="Von *" outlined dense type="date" class="col" />
              <q-input v-model="kaderForm.bis" label="Bis" outlined dense type="date" class="col" />
            </div>
            <div class="row q-gutter-sm">
              <q-btn flat label="Abbrechen" @click="kaderFormOpen = false" />
              <q-btn unelevated :label="editingKaderId ? 'Speichern' : 'Hinzufügen'"
                color="primary" :loading="kaderSaving" @click="saveKader" />
            </div>
          </div>
        </q-card-section>
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

const mannschaften = ref([])
const abteilungen = ref([])
const loading = ref(false)

const rolleOptionen = [
  { label: 'Spieler', value: 'spieler' },
  { label: 'Übungsleiter', value: 'uebungsleiter' },
  { label: 'Trainer', value: 'trainer' },
  { label: 'Betreuer', value: 'betreuer' },
]
function rolleLabel(r) { return rolleOptionen.find(o => o.value === r)?.label ?? r }
function rolleColor(r) {
  return { spieler: 'blue', uebungsleiter: 'indigo', trainer: 'deep-purple', betreuer: 'teal' }[r] ?? 'grey'
}

async function load() {
  loading.value = true
  try {
    const [{ data: ms }, { data: ab }] = await Promise.all([
      api.get('/api/mannschaften'),
      api.get('/api/abteilungen/'),
    ])
    mannschaften.value = ms
    abteilungen.value = ab
  } catch {
    $q.notify({ type: 'negative', message: 'Fehler beim Laden' })
  } finally {
    loading.value = false
  }
}
onMounted(load)

// ── Mannschaft anlegen/bearbeiten ──────────────────────────
const formOpen = ref(false)
const saving = ref(false)
const formError = ref('')
const form = ref({ id: null, abteilung_id: null, name: '', saison: '', beschreibung: '', version: null })

function openCreate() {
  form.value = { id: null, abteilung_id: null, name: '', saison: '', beschreibung: '', version: null }
  formError.value = ''
  formOpen.value = true
}
function openEdit(m) {
  form.value = { id: m.id, abteilung_id: m.abteilung_id, name: m.name, saison: m.saison ?? '',
                 beschreibung: m.beschreibung ?? '', version: m.version }
  formError.value = ''
  formOpen.value = true
}
async function save() {
  if (!form.value.abteilung_id || !form.value.name.trim()) {
    formError.value = 'Abteilung und Name sind erforderlich.'
    return
  }
  saving.value = true
  formError.value = ''
  try {
    const payload = {
      abteilung_id: form.value.abteilung_id, name: form.value.name.trim(),
      saison: form.value.saison || null, beschreibung: form.value.beschreibung || null,
    }
    if (form.value.id) {
      await api.put(`/api/mannschaften/${form.value.id}`, { ...payload, expected_version: form.value.version })
    } else {
      await api.post('/api/mannschaften', payload)
    }
    formOpen.value = false
    await load()
    $q.notify({ type: 'positive', message: 'Gespeichert' })
  } catch (e) {
    formError.value = e.response?.data?.detail || 'Fehler beim Speichern'
  } finally {
    saving.value = false
  }
}
function confirmDelete(m) {
  $q.dialog({
    title: 'Mannschaft löschen',
    message: `„${m.name}" wirklich löschen?`,
    cancel: true, persistent: true,
  }).onOk(async () => {
    try {
      await api.delete(`/api/mannschaften/${m.id}`)
      await load()
    } catch (e) {
      $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' })
    }
  })
}

// ── Kader ──────────────────────────────────────────────────
const kaderOpen = ref(false)
const kaderLoading = ref(false)
const kader = ref([])
const aktivMannschaft = ref(null)
const kaderFormOpen = ref(false)
const kaderSaving = ref(false)
const editingKaderId = ref(null)
const editingKaderVersion = ref(null)
const kaderForm = ref({ mitglied_id: null, rolle: 'spieler', von: '', bis: '' })

const alleMitglieder = ref([])
const mitgliedOptions = ref([])
function mitgliedLabel(m) { return `${m.nachname}, ${m.vorname}` }
function filterMitglieder(val, update) {
  const needle = val.toLowerCase()
  update(() => {
    mitgliedOptions.value = !needle
      ? alleMitglieder.value
      : alleMitglieder.value.filter(m => `${m.nachname} ${m.vorname}`.toLowerCase().includes(needle))
  })
}

async function openKader(m) {
  aktivMannschaft.value = m
  kaderFormOpen.value = false
  kaderOpen.value = true
  kaderLoading.value = true
  try {
    const [{ data: k }, { data: pers }] = await Promise.all([
      api.get(`/api/mannschaften/${m.id}/mitglieder`),
      alleMitglieder.value.length ? Promise.resolve({ data: null }) : api.get('/api/personen/'),
    ])
    kader.value = k
    if (pers) {
      alleMitglieder.value = pers.filter(p => p.mitglied).map(p => ({
        id: p.mitglied.id, vorname: p.mitglied.vorname, nachname: p.mitglied.nachname,
      }))
    }
    mitgliedOptions.value = alleMitglieder.value
  } finally {
    kaderLoading.value = false
  }
}
function openAddKader() {
  editingKaderId.value = null
  kaderForm.value = { mitglied_id: null, rolle: 'spieler', von: '', bis: '' }
  kaderFormOpen.value = true
}
function openEditKader(z) {
  editingKaderId.value = z.id
  editingKaderVersion.value = z.version
  kaderForm.value = { mitglied_id: z.mitglied_id, rolle: z.rolle, von: z.von ?? '', bis: z.bis ?? '' }
  kaderFormOpen.value = true
}
async function reloadKader() {
  const { data } = await api.get(`/api/mannschaften/${aktivMannschaft.value.id}/mitglieder`)
  kader.value = data
}
async function saveKader() {
  if (!editingKaderId.value && !kaderForm.value.mitglied_id) {
    $q.notify({ type: 'negative', message: 'Bitte ein Mitglied auswählen.' }); return
  }
  if (!kaderForm.value.von) {
    $q.notify({ type: 'negative', message: 'Bitte ein „Von"-Datum angeben.' }); return
  }
  kaderSaving.value = true
  const mid = aktivMannschaft.value.id
  try {
    if (editingKaderId.value) {
      await api.put(`/api/mannschaften/${mid}/mitglieder/${editingKaderId.value}`, {
        rolle: kaderForm.value.rolle, von: kaderForm.value.von || null,
        bis: kaderForm.value.bis || null, expected_version: editingKaderVersion.value,
      })
    } else {
      await api.post(`/api/mannschaften/${mid}/mitglieder`, {
        mitglied_id: kaderForm.value.mitglied_id, rolle: kaderForm.value.rolle,
        von: kaderForm.value.von || null, bis: kaderForm.value.bis || null,
      })
    }
    kaderFormOpen.value = false
    await reloadKader()
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' })
  } finally {
    kaderSaving.value = false
  }
}
async function removeKader(z) {
  try {
    await api.delete(`/api/mannschaften/${aktivMannschaft.value.id}/mitglieder/${z.id}`)
    kader.value = kader.value.filter(x => x.id !== z.id)
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' })
  }
}
</script>
