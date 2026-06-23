<template>
  <q-page padding>
    <div class="text-h5 q-mb-md">Einstellungen</div>

    <q-tabs v-model="tab" dense align="left" class="q-mb-md">
      <q-tab name="funktionen" label="Funktionen" icon="badge" />
    </q-tabs>

    <q-tab-panels v-model="tab" animated>
      <!-- ════════════════════════════════════════════════
           Tab: Funktionen
           ════════════════════════════════════════════════ -->
      <q-tab-panel name="funktionen" class="q-pa-none">
        <div class="text-caption text-grey-7 q-mb-md">
          Funktionen werden Vereinsmitgliedern zugewiesen (z.B. Schiedsrichter, Übungsleiter)
          und können in Beitragsregeln als Bedingung oder Ausnahme verwendet werden.
        </div>

        <div class="row justify-end q-mb-md">
          <q-btn icon="add" label="Neue Funktion" color="primary" unelevated
            @click="openDialog()" />
        </div>

        <div v-if="loading" class="row justify-center q-py-xl">
          <q-spinner size="40px" color="primary" />
        </div>
        <q-list bordered separator v-else>
          <q-item v-for="f in funktionen" :key="f.id">
            <q-item-section>
              <q-item-label class="text-weight-medium">{{ f.name }}</q-item-label>
              <q-item-label caption>
                <span class="text-mono text-grey-6">{{ f.key }}</span>
                <span v-if="f.beschreibung" class="q-ml-sm">· {{ f.beschreibung }}</span>
              </q-item-label>
            </q-item-section>
            <q-item-section side>
              <div class="row q-gutter-xs">
                <q-btn flat dense round icon="security" color="teal" @click="openPermissionsDialog(f)">
                  <q-tooltip>Berechtigungen dieser Funktion</q-tooltip>
                </q-btn>
                <q-btn flat dense round icon="edit" color="primary" @click="openDialog(f)" />
                <q-btn flat dense round icon="delete" color="negative" @click="confirmDelete(f)" />
              </div>
            </q-item-section>
          </q-item>
          <q-item v-if="funktionen.length === 0">
            <q-item-section class="text-grey text-center q-py-md">
              Noch keine Funktionen angelegt.
            </q-item-section>
          </q-item>
        </q-list>
      </q-tab-panel>
    </q-tab-panels>

    <!-- Dialog -->
    <q-dialog v-model="dialogOpen" persistent :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card :style="$q.screen.lt.sm ? 'width:100%;border-radius:16px 16px 0 0' : 'min-width:440px'">
        <q-card-section class="text-h6">
          {{ editing?.id ? 'Funktion bearbeiten' : 'Neue Funktion' }}
        </q-card-section>
        <q-separator />
        <q-card-section class="q-gutter-sm">
          <q-input v-model="form.key" label="Key (intern) *" outlined dense
            :readonly="!!editing?.id"
            hint="Kleinbuchstaben, keine Leerzeichen – z.B. schiedsrichter" />
          <q-input v-model="form.name" label="Anzeigename *" outlined dense autofocus />
          <q-input v-model="form.beschreibung" label="Beschreibung" outlined dense />
          <div v-if="error" class="text-negative text-caption">{{ error }}</div>
        </q-card-section>
        <q-separator />
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn label="Speichern" color="primary" unelevated :loading="saving" @click="save" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Berechtigungen einer Funktion -->
    <q-dialog v-model="permDialogOpen" :position="$q.screen.lt.sm ? 'bottom' : 'standard'">
      <q-card :style="$q.screen.lt.sm ? 'width:100%;border-radius:16px 16px 0 0' : 'min-width:640px;max-width:860px'">
        <q-card-section class="row items-center q-pb-none">
          <div class="text-h6 col">
            Berechtigungen –
            <span class="text-weight-regular">{{ permFunktion?.name }}</span>
          </div>
          <q-btn flat dense round icon="close" v-close-popup />
        </q-card-section>
        <q-card-section class="text-caption text-grey-7 q-pt-xs">
          Mitglieder mit dieser Funktion erben die hier gewählten Rechte (mehrere Funktionen
          kumulieren). Ist die Funktion an eine Abteilung gebunden, gelten die Rechte nur für
          diese Abteilung; vereinsweite Funktionen wirken im gesamten Verein.
        </q-card-section>
        <q-separator />
        <q-card-section style="max-height:60vh; overflow-y:auto">
          <q-inner-loading :showing="permLoading" />
          <PermissionMatrix v-model="permSelected" :groups="groups" />
        </q-card-section>
        <q-separator />
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn label="Speichern" color="primary" unelevated :loading="permSaving" @click="savePermissions" />
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
import PermissionMatrix from 'src/components/PermissionMatrix.vue'

