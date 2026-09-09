<template>
  <!--
    Beleg scannen (Ticket #197) — übernommen aus dem X1-ERP.

    Vollbild-Dialog statt eigener Route: Der Scanner wird aus dem
    Rechnungs-Dialog heraus geöffnet, und der soll darunter stehen bleiben.
    Über eine Route wären das eingetippte Formular und die schon gewählten
    Belege weg, sobald man scannt.

    `persistent`, weil ein Fingertipp neben den Dialog sonst mitten im Scannen
    alles verwirft. Zu ist über den Zurück-Pfeil links oben.

    Das Markup entspricht scan.php aus dem Übergabe-Paket; die IDs sind der
    Anschluss für frontend/src/lib/belegScanner.js und dürfen sich nicht
    ändern. Weggefallen sind „Zur Überweisung" und die Projekt-Mappe
    (Entscheid Marko), die Bootstrap-Icons sind Material Icons geworden.
  -->
  <q-dialog v-model="offen" persistent maximized transition-show="fade" transition-hide="fade">
    <div class="scn-app" id="scnApp">

      <!-- 1) Kamera: Live-Rahmen um den erkannten Beleg -->
      <section class="scn-view is-active" id="scnViewCamera">
        <header class="scn-head">
          <button type="button" class="scn-icon-btn" id="scnClose" title="Scannen abbrechen" @click="abbrechen">
            <i class="material-icons">arrow_back</i>
          </button>
          <h1><i class="material-icons">photo_camera</i> Beleg scannen</h1>
          <button type="button" class="scn-icon-btn is-on" id="scnAutoToggle"
                  title="Auto-Auslöser: löst aus, sobald der Beleg ruhig im Bild liegt" aria-pressed="true">
            <i class="material-icons">auto_fix_high</i>
          </button>
        </header>
        <div class="scn-stage" id="scnStage">
          <video id="scnVideo" playsinline muted autoplay></video>
          <canvas id="scnOverlay" class="scn-overlay"></canvas>
          <div class="scn-status" id="scnStatus" data-state="search">
            <i class="material-icons">search</i><span>Beleg ins Bild halten</span>
            <b class="scn-status-bar"><i id="scnStatusFill"></i></b>
          </div>
          <div class="scn-loading" id="scnLoading">
            <div class="scn-loading-box">
              <i class="material-icons scn-spin">hourglass_top</i>
              <div class="scn-loading-text" id="scnLoadingText">Scanner wird geladen …</div>
              <div class="scn-progress"><div id="scnProgressBar"></div></div>
              <div class="scn-loading-hint" id="scnLoadingHint">
                Einmalig ca. 11 MB, danach bleibt er im Browser gespeichert.
              </div>
              <button type="button" class="scn-btn scn-btn-ghost scn-btn-small" id="scnRetry" hidden>
                <i class="material-icons">refresh</i> Nochmal versuchen
              </button>
            </div>
          </div>
          <div class="scn-flash" id="scnFlash"></div>
        </div>
        <footer class="scn-bar">
          <div class="scn-bar-side">
            <button type="button" class="scn-icon-btn" id="scnFlip" title="Kamera wechseln">
              <i class="material-icons">cameraswitch</i>
            </button>
            <button type="button" class="scn-icon-btn is-torch" id="scnTorch" hidden
                    title="Blitz (Taschenlampe) ein/aus" aria-pressed="false">
              <i class="material-icons">flash_on</i>
            </button>
          </div>
          <button type="button" class="scn-shutter" id="scnShutter" disabled aria-label="Aufnehmen"><span></span></button>
          <button type="button" class="scn-stack" id="scnStack" hidden title="Zu den aufgenommenen Seiten">
            <canvas id="scnStackThumb" width="56" height="72"></canvas>
            <span class="scn-stack-count" id="scnStackCount">1</span>
            <span class="scn-stack-label">Weiter</span>
          </button>
        </footer>
      </section>

      <!-- 2) Ecken anpassen: vier Griffe, Lupe unter dem Finger -->
      <section class="scn-view" id="scnViewCorners">
        <header class="scn-head">
          <button type="button" class="scn-icon-btn" id="scnCornersBack" title="Verwerfen und neu aufnehmen">
            <i class="material-icons">arrow_back</i>
          </button>
          <h1><i class="material-icons">crop_free</i> Ecken anpassen</h1>
          <button type="button" class="scn-icon-btn" id="scnCornersFull" title="Ganzes Bild verwenden">
            <i class="material-icons">aspect_ratio</i>
          </button>
        </header>
        <div class="scn-stage scn-stage-corners" id="scnCornerStage">
          <canvas id="scnCornerCanvas"></canvas>
          <div class="scn-loupe" id="scnLoupe" hidden><canvas id="scnLoupeCanvas"></canvas></div>
        </div>
        <div class="scn-hint" id="scnCornerHint">
          <i class="material-icons">touch_app</i> Ecken ziehen — die Lupe zeigt die Kante genau.
        </div>
        <footer class="scn-bar scn-bar-actions">
          <button type="button" class="scn-btn scn-btn-ghost" id="scnCornersRetake">
            <i class="material-icons">photo_camera</i> Neu aufnehmen
          </button>
          <button type="button" class="scn-btn scn-btn-primary" id="scnCornersApply">
            <i class="material-icons">check</i> Übernehmen
          </button>
        </footer>
      </section>

      <!-- 3) Seiten prüfen: Filter, drehen, weitere Seite, hochladen -->
      <section class="scn-view" id="scnViewPages">
        <header class="scn-head">
          <button type="button" class="scn-icon-btn" id="scnPagesBack" title="Weitere Seite aufnehmen">
            <i class="material-icons">photo_camera</i>
          </button>
          <h1><i class="material-icons">collections</i> <span id="scnPagesTitle">Beleg prüfen</span></h1>
          <div class="scn-head-group">
            <button type="button" class="scn-icon-btn" id="scnPageCorners" title="Ecken dieser Seite anpassen">
              <i class="material-icons">crop_free</i>
            </button>
            <button type="button" class="scn-icon-btn" id="scnRotate" title="Um 90° drehen">
              <i class="material-icons">rotate_right</i>
            </button>
            <button type="button" class="scn-icon-btn scn-icon-danger" id="scnPageDelete" title="Diese Seite löschen">
              <i class="material-icons">delete</i>
            </button>
          </div>
        </header>
        <!-- Vorschau: fertige Seite in voller Auflösung, mit zwei Fingern oder
             Doppeltipp zoombar -->
        <div class="scn-preview" id="scnPreview">
          <div class="scn-preview-zoom" id="scnPreviewZoom"></div>
          <button type="button" class="scn-zoom-btn" id="scnZoomBtn" title="Vergrößern">
            <i class="material-icons">zoom_in</i>
          </button>
          <div class="scn-preview-busy" id="scnPreviewBusy" hidden><i class="material-icons scn-spin">hourglass_top</i></div>
        </div>
        <div class="scn-thumbs" id="scnThumbs"></div>
        <div class="scn-options">
          <label class="scn-select scn-select-filter" for="scnFilter" title="Bildfilter">
            <i class="material-icons" id="scnFilterIcon">description</i>
            <select id="scnFilter">
              <option value="dokument">Dokument</option>
              <option value="sw">Schwarz-Weiß</option>
              <option value="farbe">Farbe</option>
            </select>
            <i class="material-icons scn-select-arrow">expand_more</i>
          </label>
        </div>
        <footer class="scn-bar scn-bar-actions">
          <button type="button" class="scn-btn scn-btn-ghost" id="scnAddPage">
            <i class="material-icons">add</i> Seite
          </button>
          <button type="button" class="scn-btn scn-btn-primary" id="scnUpload">
            <i class="material-icons">cloud_upload</i> Übernehmen
          </button>
        </footer>
        <div class="scn-upload-progress" id="scnUploadProgress" hidden>
          <div class="scn-upload-box">
            <div class="scn-progress"><div id="scnUploadBar"></div></div>
            <span id="scnUploadText">Wird übertragen …</span>
          </div>
        </div>
      </section>

      <!-- 4) Fertig -->
      <section class="scn-view scn-view-done" id="scnViewDone">
        <div class="scn-done">
          <div class="scn-done-icon"><i class="material-icons">check_circle</i></div>
          <h2 id="scnDoneTitle">Beleg übernommen</h2>
          <p id="scnDoneText"></p>
          <button type="button" class="scn-btn scn-btn-primary scn-btn-big" id="scnNext">
            <i class="material-icons">photo_camera</i> Nächster Beleg
          </button>
          <button type="button" class="scn-btn scn-btn-ghost" @click="schliessen">
            <i class="material-icons">done</i> Fertig, zurück zur Rechnung
          </button>
        </div>
      </section>

      <div class="scn-toast" id="scnToast" hidden></div>
      <canvas id="scnWork" hidden></canvas>
    </div>
  </q-dialog>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { appInfo, ladeAppInfo } from 'src/composables/useAppInfo'
