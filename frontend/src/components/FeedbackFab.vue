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
      : 'min-width:640px;max-width:900px'">

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
        <q-input v-model="form.titel" label="Titel *" outlined dense autofocus />
        <q-select v-model="form.bereich_id" :options="bereiche"
          option-value="id" option-label="name" emit-value map-options
          label="Bereich *" outlined dense />

        <!-- Screenshot nur für App-Tickets: bei anderen Bereichen ist ein
             Abbild der App-Oberfläche nutzlos. Er wird beim Öffnen bereits
             aufgenommen (danach lässt er sich nicht mehr ohne den Dialog im Bild
             nachziehen), aber erst eingeblendet, sobald „VTB-App" als Bereich
             gewählt ist. -->
        <template v-if="istVtbApp">
          <div v-if="screenshotUrl">
            <img :src="screenshotUrl" class="vtb-feedback-shot" />
            <div class="vtb-btn-reihe q-mt-sm">
              <q-btn outline no-caps icon="refresh" color="primary" label="Neu aufnehmen"
                :loading="capturing" @click="retake" />
              <q-btn outline no-caps icon="hide_image" color="grey" label="Entfernen"
                @click="removeScreenshot" />
            </div>
          </div>
          <div v-else>
            <q-btn outline no-caps icon="screenshot_monitor" color="primary" label="Screenshot aufnehmen"
              class="vtb-btn-voll-mobil" :loading="capturing" @click="retake" />
          </div>
        </template>

        <!-- Andere Bereiche: kein App-Screenshot, sondern Fotos (Rückkamera)
             und/oder hochgeladene Bilder — z. B. um vor Ort etwas zu belegen.
             Mehrere Bilder je Ticket möglich. -->
        <template v-else-if="zeigeFotoBereich">
          <!-- Miniaturen bereits erfasster Bilder -->
          <div v-if="fotos.length" class="row q-gutter-sm">
            <div v-for="f in fotos" :key="f.id" class="vtb-foto-thumb">
              <img :src="f.url" />
              <q-btn round dense size="sm" icon="close" color="negative"
                class="vtb-foto-thumb__x" @click="removeFoto(f.id)" />
            </div>
          </div>

          <!-- Live-Kamera läuft -->
          <div v-if="kameraAktiv">
            <video ref="videoEl" class="vtb-feedback-video" playsinline muted></video>
            <div class="vtb-btn-reihe q-mt-sm">
              <q-btn no-caps icon="camera" color="primary" unelevated label="Auslösen" @click="ausloesen" />
              <q-btn no-caps icon="check" color="grey" outline label="Fertig" @click="kameraStoppen" />
            </div>
          </div>

          <!-- Auswahl: Foto aufnehmen und/oder Bild(er) hochladen -->
          <div v-else>
            <div class="vtb-btn-reihe">
              <q-btn v-if="kameraMoeglich" outline no-caps icon="photo_camera" color="primary"
                :label="fotos.length ? 'Weiteres Foto' : 'Foto aufnehmen'" @click="kameraStarten" />
              <q-btn outline no-caps icon="upload" color="primary"
                :label="fotos.length ? 'Weitere hochladen' : 'Bild hochladen'" @click="dateiWaehlen" />
            </div>
            <div v-if="!kameraMoeglich" class="text-caption text-grey-7 q-mt-xs">
              Kamera nur über HTTPS verfügbar – hier bitte Bilder hochladen.
            </div>
            <div v-if="kameraFehler" class="text-negative text-caption q-mt-xs">{{ kameraFehler }}</div>
          </div>
          <input ref="fileInput" type="file" accept="image/*" multiple class="hidden" @change="dateiGewaehlt" />
        </template>

        <q-input v-model="form.beschreibung" label="Beschreibung" outlined dense
          type="textarea" :rows="$q.screen.lt.sm ? 3 : 5" />
        <div v-if="error" class="vtb-fehler">
          <q-icon name="error" size="20px" />
          <span>{{ error }}</span>
        </div>
      </q-card-section>

      <q-separator />
      <q-card-actions :align="$q.screen.lt.sm ? undefined : 'right'"
        :class="$q.screen.lt.sm ? 'vtb-btn-reihe q-px-md q-pb-md' : ''">
        <q-btn flat label="Abbrechen" no-caps v-close-popup />
        <q-btn label="Ticket anlegen" icon="send" color="primary" unelevated no-caps
          class="vtb-feedback-senden" :loading="saving" @click="onSave" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup>
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
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
const vtbAppBereichId = ref(null)
const form = ref({ titel: '', bereich_id: null, beschreibung: '' })

// Screenshot der App-Oberfläche nur anzeigen/anhängen, wenn der Bereich „VTB-App"
// aktiv gewählt ist.
const istVtbApp = computed(
  () => vtbAppBereichId.value != null && form.value.bereich_id === vtbAppBereichId.value,
)

// Foto/Upload für andere Bereiche: sobald ein Bereich gewählt ist, der nicht
// „VTB-App" ist (der App-Screenshot wäre dort nutzlos).
const zeigeFotoBereich = computed(() => form.value.bereich_id != null && !istVtbApp.value)

// Mehrere Bilder je Ticket möglich: Kamera-Aufnahmen und/oder Uploads sammeln
// sich in dieser Liste, jedes Element { id, blob, url, name, type }.
const fotos = ref([])
let fotoSeq = 0

// Live-Kamera (Rückkamera). getUserMedia gibt es nur im Secure Context —
// über http (z. B. Handy im WLAN per IP) ist es nicht verfügbar, dann nur Upload.
const kameraAktiv   = ref(false)
const kameraFehler  = ref('')
const videoEl       = ref(null)
const fileInput     = ref(null)
let   kameraStream  = null
const kameraMoeglich = computed(
  () => window.isSecureContext && !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia),
)

