<template>
  <q-page class="q-pa-md">
    <div class="row items-center q-mb-md">
      <div class="text-h5">Mannschaften</div>
      <q-space />
      <q-btn v-if="auth.hasPermission('mannschaften.write')" color="primary" unelevated
        icon="add" label="Neue Mannschaft" :round="$q.screen.lt.sm" @click="openCreate" />
    </div>

    <!-- Filter -->
    <div class="row q-col-gutter-sm q-mb-md items-center">
      <div class="col-12 col-sm-5">
        <q-select v-model="filterAbteilung" :options="abteilungFilterOptions" emit-value map-options
          dense outlined clearable label="Abteilung filtern" />
      </div>
      <div class="col-12 col-sm-5">
        <q-input v-model="search" dense outlined clearable placeholder="Team suchen…">
          <template #prepend><q-icon name="search" /></template>
        </q-input>
      </div>
      <div class="col text-caption text-grey-7">
        {{ gefilterte.length }} Team(s) · {{ kaderGesamt }} im Kader
      </div>
    </div>

    <q-inner-loading :showing="loading" />
    <div v-if="!loading && gefilterte.length === 0" class="text-grey text-center q-py-xl">
      Keine Mannschaften gefunden.
    </div>

    <!-- Gruppiert nach Abteilung, Teams als aufklappbare Liste -->
    <div v-for="g in gruppen" :key="g.abteilung" class="q-mb-md">
      <div class="row items-center q-mb-xs">
        <q-icon name="account_tree" color="purple" size="20px" class="q-mr-xs" />
        <div class="text-subtitle1 text-weight-medium">{{ g.abteilung }}</div>
        <q-chip dense size="sm" color="grey-3" class="q-ml-sm">{{ g.teams.length }}</q-chip>
      </div>
      <q-list bordered separator class="rounded-borders">
        <q-expansion-item v-for="m in g.teams" :key="m.id" icon="groups" @show="loadKader(m)">
          <template #header>
            <q-item-section>
              <q-item-label>{{ m.name }}</q-item-label>
              <q-item-label caption v-if="m.saison || m.beschreibung">
                <span v-if="m.saison">Saison {{ m.saison }}</span>
                <span v-if="m.beschreibung"> · {{ m.beschreibung }}</span>
              </q-item-label>
            </q-item-section>
            <q-item-section side>
              <div class="row items-center q-gutter-xs no-wrap">
                <q-chip dense size="sm" color="cyan-8" text-color="white" icon="groups">{{ m.mitglieder_count }}</q-chip>
                <q-btn v-if="auth.hasPermission('mannschaften.write')" flat dense round icon="edit"
                  color="primary" size="sm" @click.stop="openEdit(m)"><q-tooltip>Bearbeiten</q-tooltip></q-btn>
                <q-btn v-if="auth.hasPermission('mannschaften.delete')" flat dense round icon="delete"
                  color="negative" size="sm" @click.stop="confirmDelete(m)"><q-tooltip>Löschen</q-tooltip></q-btn>
              </div>
            </q-item-section>
          </template>

          <q-card>
            <q-card-section class="q-pt-sm">
              <q-inner-loading :showing="kaderLoadingId === m.id" />
              <div v-if="kaderLoadingId !== m.id && (kaderByTeam[m.id]?.length ?? 0) === 0"
                class="text-grey text-center q-py-sm">Noch keine Mitglieder im Kader.</div>
              <q-list dense separator>
                <q-item v-for="z in (kaderByTeam[m.id] ?? [])" :key="z.id">
                  <q-item-section>
                    <q-item-label>{{ z.mitglied_nachname }}, {{ z.mitglied_vorname }}</q-item-label>
                    <q-item-label caption>
                      <q-chip dense size="xs" :color="rolleColor(z.rolle)" text-color="white">{{ rolleLabel(z.rolle) }}</q-chip>
                      <span class="q-ml-xs">{{ z.von }} – {{ z.bis ?? 'heute' }}</span>
                    </q-item-label>
                  </q-item-section>
                  <q-item-section side v-if="auth.hasPermission('mannschaften.write')">
                    <div class="row q-gutter-xs">
                      <q-btn flat dense round icon="edit" color="primary" size="sm" @click="openEditKader(m, z)" />
                      <q-btn flat dense round icon="delete" color="negative" size="sm" @click="removeKader(m, z)" />
                    </div>
                  </q-item-section>
                </q-item>
              </q-list>
              <q-btn v-if="auth.hasPermission('mannschaften.write')" flat icon="person_add"
                label="Mitglied hinzufügen" color="primary" size="sm" class="q-mt-xs" @click="openAddKader(m)" />
              <div v-if="kaderFormTeamId === m.id" class="q-mt-sm q-gutter-sm">
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
                  <q-btn flat label="Abbrechen" @click="kaderFormTeamId = null" />
                  <q-btn unelevated :label="editingKaderId ? 'Speichern' : 'Hinzufügen'"
                    color="primary" :loading="kaderSaving" @click="saveKader(m)" />
                </div>
              </div>
            </q-card-section>
          </q-card>
        </q-expansion-item>
      </q-list>
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

  </q-page>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { useAuthStore } from 'src/stores/auth'

