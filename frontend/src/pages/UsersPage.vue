<template>
  <q-page padding>
    <div class="row items-center q-mb-md">
      <div class="text-h5 col">Benutzerverwaltung</div>
      <q-btn v-if="canManageUsers" label="Neu" icon="add" color="primary" unelevated @click="openCreateDialog" />
    </div>

    <q-table
      :rows="users"
      :columns="columns"
      row-key="id"
      :loading="loading"
      flat
      bordered
    >
      <template #body-cell-active="props">
        <q-td :props="props">
          <q-badge :color="props.value ? 'positive' : 'grey'">
            {{ props.value ? 'Aktiv' : 'Inaktiv' }}
          </q-badge>
        </q-td>
      </template>

      <template #body-cell-role="props">
        <q-td :props="props">
          {{ roleLabels[props.value] ?? props.value }}
        </q-td>
      </template>

      <template #body-cell-last_login="props">
        <q-td :props="props">
          {{ props.value ?? 'Noch nie' }}
        </q-td>
      </template>

      <template #body-cell-actions="props">
        <q-td :props="props" class="q-gutter-xs">
          <q-btn flat dense round icon="edit" color="primary" size="sm"
            title="Bearbeiten" @click="openEditDialog(props.row)" />
          <q-btn flat dense round icon="vpn_key" color="secondary" size="sm"
            title="Passwort ändern" @click="openPasswordDialog(props.row)" />
          <q-btn flat dense round icon="security" color="accent" size="sm"
            title="Berechtigungen" @click="goToPermissions(props.row)" />
          <q-btn flat dense round icon="delete" color="negative" size="sm"
            title="Löschen"
            :disable="props.row.id === auth.user?.id"
            @click="confirmDelete(props.row)" />
        </q-td>
      </template>
    </q-table>

    <!-- Erstellen-Dialog -->
    <q-dialog v-model="createOpen" persistent>
      <q-card style="min-width: 420px">
        <q-card-section class="text-h6">Neuen Benutzer anlegen</q-card-section>
        <q-separator />
        <q-card-section class="q-gutter-sm">
          <q-input v-model="createForm.username" label="Benutzername *" outlined autofocus
            :rules="[(v) => !!v || 'Pflichtfeld']" />
          <q-input v-model="createForm.email" label="E-Mail *" outlined type="email"
            :rules="[(v) => !!v || 'Pflichtfeld']" />
          <q-select v-model="createForm.role" label="Rolle" outlined :options="roleOptions"
            emit-value map-options />
          <q-checkbox v-model="createForm.active" label="Aktiv" />
          <q-input v-model="createForm.password" label="Passwort (optional)" outlined
            :type="showPw ? 'text' : 'password'">
            <template #append>
              <q-icon :name="showPw ? 'visibility_off' : 'visibility'"
                class="cursor-pointer" @click="showPw = !showPw" />
            </template>
          </q-input>
          <div class="text-caption text-grey-7">
            Ohne Passwort kann sich der Benutzer nur per Magic-Link anmelden.
          </div>
          <div v-if="createError" class="text-negative">{{ createError }}</div>
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
      <q-card style="min-width: 420px">
        <q-card-section class="text-h6">Benutzer bearbeiten: {{ editForm.username }}</q-card-section>
        <q-separator />
        <q-card-section class="q-gutter-sm">
          <q-input v-model="editForm.username" label="Benutzername *" outlined
            :rules="[(v) => !!v || 'Pflichtfeld']" />
          <q-input v-model="editForm.email" label="E-Mail *" outlined type="email"
            :rules="[(v) => !!v || 'Pflichtfeld']" />
          <q-select v-model="editForm.role" label="Rolle" outlined :options="roleOptions"
            emit-value map-options />
          <q-checkbox v-model="editForm.active" label="Aktiv" />
          <q-banner v-if="lastAdminWarning" class="vtb-warnung">
            <template #avatar><q-icon name="warning" /></template>
            Dies ist der letzte aktive Administrator!
          </q-banner>
          <div v-if="editError" class="text-negative">{{ editError }}</div>
        </q-card-section>
        <q-separator />
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn label="Speichern" color="primary" unelevated :loading="saving"
            :disable="lastAdminWarning" @click="onEdit" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Passwort-Dialog -->
    <q-dialog v-model="passwordOpen" persistent>
      <q-card style="min-width: 380px">
        <q-card-section class="text-h6">Passwort ändern: {{ passwordUser?.username }}</q-card-section>
        <q-separator />
        <q-card-section class="q-gutter-sm">
          <q-input v-model="newPassword" label="Neues Passwort *" outlined
            :type="showPw2 ? 'text' : 'password'" :rules="[(v) => v.length >= 6 || 'Mindestens 6 Zeichen']">
            <template #append>
              <q-icon :name="showPw2 ? 'visibility_off' : 'visibility'"
                class="cursor-pointer" @click="showPw2 = !showPw2" />
            </template>
          </q-input>
          <q-input v-model="newPasswordConfirm" label="Passwort wiederholen *" outlined
            :type="showPw2 ? 'text' : 'password'"
            :rules="[(v) => v === newPassword || 'Passwörter stimmen nicht überein']" />
          <div v-if="passwordError" class="text-negative">{{ passwordError }}</div>
        </q-card-section>
        <q-separator />
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" v-close-popup />
          <q-btn label="Ändern" color="primary" unelevated :loading="saving" @click="onPasswordChange" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { usePageRefresh } from 'src/composables/useRefresh'
