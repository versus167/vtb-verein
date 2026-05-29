<template>
  <div>
    <!-- Dateiliste -->
    <div v-if="anhaenge.length === 0" class="text-grey text-caption q-py-sm">
      Keine Anhänge vorhanden.
    </div>

    <q-list v-else dense separator>
      <q-item v-for="a in anhaenge" :key="a.id" class="q-px-none">
        <q-item-section avatar>
          <q-icon
            :name="isPdf(a) ? 'picture_as_pdf' : 'image'"
            :color="isPdf(a) ? 'negative' : 'primary'"
            size="sm"
          />
        </q-item-section>

        <q-item-section>
          <q-item-label>{{ a.original_name }}</q-item-label>
          <q-item-label caption>{{ formatGroesse(a.dateigroesse) }}</q-item-label>
        </q-item-section>

        <q-item-section side>
          <div class="row q-gutter-xs no-wrap">
            <q-btn
              flat dense round icon="download" color="primary" size="sm"
              @click="downloadAnhang(a)"
            >
              <q-tooltip>Herunterladen</q-tooltip>
            </q-btn>
            <q-btn
              v-if="canDelete"
              flat dense round icon="delete" color="negative" size="sm"
              @click="confirmDelete(a)"
            >
              <q-tooltip>Löschen</q-tooltip>
            </q-btn>
          </div>
        </q-item-section>
      </q-item>
    </q-list>

    <!-- Upload -->
    <div v-if="canUpload" class="q-mt-sm">
      <input
        ref="fileInput"
        type="file"
        accept="image/jpeg,image/png,image/gif,image/webp,application/pdf"
        style="display: none"
        @change="onFileSelected"
      />
      <q-btn
        outline
        color="primary"
        icon="attach_file"
        label="Anhang hochladen"
        size="sm"
        :loading="uploading"
        @click="fileInput.click()"
      />
      <span class="text-caption text-grey q-ml-sm">max. {{ maxMb }} MB · JPEG, PNG, GIF, WebP, PDF</span>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'

const props = defineProps({
  anhaenge: { type: Array, default: () => [] },
  uploadUrl: { type: String, required: true },
  canUpload: { type: Boolean, default: false },
  canDelete: { type: Boolean, default: false },
  maxMb: { type: Number, default: 10 },
})

const emit = defineEmits(['uploaded', 'deleted'])

const $q = useQuasar()
const fileInput = ref(null)
const uploading = ref(false)

function isPdf(anhang) {
  return anhang.mime_type === 'application/pdf' || anhang.original_name?.endsWith('.pdf')
}

async function downloadAnhang(anhang) {
  try {
    const response = await api.get(`/api/uploads/${anhang.stored_name}`, { responseType: 'blob' })
    const url = URL.createObjectURL(new Blob([response.data], { type: anhang.mime_type }))
    if (isPdf(anhang)) {
      const a = document.createElement('a')
      a.href = url
      a.download = anhang.original_name
      a.click()
    } else {
      window.open(url, '_blank')
    }
    setTimeout(() => URL.revokeObjectURL(url), 10000)
  } catch {
    $q.notify({ type: 'negative', message: 'Download fehlgeschlagen.' })
  }
}

function formatGroesse(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

async function onFileSelected(event) {
  const file = event.target.files?.[0]
  if (!file) return
  event.target.value = ''

  if (file.size > props.maxMb * 1024 * 1024) {
    $q.notify({ type: 'warning', message: `Datei zu groß (max. ${props.maxMb} MB).` })
    return
  }

  uploading.value = true
  const form = new FormData()
  form.append('file', file)
  try {
    const { data } = await api.post(props.uploadUrl, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    $q.notify({ type: 'positive', message: 'Anhang hochgeladen.' })
    emit('uploaded', data)
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Hochladen.' })
  } finally {
    uploading.value = false
  }
}

function confirmDelete(anhang) {
  $q.dialog({
    title: 'Anhang löschen',
    message: `„${anhang.original_name}" wirklich löschen?`,
    cancel: true,
    persistent: true,
  }).onOk(async () => {
    try {
      await api.delete(`${props.uploadUrl}/${anhang.id}`)
      $q.notify({ type: 'positive', message: 'Anhang gelöscht.' })
      emit('deleted', anhang.id)
    } catch (e) {
      $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler beim Löschen.' })
    }
  })
}
</script>
