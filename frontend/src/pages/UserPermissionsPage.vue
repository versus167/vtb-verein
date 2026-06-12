<template>
  <q-page padding>
    <div class="row items-center q-mb-md">
      <q-btn flat round icon="arrow_back" @click="router.push({ name: 'personen' })" />
      <div class="text-h5 q-ml-sm">
        Berechtigungen: {{ userData?.username }}
      </div>
    </div>

    <q-inner-loading :showing="loading" />

    <template v-if="!loading && userData">
      <div class="text-caption text-grey-7 q-mb-sm">Rolle: {{ userData.role }}</div>

      <q-banner v-if="userData.role === 'admin'" class="bg-blue-1 q-mb-md rounded-borders">
        <template #avatar><q-icon name="shield" color="blue" /></template>
        Administratoren haben unabhängig von dieser Matrix immer alle Rechte.
      </q-banner>

      <q-banner v-if="hasOverrides" class="bg-orange-1 q-mb-md rounded-borders">
        <template #avatar><q-icon name="tune" color="orange" /></template>
        Es sind individuelle Anpassungen gesetzt
        ({{ grants.length }} gewährt, {{ denies.length }} entzogen).
      </q-banner>

      <q-banner class="bg-grey-2 q-mb-lg rounded-borders">
        <template #avatar><q-icon name="info" color="grey-7" /></template>
        Rechte werden über die <b>Funktionen</b> des Mitglieds geerbt (mehrere kumulieren).
        Hier kannst du je Recht abweichen: <b>+</b> zusätzlich gewähren, <b>−</b> entziehen
        (auch geerbte). Kassenbuch-Rechte werden separat pro Kasse vergeben.
      </q-banner>

      <PermissionMatrix
        mode="tristate"
        :groups="groups"
        :readonly="!canEdit"
        :inherited="inherited"
        :sources="sources"
        v-model:grants="grants"
        v-model:denies="denies"
      />

      <div v-if="canEdit" class="row q-gutter-sm q-mt-lg">
        <q-btn
          label="Alle Anpassungen entfernen"
          icon="restart_alt"
          flat color="secondary"
          :disable="!hasOverrides"
          @click="clearOverrides"
        />
        <q-btn
          label="Speichern"
          icon="save"
          color="primary" unelevated
          :loading="saving"
          @click="onSave"
        />
      </div>
      <div v-else class="text-caption text-grey-6 q-mt-lg">
        <q-icon name="visibility" size="xs" class="q-mr-xs" />Nur Ansicht – keine Berechtigung zum Bearbeiten
      </div>
    </template>
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { useAuthStore } from 'src/stores/auth'
import PermissionMatrix from 'src/components/PermissionMatrix.vue'

const $q = useQuasar()
const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const canEdit = computed(() => auth.hasPermission('personen.permissions'))

const loading = ref(false)
const saving = ref(false)
const userData = ref(null)
const groups = ref([])
const inherited = ref([])
const sources = ref({})
const grants = ref([])
const denies = ref([])

const hasOverrides = computed(() => grants.value.length > 0 || denies.value.length > 0)

function clearOverrides() {
  grants.value = []
  denies.value = []
}

async function load() {
  loading.value = true
  try {
    const [permsRes, groupsRes] = await Promise.all([
      api.get(`/api/users/${route.params.id}/permissions`),
      api.get('/api/users/permission-groups'),
    ])
    userData.value = permsRes.data.user
    inherited.value = permsRes.data.inherited
    sources.value = permsRes.data.sources
    grants.value = [...permsRes.data.grants]
    denies.value = [...permsRes.data.denies]
    groups.value = groupsRes.data
  } catch {
    $q.notify({ type: 'negative', message: 'Fehler beim Laden' })
  } finally {
    loading.value = false
  }
}

async function onSave() {
  saving.value = true
  try {
    await api.put(`/api/users/${route.params.id}/permissions`, {
      grants: grants.value,
      denies: denies.value,
    })
    $q.notify({ type: 'positive', message: 'Berechtigungen gespeichert' })
    router.push({ name: 'personen' })
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Speichern' })
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>
