<template>
  <!-- Trigger in der festen Kopfzeile. Früher ein FAB unten rechts, der auf
       Listen-Seiten den Pagination-Pfeil verdeckt hat (#69). -->
  <q-btn id="feedback-fab" flat :dense="$q.screen.gt.sm" round icon="feedback"
    :loading="capturing" @click="onFabClick">
    <q-tooltip>Feedback / Screenshot</q-tooltip>
  </q-btn>

  <!-- Dialog -->
  <q-dialog id="feedback-dialog" v-model="dialogOpen"
    :position="$q.screen.lt.sm ? 'bottom' : 'standard'"
    @hide="onDialogHide">
    <q-card class="vtb-feedback-dialog" :style="$q.screen.lt.sm
      ? 'width:100%;border-radius:16px 16px 0 0'
      : 'min-width:480px;max-width:620px'">

      <q-card-section class="row items-center q-pb-none">
        <div class="vtb-feedback-icon">
          <q-icon name="feedback" size="22px" color="primary" />
        </div>
        <div class="text-subtitle1 text-weight-bold q-ml-sm">Feedback / Ticket anlegen</div>
        <q-space />
        <q-btn flat round dense icon="close" v-close-popup />
      </q-card-section>
      <q-separator class="q-mt-sm" />

      <q-card-section class="q-gutter-sm">
        <!-- Screenshot-Vorschau -->
        <div v-if="screenshotUrl">
          <img :src="screenshotUrl" class="vtb-feedback-shot" />
          <div class="row q-gutter-xs q-mt-xs">
            <q-btn flat dense size="sm" icon="refresh" color="primary" label="Neu aufnehmen" no-caps
              :loading="capturing" @click="retake" />
            <q-btn flat dense size="sm" icon="hide_image" color="grey" label="Entfernen" no-caps
              @click="removeScreenshot" />
          </div>
        </div>
        <div v-else>
          <q-btn flat dense size="sm" icon="screenshot_monitor" color="primary" label="Screenshot aufnehmen" no-caps
            :loading="capturing" @click="retake" />
        </div>

        <q-input v-model="form.titel" label="Titel *" outlined dense autofocus />
        <q-select v-model="form.bereich_id" :options="bereiche"
          option-value="id" option-label="name" emit-value map-options
          label="Bereich *" outlined dense />
        <q-input v-model="form.beschreibung" label="Beschreibung" outlined dense
          type="textarea" :rows="3" />
        <div v-if="error" class="text-negative text-caption">{{ error }}</div>
      </q-card-section>

      <q-separator />
      <q-card-actions align="right">
        <q-btn flat label="Abbrechen" no-caps v-close-popup />
        <q-btn label="Ticket anlegen" icon="send" color="primary" unelevated no-caps
          class="vtb-feedback-senden" :loading="saving" @click="onSave" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'

const $q = useQuasar()

const capturing  = ref(false)
const dialogOpen = ref(false)
const saving     = ref(false)
const error      = ref('')
const bereiche   = ref([])

const screenshotBlob = ref(null)
const screenshotUrl  = ref(null)

let defaultBereichId = null
const form = ref({ titel: '', bereich_id: null, beschreibung: '' })

// ── html2canvas lazy loader ──────────────────────────────────────────
let h2cPromise = null

function loadHtml2Canvas() {
  if (window.html2canvas) return Promise.resolve(window.html2canvas)
  if (h2cPromise) return h2cPromise
  h2cPromise = new Promise((resolve, reject) => {
    const s = document.createElement('script')
    s.src = '/vendor/html2canvas.min.js'
    s.onload  = () => window.html2canvas
      ? resolve(window.html2canvas)
      : reject(new Error('html2canvas nicht gefunden'))
    s.onerror = () => reject(new Error('html2canvas Ladefehler'))
    document.head.appendChild(s)
  })
  return h2cPromise
}

function pageBg() {
  const b = getComputedStyle(document.body).backgroundColor
  if (b && b !== 'rgba(0, 0, 0, 0)' && b !== 'transparent') return b
  const h = getComputedStyle(document.documentElement).backgroundColor
  return (h && h !== 'rgba(0, 0, 0, 0)' && h !== 'transparent') ? h : '#ffffff'
}

async function captureFullPage() {
  const h2c = await loadHtml2Canvas()
  const doc  = document.documentElement
  const canvas = await h2c(doc, {
    backgroundColor: pageBg(),
    useCORS:     true,
    logging:     false,
    scale:       1,
    scrollX:     0,
    scrollY:     0,
    windowWidth:  doc.scrollWidth,
    windowHeight: doc.scrollHeight,
    ignoreElements: (el) =>
      el.id === 'feedback-fab' ||
      el.id === 'feedback-dialog' ||
      (el.classList?.contains('q-dialog__backdrop')),
  })
  return new Promise((res) => canvas.toBlob(res, 'image/png'))
}

// ── Screenshot-Helfer ────────────────────────────────────────────────
function revokeScreenshot() {
  if (screenshotUrl.value) {
    URL.revokeObjectURL(screenshotUrl.value)
    screenshotUrl.value = null
  }
  screenshotBlob.value = null
}

async function doCapture() {
  capturing.value = true
  try {
    const blob = await captureFullPage()
    revokeScreenshot()
    screenshotBlob.value = blob
    screenshotUrl.value  = URL.createObjectURL(blob)
  } catch {
    $q.notify({ type: 'warning', message: 'Screenshot fehlgeschlagen – Ticket wird ohne Bild gespeichert.' })
  } finally {
    capturing.value = false
  }
}

function removeScreenshot() { revokeScreenshot() }

async function retake() { await doCapture() }

// ── Bereiche laden ───────────────────────────────────────────────────
async function loadBereiche() {
  try {
    const { data } = await api.get('/api/tickets/bereiche')
    bereiche.value = data
    const vtbApp = data.find(b => b.name.toLowerCase().includes('vtb-app') || b.name.toLowerCase().includes('vtb app'))
    if (vtbApp) defaultBereichId = vtbApp.id
    else if (data.length === 1) defaultBereichId = data[0].id
  } catch {
    bereiche.value = []
  }
}

// ── FAB-Klick: erst Screenshot, dann Dialog ──────────────────────────
async function onFabClick() {
  await doCapture()   // Screenshot VOR dem Dialog (Stolperfalle #2)
  form.value = {
    titel: '',
    bereich_id: defaultBereichId,
    beschreibung: '',
  }
  error.value  = ''
  dialogOpen.value = true
}

function onDialogHide() {
  revokeScreenshot()
}

// ── Speichern ────────────────────────────────────────────────────────
async function onSave() {
  if (!form.value.titel.trim()) { error.value = 'Titel ist ein Pflichtfeld.'; return }
  if (!form.value.bereich_id)   { error.value = 'Bitte einen Bereich wählen.'; return }

  saving.value = true
  error.value  = ''
  try {
    const { data: ticket } = await api.post('/api/tickets/', {
      titel:        form.value.titel,
      beschreibung: form.value.beschreibung,
      bereich_id:   form.value.bereich_id,
    })

    // Screenshot anhängen — best effort, Ticket bleibt erhalten wenn es fehlschlägt
    if (screenshotBlob.value) {
      try {
        // Blob-Type explizit setzen (manche Umgebungen liefern leeren type)
        const pngBlob = new Blob([screenshotBlob.value], { type: 'image/png' })
        const fd = new FormData()
        fd.append('file', pngBlob, `screenshot-ticket-${ticket.id}.png`)
        await api.post(`/api/tickets/${ticket.id}/anhaenge`, fd)
      } catch (e) {
        const detail = e.response?.data?.detail || e.message || 'unbekannter Fehler'
        $q.notify({ type: 'warning', message: `Ticket gespeichert, Screenshot fehlgeschlagen: ${detail}` })
      }
    }

    $q.notify({ type: 'positive', message: `Ticket #${ticket.id} angelegt` })
    dialogOpen.value = false
    window.dispatchEvent(new CustomEvent('vtb:ticket-created', { detail: ticket }))
  } catch (e) {
    error.value = e.response?.data?.detail || 'Fehler beim Speichern'
  } finally {
    saving.value = false
  }
}

onMounted(loadBereiche)
onUnmounted(revokeScreenshot)
</script>