const $q = useQuasar()
const auth = useAuthStore()

const mannschaften = ref([])
const abteilungen = ref([])

// ── Filter & Gruppierung ───────────────────────────────────
const filterAbteilung = ref(null)
const search = ref('')

const abteilungFilterOptions = computed(() =>
  abteilungen.value.map(a => ({ label: a.name, value: a.id })))

const gefilterte = computed(() => {
  let list = mannschaften.value
  if (filterAbteilung.value) list = list.filter(m => m.abteilung_id === filterAbteilung.value)
  if (search.value) {
    const q = search.value.toLowerCase()
    list = list.filter(m => (m.name ?? '').toLowerCase().includes(q))
  }
  return list
})

const kaderGesamt = computed(() =>
  gefilterte.value.reduce((s, m) => s + (m.mitglieder_count || 0), 0))

const gruppen = computed(() => {
  const byAbt = {}
  for (const m of gefilterte.value) {
    const key = m.abteilung_name || '(ohne Abteilung)'
    ;(byAbt[key] ??= []).push(m)
  }
  return Object.keys(byAbt).sort().map(abteilung => ({ abteilung, teams: byAbt[abteilung] }))
})
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

// ── Kader (inline je Team) ─────────────────────────────────
const kaderByTeam = ref({})         // teamId -> kader[]
const kaderLoadingId = ref(null)
const kaderFormTeamId = ref(null)
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
async function ensureMitglieder() {
  if (alleMitglieder.value.length) return
  const { data } = await api.get('/api/personen/')
  alleMitglieder.value = data.filter(p => p.mitglied).map(p => ({
    id: p.mitglied.id, vorname: p.mitglied.vorname, nachname: p.mitglied.nachname,
  }))
  mitgliedOptions.value = alleMitglieder.value
}

async function loadKader(team) {
  kaderFormTeamId.value = null
  kaderLoadingId.value = team.id
  try {
    const { data } = await api.get(`/api/mannschaften/${team.id}/mitglieder`)
    kaderByTeam.value = { ...kaderByTeam.value, [team.id]: data }
    team.mitglieder_count = data.length
  } finally {
    kaderLoadingId.value = null
  }
}
function openAddKader(team) {
  editingKaderId.value = null
  kaderForm.value = { mitglied_id: null, rolle: 'spieler', von: '', bis: '' }
  kaderFormTeamId.value = team.id
  ensureMitglieder()
}
function openEditKader(team, z) {
  editingKaderId.value = z.id
  editingKaderVersion.value = z.version
  kaderForm.value = { mitglied_id: z.mitglied_id, rolle: z.rolle, von: z.von ?? '', bis: z.bis ?? '' }
  kaderFormTeamId.value = team.id
}
async function saveKader(team) {
  if (!editingKaderId.value && !kaderForm.value.mitglied_id) {
    $q.notify({ type: 'negative', message: 'Bitte ein Mitglied auswählen.' }); return
  }
  if (!kaderForm.value.von) {
    $q.notify({ type: 'negative', message: 'Bitte ein „Von"-Datum angeben.' }); return
  }
  kaderSaving.value = true
  try {
    if (editingKaderId.value) {
      await api.put(`/api/mannschaften/${team.id}/mitglieder/${editingKaderId.value}`, {
        rolle: kaderForm.value.rolle, von: kaderForm.value.von || null,
        bis: kaderForm.value.bis || null, expected_version: editingKaderVersion.value,
      })
    } else {
      await api.post(`/api/mannschaften/${team.id}/mitglieder`, {
        mitglied_id: kaderForm.value.mitglied_id, rolle: kaderForm.value.rolle,
        von: kaderForm.value.von || null, bis: kaderForm.value.bis || null,
      })
    }
    kaderFormTeamId.value = null
    await loadKader(team)
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' })
  } finally {
    kaderSaving.value = false
  }
}
async function removeKader(team, z) {
  try {
    await api.delete(`/api/mannschaften/${team.id}/mitglieder/${z.id}`)
    const arr = (kaderByTeam.value[team.id] ?? []).filter(x => x.id !== z.id)
    kaderByTeam.value = { ...kaderByTeam.value, [team.id]: arr }
    team.mitglieder_count = arr.length
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' })
  }
}
</script>