import { starteScanner } from 'src/lib/belegScanner'

defineOptions({ name: 'BelegScannenDialog' })

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  // Höchstzahl Seiten je Beleg. Muss zur Grenze des Endpunkts passen
  // (ScanPdfService.MAX_SEITEN) — sonst weist der Server ab, nachdem der
  // Anwender schon alles fotografiert hat.
  maxSeiten: { type: Number, default: 20 },
})

const emit = defineEmits(['update:modelValue', 'fertig'])

const offen = computed({
  get: () => props.modelValue,
  set: (wert) => emit('update:modelValue', wert),
})

let scanner = null

/**
 * Der Scanner greift die Knöpfe über ihre IDs ab, das Markup muss also
 * wirklich im DOM stehen. `nextTick` genügt dafür: Quasar rendert den
 * Dialog-Inhalt beim Öffnen, die Einblend-Animation läuft nebenher.
 */
async function starten () {
  if (scanner) return
  await ladeAppInfo()
  await nextTick()
  scanner = starteScanner({
    maxSeiten: props.maxSeiten,
    version: appInfo.value.version || '',
    onFertig: (datei) => emit('fertig', datei),
  })
}

function beenden () {
  if (scanner) {
    scanner.stop()
    scanner = null
  }
}

function schliessen () {
  offen.value = false
}

function abbrechen () {
  offen.value = false
}

watch(() => props.modelValue, (auf) => {
  if (auf) starten()
  else beenden()
})

// Wird der Dialog samt Elternseite ausgehängt, läuft ohne das die Kamera
// weiter — samt Leuchte und Akku.
onBeforeUnmount(beenden)
</script>

<style lang="scss" src="src/css/beleg-scanner.scss"></style>