const $q = useQuasar()

const tab = ref('funktionen')
const funktionen = ref([])
const loading = ref(false)
const dialogOpen = ref(false)
const saving = ref(false)
const error = ref('')
const editing = ref(null)
const form = ref({ key: '', name: '', beschreibung: '' })

// Funktions-Berechtigungen
const groups = ref([])
const permDialogOpen = ref(false)
const permLoading = ref(false)
const permSaving = ref(false)
const permFunktion = ref(null)
const permSelected = ref([])

async function loadFunktionen() {
  loading.value = true
  try {
    const { data } = await api.get('/api/funktionen')
    funktionen.value = data
  } finally {
    loading.value = false
  }
}

function openDialog(f = null) {
  editing.value = f
  error.value = ''
  form.value = f
    ? { key: f.key, name: f.name, beschreibung: f.beschreibung ?? '' }
    : { key: '', name: '', beschreibung: '' }
  dialogOpen.value = true
}

async function save() {
  if (!form.value.name.trim() || (!editing.value && !form.value.key.trim())) {
    error.value = 'Key und Name sind Pflichtfelder.'
    return
  }
  saving.value = true
  error.value = ''
  try {
    if (editing.value?.id) {
      await api.put(`/api/funktionen/${editing.value.id}`, {
        name: form.value.name.trim(),
        beschreibung: form.value.beschreibung || null,
        expected_version: editing.value.version,
      })
    } else {
      await api.post('/api/funktionen', {
        key: form.value.key.trim(),
        name: form.value.name.trim(),
        beschreibung: form.value.beschreibung || null,
      })
    }
    dialogOpen.value = false
    await loadFunktionen()
  } catch (e) {
    error.value = e.response?.data?.detail || 'Fehler beim Speichern.'
  } finally {
    saving.value = false
  }
}

async function openPermissionsDialog(f) {
  permFunktion.value = f
  permSelected.value = []
  permDialogOpen.value = true
  permLoading.value = true
  try {
    const reqs = [api.get(`/api/funktionen/${f.id}/permissions`)]
    if (groups.value.length === 0) reqs.push(api.get('/api/users/permission-groups'))
    const res = await Promise.all(reqs)
    permSelected.value = res[0].data.permissions
    if (res[1]) groups.value = res[1].data
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Laden der Berechtigungen.' })
    permDialogOpen.value = false
  } finally {
    permLoading.value = false
  }
}

async function savePermissions() {
  permSaving.value = true
  try {
    await api.put(`/api/funktionen/${permFunktion.value.id}/permissions`, {
      permissions: permSelected.value,
    })
    $q.notify({ type: 'positive', message: 'Berechtigungen gespeichert' })
    permDialogOpen.value = false
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Speichern.' })
  } finally {
    permSaving.value = false
  }
}

function confirmDelete(f) {
  $q.dialog({
    title: 'Funktion löschen',
    message: `"${f.name}" wirklich löschen? Nur möglich, wenn die Funktion keinem Mitglied mehr zugeordnet ist.`,
    cancel: true,
    persistent: true,
  }).onOk(async () => {
    try {
      await api.delete(`/api/funktionen/${f.id}`)
      await loadFunktionen()
    } catch (e) {
      $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Löschen.' })
    }
  })
}

usePageRefresh(loadFunktionen)
onMounted(loadFunktionen)
</script>