function addFoto(blob, name, type) {
  fotos.value.push({
    id: ++fotoSeq,
    blob,
    url: URL.createObjectURL(blob),
    name: name || '',
    type: type || blob.type || 'application/octet-stream',
  })
}

function removeFoto(id) {
  const i = fotos.value.findIndex(f => f.id === id)
  if (i !== -1) {
    URL.revokeObjectURL(fotos.value[i].url)
    fotos.value.splice(i, 1)
  }
}

function revokeFotos() {
  for (const f of fotos.value) URL.revokeObjectURL(f.url)
  fotos.value = []
}

async function kameraStarten() {
  kameraFehler.value = ''
  try {
    kameraStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } })
    kameraAktiv.value = true
    await nextTick()
    if (videoEl.value) {
      // muted zwingend als Property (Vue setzt das Attribut nicht zuverlässig) –
      // ohne muted blockt die Autoplay-Policy den Start.
      videoEl.value.muted = true
      videoEl.value.srcObject = kameraStream
      await videoEl.value.play()
    }
  } catch (e) {
    kameraStoppen()
    kameraFehler.value = 'Kamera nicht verfügbar: ' + (e?.message || e?.name || 'unbekannt')
  }
}

function kameraStoppen() {
  if (kameraStream) {
    kameraStream.getTracks().forEach(t => t.stop())
    kameraStream = null
  }
  if (videoEl.value) videoEl.value.srcObject = null
  kameraAktiv.value = false
}

// Auslösen fügt ein Bild hinzu, lässt die Kamera aber laufen — so kann man
// mehrere Fotos hintereinander schießen; „Fertig" beendet die Kamera.
async function ausloesen() {
  const video = videoEl.value
  if (!video || !video.videoWidth || !video.videoHeight) return
  const canvas = document.createElement('canvas')
  canvas.width  = video.videoWidth
  canvas.height = video.videoHeight
  canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height)
  // Canvas liefert rohe Pixel ohne EXIF/HEIC → immer aufrecht stehendes JPEG.
  const blob = await new Promise(res => canvas.toBlob(res, 'image/jpeg', 0.85))
  if (blob) addFoto(blob, '', 'image/jpeg')
}

function dateiWaehlen() {
  if (fileInput.value) fileInput.value.click()
}

function dateiGewaehlt(e) {
  const files = Array.from(e.target.files || [])
  e.target.value = ''  // gleiche Datei(en) erneut wählbar machen
  for (const file of files) {
    if (!file.type.startsWith('image/')) {
      $q.notify({ type: 'warning', message: `„${file.name}" ist kein Bild – übersprungen.` })
      continue
    }
    addFoto(file, file.name, file.type)
  }
}

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
    vtbAppBereichId.value = vtbApp ? vtbApp.id : null
    // Bereich bewusst NICHT vorwählen (außer es gibt nur einen): der Screenshot
    // soll erst nach aktiver Bereichswahl erscheinen, nicht schon beim Öffnen.
    defaultBereichId = data.length === 1 ? data[0].id : null
  } catch {
    bereiche.value = []
  }
}

// ── FAB-Klick: erst Screenshot, dann Dialog ──────────────────────────
async function onFabClick() {
  revokeFotos()
  kameraFehler.value = ''
  await doCapture()   // Screenshot VOR dem Dialog (Stolperfalle #2)
  form.value = {
    titel: '',
    bereich_id: defaultBereichId,
    beschreibung: '',
  }
  error.value  = ''
  dialogOpen.value = true
}

function aufraeumen() {
  revokeScreenshot()
  revokeFotos()
  kameraStoppen()
}

function onDialogHide() {
  aufraeumen()
}

// Kamera nicht im Hintergrund weiterlaufen lassen, wenn die Foto-Sektion durch
// einen Bereichswechsel verschwindet (Kamera-LED bliebe sonst an).
watch(zeigeFotoBereich, (zeigt) => { if (!zeigt) kameraStoppen() })

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

    // Anhänge — App-Ticket: der Screenshot; sonst: alle Fotos/Uploads.
    // Best effort: das Ticket bleibt erhalten, auch wenn ein Anhang scheitert.
    const anhaenge = []
    if (istVtbApp.value && screenshotBlob.value) {
      anhaenge.push({ blob: screenshotBlob.value, name: `screenshot-ticket-${ticket.id}.png`, type: 'image/png' })
    } else if (!istVtbApp.value) {
      fotos.value.forEach((f, i) => {
        const ext = f.name.includes('.') ? f.name.split('.').pop() : (f.type.includes('png') ? 'png' : 'jpg')
        anhaenge.push({
          blob: f.blob,
          name: f.name || `foto-ticket-${ticket.id}-${i + 1}.${ext}`,
          type: f.type || 'image/jpeg',
        })
      })
    }
    for (const a of anhaenge) {
      try {
        // Blob-Type explizit setzen (manche Umgebungen liefern leeren type)
        const b = new Blob([a.blob], { type: a.type })
        const fd = new FormData()
        fd.append('file', b, a.name)
        await api.post(`/api/tickets/${ticket.id}/anhaenge`, fd)
      } catch (e) {
        const detail = e.response?.data?.detail || e.message || 'unbekannter Fehler'
        $q.notify({ type: 'warning', message: `Ticket gespeichert, Anhang „${a.name}" fehlgeschlagen: ${detail}` })
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
onUnmounted(aufraeumen)
</script>
