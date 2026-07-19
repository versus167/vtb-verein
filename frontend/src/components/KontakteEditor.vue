<template>
  <div>
    <div class="row items-center q-mb-sm">
      <div class="col text-caption text-grey-7">
        Mehrere Einträge je Typ möglich – einer davon ist immer der primäre.
      </div>
      <q-btn label="Hinzufügen" icon="add" color="primary" unelevated size="sm" no-caps
        @click="openForm(null)" />
    </div>

    <q-inner-loading :showing="loading" />

    <div v-if="!loading && kontakte.length === 0" class="text-grey text-center q-py-md">
      Keine Kontaktdaten erfasst
    </div>
    <q-list v-else separator>
      <q-item v-for="k in kontakte" :key="k.id" class="q-px-none">
        <q-item-section avatar>
          <q-icon :name="typIcon(k.typ)" color="primary" />
        </q-item-section>
        <q-item-section>
          <q-item-label>
            {{ k.wert }}
            <q-badge v-if="k.ist_primaer" class="q-ml-sm" color="primary">primär</q-badge>
          </q-item-label>
          <q-item-label caption>
            {{ typLabel(k.typ) }}<span v-if="k.label"> · {{ k.label }}</span>
          </q-item-label>
        </q-item-section>
        <q-item-section side>
          <div class="q-gutter-xs">
            <q-btn v-if="!k.ist_primaer" flat dense round icon="star" color="amber-8" size="sm"
              @click="setPrimaer(k)">
              <q-tooltip>Als primär setzen</q-tooltip>
            </q-btn>
            <q-btn flat dense round icon="edit" color="primary" size="sm" @click="openForm(k)" />
            <q-btn flat dense round icon="delete" color="negative" size="sm" @click="remove(k)" />
          </div>
        </q-item-section>
      </q-item>
    </q-list>

    <!-- Kontakt anlegen / bearbeiten -->
    <q-dialog v-model="formOpen" persistent>
      <q-card style="min-width: min(400px, 92vw)">
        <q-card-section class="text-h6">
          {{ editingId ? 'Kontakt bearbeiten' : 'Neuer Kontakt' }}
        </q-card-section>
        <q-separator />
        <q-card-section class="q-gutter-sm">
          <q-select v-model="form.typ" label="Typ *" outlined dense
            :options="typOptionen" emit-value map-options />
          <q-input v-model="form.wert" label="Wert *" outlined dense
            :type="form.typ === 'email' ? 'email' : 'text'" />
          <q-input v-model="form.label" label="Bezeichnung (optional, z. B. privat)" outlined dense />
          <q-toggle v-model="form.ist_primaer" label="Primärer Kontakt dieses Typs" />
        </q-card-section>
        <q-separator />
        <q-card-actions align="right">
          <q-btn flat label="Abbrechen" no-caps v-close-popup />
          <q-btn label="Speichern" color="primary" unelevated no-caps :loading="saving" @click="save" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup>
// Kontaktliste (E-Mail/Telefon/Mobil/Fax) mit Anlegen/Bearbeiten/Löschen und
// Primär-Markierung. Über apiBase für Admin- wie Self-Service-Endpunkte nutzbar
// (z. B. '/api/personen/mein-mitglied'); die Primär-Regel erzwingt das Backend.
import { ref, onMounted } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'

const props = defineProps({
  // Basis-Pfad, unter dem .../kontakte erreichbar ist
  apiBase: { type: String, required: true },
})
const emit = defineEmits(['changed'])

const $q = useQuasar()

const kontakte = ref([])
const loading = ref(false)
const formOpen = ref(false)
const saving = ref(false)
const editingId = ref(null)
const editingVersion = ref(null)
const form = ref({ typ: 'email', wert: '', label: '', ist_primaer: false })

const typOptionen = [
  { label: 'E-Mail', value: 'email' },
  { label: 'Telefon', value: 'telefon' },
  { label: 'Mobil', value: 'mobil' },
  { label: 'Fax', value: 'fax' },
]

function typLabel(t) { return typOptionen.find(o => o.value === t)?.label ?? t }
function typIcon(t) { return { email: 'mail', telefon: 'call', mobil: 'smartphone', fax: 'fax' }[t] ?? 'contact_phone' }

async function load() {
  loading.value = true
  try {
    const { data } = await api.get(`${props.apiBase}/kontakte`)
    kontakte.value = data
    emit('changed', data)
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Kontakte konnten nicht geladen werden' })
  } finally {
    loading.value = false
  }
}

function openForm(k) {
  if (k) {
    editingId.value = k.id
    editingVersion.value = k.version
    form.value = { typ: k.typ, wert: k.wert, label: k.label ?? '', ist_primaer: k.ist_primaer }
  } else {
    editingId.value = null
    editingVersion.value = null
    form.value = { typ: 'email', wert: '', label: '', ist_primaer: false }
  }
  formOpen.value = true
}

async function save() {
  if (!form.value.typ || !form.value.wert.trim()) {
    $q.notify({ type: 'negative', message: 'Typ und Wert sind erforderlich.' })
    return
  }
  saving.value = true
  const payload = {
    typ: form.value.typ,
    wert: form.value.wert.trim(),
    label: form.value.label || null,
    ist_primaer: form.value.ist_primaer,
  }
  try {
    if (editingId.value) {
      await api.put(`${props.apiBase}/kontakte/${editingId.value}`,
        { ...payload, expected_version: editingVersion.value })
    } else {
      await api.post(`${props.apiBase}/kontakte`, payload)
    }
    formOpen.value = false
    await load()
    $q.notify({ type: 'positive', message: 'Gespeichert' })
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Speichern' })
  } finally {
    saving.value = false
  }
}

async function setPrimaer(k) {
  try {
    await api.put(`${props.apiBase}/kontakte/${k.id}`, {
      typ: k.typ, wert: k.wert, label: k.label, ist_primaer: true,
      expected_version: k.version,
    })
    await load()
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' })
  }
}

function remove(k) {
  $q.dialog({
    title: 'Kontakt löschen',
    message: `„${k.wert}" wirklich löschen?`,
    cancel: { label: 'Abbrechen', flat: true, noCaps: true },
    ok: { label: 'Löschen', color: 'negative', unelevated: true, noCaps: true },
  }).onOk(async () => {
    try {
      await api.delete(`${props.apiBase}/kontakte/${k.id}`)
      await load()
    } catch (e) {
      $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Löschen' })
    }
  })
}

onMounted(load)
</script>
