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

      <q-banner v-if="hasCustomPermissions" class="bg-orange-1 q-mb-md rounded-borders">
        <template #avatar><q-icon name="warning" color="orange" /></template>
        Die Berechtigungen weichen von den Rollen-Standards ab.
      </q-banner>

      <q-banner class="bg-blue-1 q-mb-lg rounded-borders">
        <template #avatar><q-icon name="info" color="blue" /></template>
        Kassenbuch-Berechtigungen werden pro Kasse in der Kassenverwaltung vergeben.
      </q-banner>

      <div class="row q-col-gutter-md q-mb-lg">
        <div
          v-for="group in groups"
          :key="group.label"
          class="col-12 col-sm-6 col-md-4"
        >
          <q-card flat bordered>
            <q-card-section>
              <div class="row items-center q-mb-sm">
                <q-icon :name="group.icon" color="primary" size="sm" />
                <span class="text-subtitle2 text-weight-bold q-ml-sm">{{ group.label }}</span>
              </div>
              <div v-for="perm in group.permissions" :key="perm.key">
                <q-checkbox
                  v-model="selected"
                  :val="perm.key"
                  :label="perm.label"
                  :color="deviatesFromDefault(perm.key) ? 'orange' : 'primary'"
                />
              </div>
            </q-card-section>
          </q-card>
        </div>
      </div>

      <div class="row q-gutter-sm">
        <q-btn
          label="Auf Rollen-Standard zurücksetzen"
          icon="restart_alt"
          flat
          color="secondary"
          @click="resetToDefaults"
        />
        <q-btn
          label="Speichern"
          icon="save"
          color="primary"
          unelevated
          :loading="saving"
          @click="onSave"
        />
      </div>
    </template>
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'

const $q = useQuasar()
const route = useRoute()
const router = useRouter()

const loading = ref(false)
const saving = ref(false)
const userData = ref(null)
const selected = ref([])
const defaults = ref([])
const groups = ref([])

const hasCustomPermissions = computed(() => {
  const sel = new Set(selected.value)
  const def = new Set(defaults.value)
  if (sel.size !== def.size) return true
  return [...sel].some((p) => !def.has(p))
})

function deviatesFromDefault(key) {
  const inSelected = selected.value.includes(key)
  const inDefault = defaults.value.includes(key)
  return inSelected !== inDefault
}

function resetToDefaults() {
  selected.value = [...defaults.value]
}

async function load() {
  loading.value = true
  try {
    const [permsRes, groupsRes] = await Promise.all([
      api.get(`/api/users/${route.params.id}/permissions`),
      api.get('/api/users/permission-groups'),
    ])
    userData.value = permsRes.data.user
    selected.value = [...permsRes.data.current]
    defaults.value = [...permsRes.data.defaults]
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
      permissions: selected.value,
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
