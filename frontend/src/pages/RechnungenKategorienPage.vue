<template>
  <div>
    <div class="row items-center q-mb-md q-gutter-sm">
      <div class="text-subtitle1">Kategorien</div>
      <q-space />
      <q-btn unelevated color="primary" icon="add" label="Neu" @click="neu" />
    </div>

    <div class="text-caption text-grey q-mb-md">
      Die Auswahl beim Einreichen bewusst kurz halten. Das Sachkonto trägt die
      Kategorie für die spätere Fibu-Anbindung – es darf vorerst leer bleiben.
    </div>

    <q-list bordered separator>
      <q-item v-for="k in kategorien" :key="k.id" clickable @click="bearbeite(k)">
        <q-item-section>
          <q-item-label>{{ k.name }}</q-item-label>
          <q-item-label caption>
            <span v-if="k.sachkonto">Sachkonto {{ k.sachkonto }}</span>
            <span v-else class="text-orange">kein Sachkonto</span>
            <span v-if="k.kostenstelle"> · KSt {{ k.kostenstelle }}</span>
            <span v-if="k.beschreibung"> · {{ k.beschreibung }}</span>
          </q-item-label>
        </q-item-section>
        <q-item-section side><q-icon name="chevron_right" color="grey-6" /></q-item-section>
      </q-item>
      <q-item v-if="kategorien.length === 0">
        <q-item-section class="text-grey text-center q-py-md">
          Keine Kategorien – ohne mindestens eine kann niemand etwas einreichen.
        </q-item-section>
      </q-item>
    </q-list>

    <q-dialog v-model="dialogOpen" persistent>
      <q-card style="min-width:340px">
        <q-card-section class="row items-center">
          <div class="text-h6">{{ aktuell?.id ? 'Kategorie bearbeiten' : 'Neue Kategorie' }}</div>
          <q-space />
          <q-btn flat dense round icon="close" v-close-popup />
        </q-card-section>
        <q-card-section class="q-pt-none q-gutter-sm">
          <q-input v-model="form.name" outlined dense label="Name *" autofocus />
          <q-input v-model="form.beschreibung" outlined dense label="Beschreibung" />
          <q-input v-model="form.sachkonto" outlined dense label="Sachkonto (Aufwand)" />
          <q-input v-model.number="form.kostenstelle" outlined dense type="number"
            label="Kostenstelle" />
          <q-input v-model.number="form.kostentraeger" outlined dense type="number"
            label="Kostenträger" />
          <div v-if="error" class="text-negative text-caption">{{ error }}</div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn v-if="aktuell?.id" flat color="negative" label="Löschen"
            :loading="busy" @click="loeschen" />
          <q-space />
          <q-btn unelevated color="primary" label="Speichern" :loading="busy"
            @click="speichern" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { usePageRefresh } from 'src/composables/useRefresh'
import { fehlertext } from 'src/composables/useRechnungen'

defineOptions({ name: 'RechnungenKategorienPage' })

const $q = useQuasar()

const kategorien = ref([])
const dialogOpen = ref(false)
const aktuell = ref(null)
const busy = ref(false)
const error = ref('')
const form = ref(leer())

function leer() {
  return { name: '', beschreibung: '', sachkonto: '', kostenstelle: null, kostentraeger: null }
}

async function load() {
  const { data } = await api.get('/api/rechnungen/kategorien')
  kategorien.value = data
}

function neu() {
  aktuell.value = null
  form.value = leer()
  error.value = ''
  dialogOpen.value = true
}

function bearbeite(k) {
  aktuell.value = k
  form.value = {
    name: k.name,
    beschreibung: k.beschreibung || '',
    sachkonto: k.sachkonto || '',
    kostenstelle: k.kostenstelle,
    kostentraeger: k.kostentraeger,
  }
  error.value = ''
  dialogOpen.value = true
}

async function speichern() {
  if (!form.value.name?.trim()) {
    error.value = 'Bitte einen Namen angeben.'
    return
  }
  busy.value = true
  error.value = ''
  const nutzlast = {
    name: form.value.name.trim(),
    beschreibung: form.value.beschreibung || null,
    sachkonto: form.value.sachkonto || null,
    kostenstelle: form.value.kostenstelle ?? null,
    kostentraeger: form.value.kostentraeger ?? null,
  }
  try {
    if (aktuell.value?.id) {
      await api.patch(`/api/rechnungen/kategorien/${aktuell.value.id}`,
        { ...nutzlast, expected_version: aktuell.value.version })
    } else {
      await api.post('/api/rechnungen/kategorien', nutzlast)
    }
    dialogOpen.value = false
    await load()
  } catch (e) {
    error.value = fehlertext(e, 'Speichern fehlgeschlagen')
  } finally {
    busy.value = false
  }
}

function loeschen() {
  $q.dialog({
    title: 'Kategorie löschen',
    message: `„${aktuell.value.name}“ löschen? Das geht nur, solange keine Rechnung `
      + 'darauf verweist.',
    cancel: true,
    ok: { label: 'Löschen', color: 'negative' },
  }).onOk(async () => {
    busy.value = true
    try {
      await api.delete(`/api/rechnungen/kategorien/${aktuell.value.id}`)
      dialogOpen.value = false
      await load()
    } catch (e) {
      error.value = fehlertext(e, 'Löschen fehlgeschlagen')
    } finally {
      busy.value = false
    }
  })
}

usePageRefresh(load)
onMounted(async () => {
  try { await load() } catch { $q.notify({ type: 'negative', message: 'Fehler beim Laden' }) }
})
</script>
