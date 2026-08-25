<template>
  <q-page padding>
    <div class="row items-center q-mb-lg">
      <div class="text-h5 col">Ticket-Verwaltung</div>
    </div>

    <q-tabs v-model="tab" align="left" class="q-mb-md">
      <q-tab name="bereiche"   label="Bereiche"   icon="folder" />
      <q-tab name="kategorien" label="Kategorien" icon="label" />
      <q-tab name="erinnerungen" label="Erinnerungen" icon="notifications_active" />
    </q-tabs>

    <!-- ── Bereiche ── -->
    <q-tab-panels v-model="tab" animated>
      <q-tab-panel name="bereiche" class="q-pa-none">

        <div class="row items-center q-mb-sm">
          <q-space />
          <q-btn icon="add" label="Neuer Bereich" color="primary" unelevated size="sm" @click="openBereichDialog()" />
        </div>

        <q-list bordered separator>
          <q-expansion-item
            v-for="b in bereiche"
            :key="b.id"
            expand-separator
            @before-show="loadBerechtigungen(b.id)"
          >
            <template #header>
              <q-item-section avatar>
                <q-icon name="folder" />
              </q-item-section>
              <q-item-section>
                <q-item-label>{{ b.name }}</q-item-label>
                <q-item-label caption>{{ b.beschreibung || '' }}</q-item-label>
              </q-item-section>
              <q-item-section side>
                <div class="row q-gutter-xs">
                  <q-btn flat round dense icon="edit" size="sm" @click.stop="openBereichDialog(b)" />
                  <q-btn flat round dense icon="delete" size="sm" color="negative" @click.stop="deleteBereich(b)" />
                </div>
              </q-item-section>
            </template>

            <q-card flat>
              <q-card-section>
                <div class="row items-center q-mb-sm">
                  <div class="text-subtitle2 col">Berechtigungen</div>
                  <q-btn icon="person_add" label="User hinzufügen" size="sm" color="primary" outline @click="openAddUser(b.id)" />
                </div>

                <div v-if="loadingBerechtigungen[b.id]" class="row justify-center q-py-md">
                  <q-spinner color="primary" />
                </div>
                <div v-else-if="!berechtigungen[b.id]?.length" class="text-grey text-caption q-mt-sm">
                  Noch keine Berechtigungen vergeben.
                </div>
                <q-markup-table v-else flat dense class="q-mt-sm">
                  <thead>
                    <tr>
                      <th class="text-left">Benutzer</th>
                      <th>Lesen</th>
                      <th>Bearbeiten</th>
                      <th>Schließen</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="u in berechtigungen[b.id]" :key="u.user_id">
                      <td>{{ u.username }}</td>
                      <td class="text-center">
                        <q-checkbox
                          :model-value="u.darf_lesen"
                          :disable="u.darf_bearbeiten || u.darf_schliessen"
                          @update:model-value="v => setFlag(b.id, u, 'darf_lesen', v)"
                        />
                      </td>
                      <td class="text-center">
                        <q-checkbox
                          :model-value="u.darf_bearbeiten"
                          :disable="u.darf_schliessen"
                          @update:model-value="v => setFlag(b.id, u, 'darf_bearbeiten', v)"
                        />
                      </td>
                      <td class="text-center">
                        <q-checkbox
                          :model-value="u.darf_schliessen"
                          @update:model-value="v => setFlag(b.id, u, 'darf_schliessen', v)"
                        />
                      </td>
                      <td class="text-center">
                        <q-btn flat round dense icon="person_remove" size="xs" color="negative" @click="removeUser(b.id, u)">
                          <q-tooltip>Berechtigung entfernen</q-tooltip>
                        </q-btn>
                      </td>
                    </tr>
                  </tbody>
                </q-markup-table>
              </q-card-section>
            </q-card>
          </q-expansion-item>
        </q-list>
      </q-tab-panel>

      <!-- ── Kategorien ── -->
      <q-tab-panel name="kategorien" class="q-pa-none">
        <div class="row items-center q-mb-sm">
          <q-space />
          <q-btn icon="add" label="Neue Kategorie" color="primary" unelevated size="sm" @click="openKategorieDialog()" />
        </div>

        <q-list bordered separator>
          <q-item v-for="k in kategorien" :key="k.id">
            <q-item-section avatar>
              <q-icon :name="k.icon || 'label'" />
            </q-item-section>
            <q-item-section>{{ k.name }}</q-item-section>
            <q-item-section side>
              <div class="row q-gutter-xs">
                <q-btn flat round dense icon="edit" size="sm" @click="openKategorieDialog(k)" />
                <q-btn flat round dense icon="delete" size="sm" color="negative" @click="deleteKategorie(k)" />
              </div>
            </q-item-section>
          </q-item>
        </q-list>
      </q-tab-panel>

      <!-- ── Erinnerungen ── -->
      <q-tab-panel name="erinnerungen" class="q-pa-none">
        <div class="text-body2 q-mb-md">
          Einmal täglich sieht die App nach, welche offenen Tickets liegen bleiben, und
          erinnert die Verantwortlichen daran – zugewiesen ist das der Zugewiesene, sonst
          alle, die im Bereich bearbeiten oder schließen dürfen.
          <span class="text-grey-8">
            Die Fristen gelten je Priorität; <strong>0 Tage</strong> heißt „diese
            Priorität nicht erinnern".
          </span>
        </div>

        <q-card flat bordered class="q-mb-md">
          <q-card-section>
            <div class="row items-center no-wrap">
              <div class="col">
                <div class="text-subtitle1">Unbeachtete Tickets</div>
                <div class="text-caption text-grey-8">
                  Noch niemand aus dem zuständigen Kreis hat das Ticket geöffnet. Gezählt
                  ab der Meldung – die Erinnerung endet, sobald jemand hineinsieht.
                </div>
              </div>
              <q-toggle v-model="erinnerung.unbeachtet_aktiv" />
            </div>

            <div class="row q-col-gutter-sm q-mt-sm">
              <div v-for="p in PRIORITAETEN" :key="p.key" class="col-6 col-sm-3">
                <q-input
                  v-model.number="erinnerung['unbeachtet_tage_' + p.key]"
                  type="number" dense outlined min="0" max="365" suffix="Tage"
                  :label="p.label" :disable="!erinnerung.unbeachtet_aktiv"
                />
              </div>
              <div class="col-6 col-sm-3">
                <q-input
                  v-model.number="erinnerung.unbeachtet_wiederholung_tage"
                  type="number" dense outlined min="1" max="365" suffix="Tage"
                  label="Dann wieder alle" :disable="!erinnerung.unbeachtet_aktiv"
                />
              </div>
            </div>
          </q-card-section>
        </q-card>

        <q-card flat bordered class="q-mb-md">
          <q-card-section>
            <div class="row items-center no-wrap">
              <div class="col">
                <div class="text-subtitle1">Liegen gebliebene Tickets</div>
                <div class="text-caption text-grey-8">
                  Jemand hat hingesehen, seither passiert nichts mehr: kein Kommentar,
                  keine Statusänderung, kein Anhang. Gezählt ab der letzten Aktivität –
                  bloßes Ansehen verlängert die Frist nicht.
                </div>
              </div>
              <q-toggle v-model="erinnerung.stillstand_aktiv" />
            </div>

            <div class="row q-col-gutter-sm q-mt-sm">
              <div v-for="p in PRIORITAETEN" :key="p.key" class="col-6 col-sm-3">
                <q-input
                  v-model.number="erinnerung['stillstand_tage_' + p.key]"
                  type="number" dense outlined min="0" max="365" suffix="Tage"
                  :label="p.label" :disable="!erinnerung.stillstand_aktiv"
                />
              </div>
              <div class="col-6 col-sm-3">
                <q-input
                  v-model.number="erinnerung.stillstand_wiederholung_tage"
                  type="number" dense outlined min="1" max="365" suffix="Tage"
                  label="Dann wieder alle" :disable="!erinnerung.stillstand_aktiv"
                />
              </div>
            </div>
          </q-card-section>
        </q-card>

        <div class="row justify-end">
          <q-btn label="Speichern" color="primary" unelevated
                 :loading="saving" @click="saveErinnerung" />
        </div>
      </q-tab-panel>
    </q-tab-panels>

    <!-- ── Bereich-Dialog ── -->
    <q-dialog v-model="bereichDialogOpen" persistent>
      <q-card style="min-width: 360px">
        <q-card-section class="text-h6">{{ editBereich?.id ? 'Bereich bearbeiten' : 'Neuer Bereich' }}</q-card-section>
        <q-separator />
        <q-card-section class="q-gutter-sm">
          <q-input v-model="bereichForm.name" label="Name *" outlined autofocus />
          <q-input v-model="bereichForm.beschreibung" label="Beschreibung" outlined type="textarea" rows="2" />
        </q-card-section>
        <q-separator />
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn label="Speichern" color="primary" unelevated :loading="saving" @click="saveBereich" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- ── User hinzufügen-Dialog ── -->
    <q-dialog v-model="addUserDialogOpen" persistent>
      <q-card style="min-width: 360px">
        <q-card-section class="text-h6">User hinzufügen</q-card-section>
        <q-separator />
        <q-card-section>
          <q-select
            v-model="addUserSelected"
            :options="addUserOptions"
            label="Benutzer wählen"
            outlined
            option-value="id"
            option-label="username"
            emit-value map-options
            autofocus
          />
        </q-card-section>
        <q-separator />
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn label="Hinzufügen" color="primary" unelevated :loading="saving" :disable="!addUserSelected" @click="addUser" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- ── Kategorie-Dialog ── -->
    <q-dialog v-model="kategorieDialogOpen" persistent>
      <q-card style="min-width: 360px">
        <q-card-section class="text-h6">{{ editKategorie?.id ? 'Kategorie bearbeiten' : 'Neue Kategorie' }}</q-card-section>
        <q-separator />
        <q-card-section class="q-gutter-sm">
          <q-input v-model="kategorieForm.name" label="Name *" outlined autofocus />
          <q-input v-model="kategorieForm.icon" label="Icon (Material Icons)" outlined />
        </q-card-section>
        <q-separator />
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn label="Speichern" color="primary" unelevated :loading="saving" @click="saveKategorie" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { usePageRefresh } from 'src/composables/useRefresh'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'

