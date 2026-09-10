<template>
  <div>
    <!-- Dateiliste -->
    <div v-if="anhaenge.length === 0" class="text-grey text-caption q-py-sm">
      Keine Anhänge vorhanden.
    </div>

    <q-list v-else dense separator>
      <q-item v-for="a in anhaenge" :key="a.id" class="q-px-none" clickable @click="openPreview(a)">
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
              @click.stop="downloadAnhang(a)"
            >
              <q-tooltip>Herunterladen</q-tooltip>
            </q-btn>
            <q-btn
              v-if="canDelete"
              flat dense round icon="delete" color="negative" size="sm"
              @click.stop="confirmDelete(a)"
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
        :accept="uploadAccept"
        style="display: none"
        @change="onFileSelected"
      />
      <div class="row items-center q-gutter-sm">
        <q-btn
          outline
          color="primary"
          icon="attach_file"
          label="Anhang hochladen"
          size="sm"
          :loading="uploading"
          @click="fileInput.click()"
        />
        <!-- Foto aufnehmen (#111) und Beleg scannen (#197) sind zwei
             verschiedene Werkzeuge: Das Foto zeigt, was im Sucher steht (eine
             kaputte Tür), der Scanner sucht Belegkanten und baut ein PDF.
             Beide nur, wo die Kamera überhaupt darf — getUserMedia gibt es
             ausschließlich im Secure Context. -->
        <q-btn
          v-if="foto && kameraMoeglich"
          outline
          color="primary"
          icon="photo_camera"
          label="Foto aufnehmen"
          size="sm"
          :loading="uploading"
          @click="kameraStarten"
        />
        <q-btn
          v-if="scannen && scannerMoeglich"
          outline
          color="primary"
          icon="document_scanner"
          label="Beleg scannen"
          size="sm"
          :loading="uploading"
          @click="scannerOffen = true"
        />
      </div>

      <!-- Live-Kamera. Steht unter den Knöpfen statt in einem eigenen Dialog,
           damit die schon hochgeladenen Anhänge sichtbar bleiben — man sieht,
           was man ergänzt. -->
      <div v-if="kameraAktiv" class="q-mt-sm">
        <video ref="videoEl" class="vtb-feedback-video" playsinline muted></video>
        <div class="vtb-btn-reihe q-mt-sm">
          <q-btn no-caps icon="camera" color="primary" unelevated label="Auslösen"
            :loading="uploading" @click="ausloesen" />
          <q-btn no-caps icon="check" color="grey" outline label="Fertig" @click="kameraStoppen" />
        </div>
      </div>
      <div v-if="kameraFehler" class="text-negative text-caption q-mt-xs">{{ kameraFehler }}</div>
      <BelegScannenDialog v-if="scannen" v-model="scannerOffen" @fertig="onDateiGewaehlt" />
      <span class="text-caption text-grey q-ml-sm">max. {{ maxMb }} MB · JPEG, PNG, GIF, WebP, PDF</span>
    </div>

    <!-- Vorschau -->
    <q-dialog v-model="previewOpen" :maximized="$q.screen.lt.sm" @hide="closePreview">
      <q-card style="width: 90vw; max-width: 900px">
        <q-card-section class="row items-center q-py-sm">
          <q-icon
            :name="isPdf(previewAnhang) ? 'picture_as_pdf' : 'image'"
            :color="isPdf(previewAnhang) ? 'negative' : 'primary'"
            class="q-mr-sm"
          />
          <div class="text-subtitle1 ellipsis">{{ previewAnhang?.original_name }}</div>
          <q-space />
          <q-btn flat dense round icon="download" color="primary" @click="downloadAnhang(previewAnhang)">
            <q-tooltip>Herunterladen</q-tooltip>
          </q-btn>
          <q-btn flat dense round icon="close" v-close-popup>
            <q-tooltip>Schließen</q-tooltip>
          </q-btn>
        </q-card-section>

        <q-separator />

        <q-card-section class="q-pa-none bg-grey-2">
          <div v-if="previewLoading" class="flex flex-center q-pa-xl">
            <q-spinner color="primary" size="40px" />
          </div>
          <template v-else-if="previewUrl">
            <!-- Bild: überall inline -->
            <div v-if="!isPdf(previewAnhang)" class="flex flex-center" style="max-height: 80vh; overflow: auto">
              <img :src="previewUrl" style="max-width: 100%; height: auto; display: block" />
            </div>
            <!-- PDF: Desktop eingebettet; Mobile-Browser können PDFs nicht einbetten -->
            <iframe
              v-else-if="!$q.platform.is.mobile"
              :src="previewUrl"
              style="width: 100%; height: 75vh; border: 0; display: block"
            />
            <div v-else class="column flex-center text-center q-pa-xl">
              <q-icon name="picture_as_pdf" color="negative" size="64px" class="q-mb-md" />
              <div class="text-body2 text-grey-8 q-mb-md">
                PDFs lassen sich auf Mobilgeräten nicht direkt einbetten.
              </div>
              <q-btn color="primary" icon="open_in_new" label="Im Browser öffnen" @click="openInTab" />
            </div>
          </template>
        </q-card-section>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { ladeAppInfo, maxUploadMb, uploadAccept } from 'src/composables/useAppInfo'
import { useKamera } from 'src/composables/useKamera'
import BelegScannenDialog from 'components/BelegScannenDialog.vue'

const props = defineProps({
  anhaenge: { type: Array, default: () => [] },
  uploadUrl: { type: String, required: true },
  canUpload: { type: Boolean, default: false },
  canDelete: { type: Boolean, default: false },
  // Keine eigene Zahl mehr: Die Grenze kommt aus /api/app-info, damit sie nicht
  // von der Server-Einstellung abdriftet — genau das war sie (Panel 10 MB,
  // Server 20 MB). Wer sie hier setzt, engt bewusst weiter ein.
  maxMb: { type: Number, default: 0 },
  // Beleg-Scanner anbieten (Kantenerkennung, Entzerrung, PDF). Für Flächen, an
  // die Papier kommt: Rechnungen und Kasse. Bei Tickets bewusst aus — dort will
  // man knipsen, nicht scannen.
  scannen: { type: Boolean, default: false },
  // Schnappschuss anbieten (das Bild, das im Sucher steht). Für Flächen, an die
  // man etwas zeigt statt es einzureichen — Tickets.
  foto: { type: Boolean, default: false },
  // Zusätzliche Query-Parameter für den Upload (nicht für Löschen/Download).
  // Bewusst nicht an uploadUrl angehängt: daraus baut das Löschen seine URL.
  uploadParams: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['uploaded', 'deleted'])

const $q = useQuasar()
const fileInput = ref(null)
const uploading = ref(false)

// Beleg-Scanner (#197). getUserMedia gibt es nur im Secure Context — über http
// (außer localhost) fehlt die Kamera ersatzlos, dann bleibt der Knopf weg,
// statt beim Tippen ins Leere zu laufen.
const scannerOffen = ref(false)
const scannerMoeglich = window.isSecureContext
  && !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)

// Server-Grenze, sofern die Fläche keine engere vorgibt.
const grenzeMb = computed(() => props.maxMb || maxUploadMb.value)

// Schnappschuss (#111). Derselbe Ablauf wie im Ticket-Anlegen-Dialog.
const {
  kameraAktiv, kameraFehler, videoEl, kameraMoeglich, kameraStarten, kameraStoppen, schnappschuss,
} = useKamera()

// Auslösen lädt sofort hoch — anders als beim Anlegen, wo es noch keine ID
// gibt und die Bilder warten müssen. Die Kamera läuft weiter, damit man
// mehrere Aufnahmen hintereinander machen kann; „Fertig" beendet sie.
async function ausloesen() {
  const blob = await schnappschuss()
  if (!blob) return
  const stempel = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')
  await onDateiGewaehlt(new File([blob], `foto-${stempel}.jpg`, { type: 'image/jpeg' }))
}

onBeforeUnmount(kameraStoppen)

onMounted(ladeAppInfo)

const previewOpen = ref(false)
const previewLoading = ref(false)
const previewUrl = ref('')
const previewAnhang = ref(null)

function isPdf(anhang) {
  if (!anhang) return false
  return anhang.mime_type === 'application/pdf' || anhang.original_name?.endsWith('.pdf')
}

// Die Datei hängt am Fach-Endpunkt des Anhangs, nicht an einem allgemeinen
// Upload-Pfad: Nur dort ist bekannt, wer das zugehörige Ticket bzw. den Beleg
// lesen darf. Gleiche Ableitung wie beim Löschen — daher ohne eigenes Prop.
function dateiUrl(anhang) {
  return `${props.uploadUrl}/${anhang.id}/datei`
}

async function openPreview(anhang) {
  previewAnhang.value = anhang
  previewLoading.value = true
  previewOpen.value = true
  if (previewUrl.value) {
    URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = ''
  }
  try {
    const response = await api.get(dateiUrl(anhang), { responseType: 'blob' })
    previewUrl.value = URL.createObjectURL(new Blob([response.data], { type: anhang.mime_type }))
  } catch {
    $q.notify({ type: 'negative', message: 'Vorschau fehlgeschlagen.' })
    previewOpen.value = false
  } finally {
    previewLoading.value = false
  }
}

function closePreview() {
  if (previewUrl.value) {
    URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = ''
  }
  previewAnhang.value = null
}

function openInTab() {
  if (previewUrl.value) window.open(previewUrl.value, '_blank')
}

async function downloadAnhang(anhang) {
  if (!anhang) return
  try {
    const response = await api.get(dateiUrl(anhang), { responseType: 'blob' })
    const url = URL.createObjectURL(new Blob([response.data], { type: anhang.mime_type }))
    const a = document.createElement('a')
    a.href = url
    a.download = anhang.original_name
    a.click()
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

// Gewählte Datei und gescannter Beleg gehen denselben Weg — der Scanner liefert
// ein fertiges PDF, das sich von einer selbst gewählten Datei nicht unterscheidet.
async function onFileSelected(event) {
  const file = event.target.files?.[0]
  if (!file) return
  event.target.value = ''
  await onDateiGewaehlt(file)
}

async function onDateiGewaehlt(file) {
  if (file.size > grenzeMb.value * 1024 * 1024) {
    $q.notify({ type: 'warning', message: `Datei zu groß (max. ${grenzeMb.value} MB).` })
    return
  }

  uploading.value = true
  const form = new FormData()
  form.append('file', file)
  try {
    const { data } = await api.post(props.uploadUrl, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      params: props.uploadParams,
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
