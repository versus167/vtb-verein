// Live-Kamera für Schnappschüsse (Rückkamera), geteilt von den Flächen, die
// „Foto aufnehmen" anbieten: dem Ticket-Anlegen-Dialog (#111) und dem
// AnhangPanel am bestehenden Ticket.
//
// Bewusst NICHT der Beleg-Scanner (#197): Der sucht Belegkanten, entzerrt
// perspektivisch und baut ein mehrseitiges PDF — das richtige Werkzeug für ein
// Papier, das falsche für eine kaputte Tür. Hier geht es um genau das Foto, das
// im Sucher steht.
//
// Herausgezogen, weil es sonst zwei getUserMedia-Implementierungen gäbe. Die
// Fallstricke stecken in wenigen Zeilen, und die will man nur einmal richtig
// haben: `muted` als Property statt Attribut (sonst blockt die Autoplay-Policy),
// das Stoppen jeder einzelnen Spur (sonst bleibt die Kamera-Leuchte an) und das
// Aufräumen beim Verlassen.
import { computed, nextTick, ref } from 'vue'

export function useKamera() {
  const kameraAktiv = ref(false)
  const kameraFehler = ref('')
  const videoEl = ref(null)
  let stream = null

  // getUserMedia gibt es nur im Secure Context — über http (außer localhost)
  // fehlt die Kamera ersatzlos. Dann bleibt der Knopf weg, statt beim Tippen
  // ins Leere zu laufen.
  const kameraMoeglich = computed(
    () => window.isSecureContext && !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia),
  )

  async function kameraStarten() {
    kameraFehler.value = ''
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } })
      kameraAktiv.value = true
      await nextTick()
      if (videoEl.value) {
        // muted zwingend als Property (Vue setzt das Attribut nicht zuverlässig) –
        // ohne muted blockt die Autoplay-Policy den Start.
        videoEl.value.muted = true
        videoEl.value.srcObject = stream
        await videoEl.value.play()
      }
    } catch (e) {
      kameraStoppen()
      kameraFehler.value = 'Kamera nicht verfügbar: ' + (e?.message || e?.name || 'unbekannt')
    }
  }

  function kameraStoppen() {
    if (stream) {
      stream.getTracks().forEach(t => t.stop())
      stream = null
    }
    if (videoEl.value) videoEl.value.srcObject = null
    kameraAktiv.value = false
  }

  /**
   * Aktuelles Bild als JPEG-Blob. Die Kamera läuft weiter, damit man mehrere
   * Fotos hintereinander schießen kann.
   *
   * Über ein Canvas statt über ImageCapture: Das liefert rohe Pixel ohne EXIF
   * und ohne HEIC, das Bild steht also immer aufrecht und ist überall lesbar.
   */
  async function schnappschuss() {
    const video = videoEl.value
    if (!video || !video.videoWidth || !video.videoHeight) return null
    const canvas = document.createElement('canvas')
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height)
    return new Promise(res => canvas.toBlob(res, 'image/jpeg', 0.85))
  }

  return { kameraAktiv, kameraFehler, videoEl, kameraMoeglich, kameraStarten, kameraStoppen, schnappschuss }
}