const $q = useQuasar()

const tab = ref('bereiche')
const bereiche = ref([])
const kategorien = ref([])
const saving = ref(false)

// Berechtigungen pro Bereich (lazy loaded)
const berechtigungen = ref({})
const loadingBerechtigungen = ref({})

// User hinzufügen
const addUserDialogOpen = ref(false)
const addUserBereichId = ref(null)
const addUserOptions = ref([])
const addUserSelected = ref(null)

// Bereich-Dialog
const bereichDialogOpen = ref(false)
const editBereich = ref(null)
const bereichForm = ref({ name: '', beschreibung: '' })

// Kategorie-Dialog
const kategorieDialogOpen = ref(false)
const editKategorie = ref(null)
const kategorieForm = ref({ name: '', icon: '' })

// Erinnerungen (#179-Nachgang): Fristen je Priorität – dringend zuerst, wie in der Ticketliste.
const PRIORITAETEN = [
  { key: 'sicherheit', label: 'Sicherheit' },
  { key: 'hoch',       label: 'Hoch' },
  { key: 'normal',     label: 'Normal' },
  { key: 'niedrig',    label: 'Niedrig' },
]
const erinnerung = ref({
  unbeachtet_aktiv: true,
  unbeachtet_tage_sicherheit: 1, unbeachtet_tage_hoch: 1,
  unbeachtet_tage_normal: 3, unbeachtet_tage_niedrig: 7,
  unbeachtet_wiederholung_tage: 7,
  stillstand_aktiv: true,
  stillstand_tage_sicherheit: 3, stillstand_tage_hoch: 7,
  stillstand_tage_normal: 28, stillstand_tage_niedrig: 28,
  stillstand_wiederholung_tage: 14,
})

