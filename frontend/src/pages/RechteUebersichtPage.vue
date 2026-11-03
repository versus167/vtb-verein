<template>
  <q-page padding>
    <div class="row items-center q-mb-md">
      <q-btn flat round dense icon="arrow_back" class="q-mr-sm" @click="zurueck" />
      <div class="text-h5">Rechteübersicht</div>
    </div>

    <div class="text-caption text-grey-7 q-mb-md">
      Wer hat welches Recht – wirksam aus Funktionen, Sockel und individuellen Anpassungen.
      Antippen zeigt die Personen. Kassen und Tresore werden pro Ressource vergeben und
      stehen deshalb nicht hier.
    </div>

    <div v-if="loading && !daten" class="row justify-center q-py-xl">
      <q-spinner size="40px" color="primary" />
    </div>

    <template v-else-if="daten">
      <div class="row items-center q-gutter-md q-mb-md">
        <q-checkbox v-model="inaktiveMitzaehlen" label="Inaktive Konten mitzählen" dense />
        <q-input v-model="suche" dense outlined clearable placeholder="Recht suchen"
          class="col-12 col-sm-4">
          <template #prepend><q-icon name="search" /></template>
        </q-input>
      </div>

      <q-banner v-if="admins.length" class="bg-blue-1 text-blue-10 q-mb-md rounded-borders">
        <template #avatar><q-icon name="shield" color="primary" /></template>
        {{ admins.length === 1 ? 'Ein Administrator hat' : `${admins.length} Administratoren haben` }}
        über die Rolle immer alle Rechte und sind unten nicht mitgezählt:
        {{ admins.map(anzeigeName).join(', ') }}
      </q-banner>

      <div class="row q-col-gutter-md">
        <div v-for="group in gefilterteGruppen" :key="group.label" class="col-12 col-sm-6 col-md-4">
          <q-card flat bordered>
            <q-card-section class="q-pb-none">
              <div class="row items-center">
                <q-icon :name="group.icon" color="primary" size="sm" />
                <span class="text-subtitle2 text-weight-bold q-ml-sm">{{ group.label }}</span>
              </div>
            </q-card-section>
            <q-list dense>
              <q-item v-for="perm in group.permissions" :key="perm.key" clickable
                @click="oeffne(perm)">
                <q-item-section>
                  <q-item-label>{{ perm.label }}</q-item-label>
                  <q-item-label caption class="text-grey-6">{{ perm.key }}</q-item-label>
                </q-item-section>
                <q-item-section side>
                  <q-badge v-if="istSockel(perm.key)" color="grey-5" label="alle" />
                  <q-badge v-else :color="anzahl(perm.key) ? 'primary' : 'grey-5'"
                    :label="anzahl(perm.key)" />
                </q-item-section>
              </q-item>
            </q-list>
          </q-card>
        </div>
      </div>
    </template>

    <q-dialog v-model="dialogOffen">
      <q-card style="min-width: 340px; max-width: 560px; width: 100%">
        <q-card-section>
          <div class="text-h6">{{ gewaehlt?.label }}</div>
          <div class="text-caption text-grey-7">
            {{ gewaehlt?.key }} · {{ inhaberListe.length }}
            {{ inhaberListe.length === 1 ? 'Person' : 'Personen' }}
          </div>
        </q-card-section>
        <q-separator />
        <q-list separator style="max-height: 60vh; overflow-y: auto">
          <q-item v-for="h in inhaberListe" :key="h.user_id" clickable
            @click="$router.push({ name: 'user-permissions', params: { id: h.user_id } })">
            <q-item-section>
              <q-item-label>
                {{ anzeigeName(h.person) }}
                <q-badge v-if="!h.person.active" color="grey" label="inaktiv" class="q-ml-xs" />
              </q-item-label>
              <q-item-label caption>
                <span v-if="h.scopes === 'global'">vereinsweit</span>
                <span v-else>nur {{ h.scopes.join(', ') }}</span>
                <q-badge v-for="q in h.quellen" :key="q"
                  :color="q === 'individuell' ? 'orange-1' : 'teal-1'"
                  :text-color="q === 'individuell' ? 'orange-10' : 'teal-9'"
                  class="q-ml-xs" :label="q" />
              </q-item-label>
            </q-item-section>
            <q-item-section side><q-icon name="chevron_right" /></q-item-section>
          </q-item>
          <q-item v-if="!inhaberListe.length">
            <q-item-section class="text-grey-6">Niemand (außer Administratoren)</q-item-section>
          </q-item>
        </q-list>
        <q-card-actions align="right">
          <q-btn flat label="Schließen" v-close-popup />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { usePageRefresh } from 'src/composables/useRefresh'
import { useZurueck } from 'src/composables/useZurueck'

defineOptions({ name: 'RechteUebersichtPage' })

const $q = useQuasar()
const zurueck = useZurueck({ name: 'einstellungen' })

const loading = ref(false)
const daten = ref(null)
const inaktiveMitzaehlen = ref(false)
const suche = ref('')
const dialogOffen = ref(false)
const gewaehlt = ref(null)

const personenById = computed(() => new Map((daten.value?.personen || []).map(p => [p.id, p])))
const sockel = computed(() => new Set(daten.value?.sockel || []))
const admins = computed(() =>
  (daten.value?.personen || []).filter(p => p.role === 'admin' && p.active))

function anzeigeName(p) {
  return p.name ? `${p.name} (${p.username})` : p.username
}

function istSockel(key) {
  return sockel.value.has(key)
}

// Inhaber eines Rechts inkl. Personendaten; inaktive Konten nur auf Wunsch,
// weil sie sich nicht anmelden können und das Recht damit nicht ausüben.
function inhaber(key) {
  return (daten.value?.inhaber?.[key] || [])
    .map(h => ({ ...h, person: personenById.value.get(h.user_id) }))
    .filter(h => h.person && (inaktiveMitzaehlen.value || h.person.active))
}

function anzahl(key) {
  return inhaber(key).length
}

const inhaberListe = computed(() => (gewaehlt.value ? inhaber(gewaehlt.value.key) : []))

const gefilterteGruppen = computed(() => {
  const groups = daten.value?.groups || []
  const s = (suche.value || '').trim().toLowerCase()
  if (!s) return groups
  return groups
    .map(g => g.label.toLowerCase().includes(s)
      ? g
      : { ...g, permissions: g.permissions.filter(p =>
          p.label.toLowerCase().includes(s) || p.key.toLowerCase().includes(s)) })
    .filter(g => g.permissions.length)
})

function oeffne(perm) {
  gewaehlt.value = perm
  dialogOffen.value = true
}

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/api/users/permission-overview')
    daten.value = data
  } catch {
    $q.notify({ type: 'negative', message: 'Fehler beim Laden der Rechteübersicht' })
  } finally {
    loading.value = false
  }
}

usePageRefresh(load)
onMounted(load)
</script>