import { useRouter } from 'vue-router'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { useAuthStore } from 'src/stores/auth'

const $q = useQuasar()
const router = useRouter()
const auth = useAuthStore()
// Login-Accounts darf nur anlegen, wer Berechtigungen vergeben darf.
const canManageUsers = computed(() => auth.hasPermission('personen.permissions'))

const users = ref([])
const loading = ref(false)

const roleLabels = {
  admin: 'Administrator',
  user: 'Bearbeiter',
  readonly: 'Nur Lesen',
}
const roleOptions = [
  { label: 'Administrator', value: 'admin' },
  { label: 'Bearbeiter', value: 'user' },
  { label: 'Nur Lesen', value: 'readonly' },
]

const columns = [
  { name: 'username',   label: 'Benutzername',  field: 'username',   sortable: true, align: 'left' },
  { name: 'email',      label: 'E-Mail',         field: 'email',      align: 'left' },
  { name: 'role',       label: 'Rolle',          field: 'role',       sortable: true, align: 'left' },
  { name: 'active',     label: 'Status',         field: 'active',     align: 'center' },
  { name: 'last_login', label: 'Letzter Login',  field: 'last_login', align: 'left' },
  { name: 'actions',    label: '',               field: 'actions',    align: 'right' },
]

async function loadUsers() {
  loading.value = true
  try {
    const { data } = await api.get('/api/users/')
    users.value = data
  } catch {
    $q.notify({ type: 'negative', message: 'Fehler beim Laden' })
  } finally {
    loading.value = false
  }
}

// --- Erstellen ---
const createOpen = ref(false)
const createError = ref('')
const saving = ref(false)
const showPw = ref(false)
const createForm = ref({ username: '', email: '', role: 'user', active: true, password: '' })

function openCreateDialog() {
  createForm.value = { username: '', email: '', role: 'user', active: true, password: '' }
  createError.value = ''
  createOpen.value = true
}

async function onCreate() {
  createError.value = ''
  saving.value = true
  try {
    await api.post('/api/users/', {
      ...createForm.value,
      password: createForm.value.password || null,
    })
    $q.notify({ type: 'positive', message: 'Benutzer angelegt' })
    createOpen.value = false
    await loadUsers()
  } catch (e) {
    createError.value = e.response?.data?.detail || 'Fehler beim Anlegen'
  } finally {
    saving.value = false
  }
}

// --- Bearbeiten ---
const editOpen = ref(false)
const editError = ref('')
const editForm = ref({})
const editOriginal = ref({})

const lastAdminWarning = computed(() => {
  if (!editOriginal.value.role) return false
  const wasActiveAdmin = editOriginal.value.role === 'admin' && editOriginal.value.active
  if (!wasActiveAdmin) return false
  const willBeDeactivated = editForm.value.role === 'admin' && !editForm.value.active
  const willBeDemoted = editForm.value.role !== 'admin'
  return willBeDeactivated || willBeDemoted
})

function openEditDialog(row) {
  editForm.value = { ...row }
  editOriginal.value = { ...row }
  editError.value = ''
  editOpen.value = true
}

async function onEdit() {
  editError.value = ''
  saving.value = true
  try {
    await api.put(`/api/users/${editForm.value.id}`, {
      username: editForm.value.username,
      email: editForm.value.email,
      role: editForm.value.role,
      active: editForm.value.active,
      expected_version: editForm.value.version,
    })
    $q.notify({ type: 'positive', message: 'Gespeichert' })
    editOpen.value = false
    await loadUsers()
  } catch (e) {
    editError.value = e.response?.data?.detail || 'Fehler beim Speichern'
  } finally {
    saving.value = false
  }
}

// --- Passwort ---
const passwordOpen = ref(false)
const passwordError = ref('')
const passwordUser = ref(null)
const newPassword = ref('')
const newPasswordConfirm = ref('')
const showPw2 = ref(false)

function openPasswordDialog(row) {
  passwordUser.value = row
  newPassword.value = ''
  newPasswordConfirm.value = ''
  passwordError.value = ''
  passwordOpen.value = true
}

async function onPasswordChange() {
  if (newPassword.value !== newPasswordConfirm.value) {
    passwordError.value = 'Passwörter stimmen nicht überein'
    return
  }
  passwordError.value = ''
  saving.value = true
  try {
    await api.post(`/api/users/${passwordUser.value.id}/password`, {
      new_password: newPassword.value,
    })
    $q.notify({ type: 'positive', message: 'Passwort geändert' })
    passwordOpen.value = false
  } catch (e) {
    passwordError.value = e.response?.data?.detail || 'Fehler'
  } finally {
    saving.value = false
  }
}

// --- Löschen ---
function confirmDelete(row) {
  $q.dialog({
    title: 'Benutzer löschen',
    message: `Benutzer "${row.username}" wirklich löschen?`,
    cancel: true,
    persistent: true,
  }).onOk(async () => {
    try {
      await api.delete(`/api/users/${row.id}`)
      $q.notify({ type: 'positive', message: 'Gelöscht' })
      await loadUsers()
    } catch (e) {
      $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' })
    }
  })
}

// --- Permissions ---
function goToPermissions(row) {
  router.push({ name: 'user-permissions', params: { id: row.id } })
}

usePageRefresh(loadUsers)
onMounted(loadUsers)
</script>