async function loadAll() {
  const [b, k, e] = await Promise.all([
    api.get('/api/tickets/bereiche'),
    api.get('/api/tickets/kategorien'),
    api.get('/api/tickets/erinnerung-einstellungen'),
  ])
  bereiche.value = b.data
  kategorien.value = k.data
  erinnerung.value = e.data
}

async function loadBerechtigungen(bereichId) {
  loadingBerechtigungen.value[bereichId] = true
  try {
    const { data } = await api.get(`/api/tickets/bereiche/${bereichId}/berechtigungen`)
    berechtigungen.value = { ...berechtigungen.value, [bereichId]: data }
  } finally {
    loadingBerechtigungen.value[bereichId] = false
  }
}

async function openAddUser(bereichId) {
  addUserBereichId.value = bereichId
  addUserSelected.value = null
  const { data } = await api.get(`/api/tickets/bereiche/${bereichId}/berechtigungen/verfuegbare-user`)
  addUserOptions.value = data
  addUserDialogOpen.value = true
}

async function addUser() {
  if (!addUserSelected.value) return
  saving.value = true
  try {
    const { data } = await api.put(
      `/api/tickets/bereiche/${addUserBereichId.value}/berechtigungen/${addUserSelected.value}`,
      { darf_lesen: true, darf_bearbeiten: false, darf_schliessen: false },
    )
    const user = addUserOptions.value.find(u => u.id === addUserSelected.value)
    const neuerEintrag = { user_id: addUserSelected.value, username: user?.username ?? '', ...data }
    berechtigungen.value = {
      ...berechtigungen.value,
      [addUserBereichId.value]: [...(berechtigungen.value[addUserBereichId.value] ?? []), neuerEintrag],
    }
    addUserDialogOpen.value = false
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler.' })
  } finally {
    saving.value = false
  }
}

async function removeUser(bereichId, userRow) {
  await api.put(`/api/tickets/bereiche/${bereichId}/berechtigungen/${userRow.user_id}`, {
    darf_lesen: false, darf_bearbeiten: false, darf_schliessen: false,
  })
  berechtigungen.value = {
    ...berechtigungen.value,
    [bereichId]: berechtigungen.value[bereichId].filter(u => u.user_id !== userRow.user_id),
  }
}

async function setFlag(bereichId, userRow, flag, value) {
  const updated = {
    darf_lesen:      userRow.darf_lesen,
    darf_bearbeiten: userRow.darf_bearbeiten,
    darf_schliessen: userRow.darf_schliessen,
    [flag]: value,
  }
  try {
    const { data } = await api.put(
      `/api/tickets/bereiche/${bereichId}/berechtigungen/${userRow.user_id}`,
      updated,
    )
    // Lokalen State mit Server-Response (mit Kaskade) aktualisieren
    const list = berechtigungen.value[bereichId]
    const idx = list.findIndex(u => u.user_id === userRow.user_id)
    if (idx >= 0) {
      list[idx] = { ...list[idx], ...data }
      berechtigungen.value = { ...berechtigungen.value, [bereichId]: [...list] }
    }
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Speichern.' })
  }
}

// ── Bereiche ───────────────────────────────────────────────────────────────
function openBereichDialog(b = null) {
  editBereich.value = b
  bereichForm.value = { name: b?.name ?? '', beschreibung: b?.beschreibung ?? '' }
  bereichDialogOpen.value = true
}

async function saveBereich() {
  if (!bereichForm.value.name.trim()) return
  saving.value = true
  try {
    if (editBereich.value?.id) {
      await api.put(`/api/tickets/bereiche/${editBereich.value.id}`, {
        ...bereichForm.value,
        expected_version: editBereich.value.version,
      })
    } else {
      await api.post('/api/tickets/bereiche', bereichForm.value)
    }
    bereichDialogOpen.value = false
    await loadAll()
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Speichern.' })
  } finally {
    saving.value = false
  }
}

async function deleteBereich(b) {
  $q.dialog({
    title: 'Bereich löschen',
    message: `Bereich „${b.name}" wirklich löschen?`,
    cancel: true,
  }).onOk(async () => {
    try {
      await api.delete(`/api/tickets/bereiche/${b.id}`)
      await loadAll()
    } catch (e) {
      $q.dialog({
        title: 'Löschen nicht möglich',
        message: e.response?.data?.detail || 'Fehler beim Löschen.',
        ok: 'OK',
      })
    }
  })
}

// ── Kategorien ─────────────────────────────────────────────────────────────
function openKategorieDialog(k = null) {
  editKategorie.value = k
  kategorieForm.value = { name: k?.name ?? '', icon: k?.icon ?? '' }
  kategorieDialogOpen.value = true
}

async function saveKategorie() {
  if (!kategorieForm.value.name.trim()) return
  saving.value = true
  try {
    if (editKategorie.value?.id) {
      await api.put(`/api/tickets/kategorien/${editKategorie.value.id}`, {
        ...kategorieForm.value,
        expected_version: editKategorie.value.version,
      })
    } else {
      await api.post('/api/tickets/kategorien', kategorieForm.value)
    }
    kategorieDialogOpen.value = false
    await loadAll()
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Speichern.' })
  } finally {
    saving.value = false
  }
}

async function deleteKategorie(k) {
  $q.dialog({
    title: 'Kategorie löschen',
    message: `Kategorie „${k.name}" wirklich löschen?`,
    cancel: true,
  }).onOk(async () => {
    await api.delete(`/api/tickets/kategorien/${k.id}`)
    await loadAll()
  })
}

// ── Erinnerungen ───────────────────────────────────────────────────────────
async function saveErinnerung() {
  saving.value = true
  try {
    // Nur die Felder, die der Server kennt: `id`, `version` und die Zeitstempel
    // kommen beim Lesen mit, gehören aber nicht ins Schreib-Schema.
    const daten = { unbeachtet_aktiv: erinnerung.value.unbeachtet_aktiv,
                    stillstand_aktiv: erinnerung.value.stillstand_aktiv }
    for (const art of ['unbeachtet', 'stillstand']) {
      for (const p of PRIORITAETEN) daten[`${art}_tage_${p.key}`] = erinnerung.value[`${art}_tage_${p.key}`]
      daten[`${art}_wiederholung_tage`] = erinnerung.value[`${art}_wiederholung_tage`]
    }
    const { data } = await api.put('/api/tickets/erinnerung-einstellungen', daten)
    erinnerung.value = data
    $q.notify({ type: 'positive', message: 'Erinnerungen gespeichert.' })
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Speichern.' })
  } finally {
    saving.value = false
  }
}

usePageRefresh(loadAll)
onMounted(loadAll)
</script>
