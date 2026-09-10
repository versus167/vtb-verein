/* ==========================================================================
   Beleg scannen — Handy-Dokumentenscanner (Ticket #197)

   Ablauf:  Kamera (Live-Rahmen um den erkannten Beleg, Auto-Auslöser)
         →  Ecken anpassen (vier Griffe, Lupe unter dem Finger wie bei Google)
         →  Seiten prüfen (Filter Dokument/Schwarz-Weiß/Farbe, drehen, löschen,
            weitere Seite)
         →  Übernehmen: Seiten als JPEG an /api/scan/beleg-pdf; der
            Server baut daraus ein PDF und gibt es zurück. Abgelegt wird es
            nicht hier, sondern mit der Rechnung — das PDF geht per
            postMessage an die App (s. showDone).

   HERKUNFT: Übernommen aus dem X1-ERP (public/js/belege/scan.js, Stand
   09.09.2026), wo dieser Scanner auf Android-Chrome und iPhone-Safari
   abgenommen wurde. Ablauf, Konstanten und die Reihenfolge in `loadOpenCv()`
   sind bewusst unverändert — was hier umständlich aussieht, ist meist eine
   bezahlte Lehre. Geändert wurden nur die Anschlüsse an unsere App:
     * kein CSRF-Token (HttpOnly-Cookie + SameSite=strict),
     * eigener, fachneutraler Endpunkt (Rechnungen, Tickets und Kasse teilen
       ihn), Antwort ist das PDF statt einer Beleg-ID,
     * „Zur Überweisung" und Projekt-Mappe entfallen (Entscheid Marko),
     * Material Icons statt Bootstrap-Icons,
     * OpenCV wird als normales <script src> geladen statt als Blob-Script.

   WARUM EIGENES DOKUMENT statt Teil der Vue-App: OpenCV.js braucht
   'unsafe-eval' und `connect-src data:` (gemessen, s. backend/main.py). Diese
   Lockerung soll nicht für die ganze App gelten, sondern an der Kante dieses
   Rahmens enden. Das Dokument sieht deshalb nur das Kamerabild und kennt
   keine Vereinsdaten. Genau so ist es auch im ERP gebaut (dort scan.php).

   Bildlogik (Erkennung, Entzerrung, Filter) liegt unverändert in
   scan-detect.js daneben und läuft komplett im Browser mit opencv.js
   (10,9 MB, einmalig geladen, danach aus dem Browser-Cache).

   OpenCV.js-Fallen:
   - Jede cv.Mat muss per delete() freigegeben werden, sonst läuft der
     WASM-Speicher voll.
   - Das Modul trägt ein altes „then" (ruft mit sich selbst zurück) — NIE als
     Promise auflösen, sonst Endlosschleife. Bereitschaft über calledRun /
     onRuntimeInitialized prüfen.
   ========================================================================== */
(function () {
    'use strict';


    const OUT_LONG_EDGE   = 2400;   // Pixel lange Kante nach der Entzerrung
    const DETECT_SIZE     = 480;    // Analyse-Größe (lange Kante) für den Live-Rahmen
    const DETECT_INTERVAL = 110;    // ms zwischen zwei Analysen (~9 Bilder/s)
    const AUTO_FRAMES     = 8;      // so viele ruhige Bilder in Folge → Auto-Auslöser
    const AUTO_TOLERANCE  = 0.022;  // erlaubte Eckbewegung, relativ zur Bildbreite
    // Ruhe im Bild (Marko 09.09.2026: „zu hektisch"): Rahmen wird über mehrere
    // Bilder geglättet, ein kurz verlorener Rahmen bleibt stehen, der Status
    // springt erst nach bestätigten Treffern um.
    const SMOOTH          = 0.4;    // Anteil des neuen Bildes an der Rahmenposition
    const LOST_GRACE      = 4;      // so viele Bilder bleibt ein verlorener Rahmen stehen
    const FOUND_CONFIRM   = 2;      // so viele Treffer in Folge, bis „erkannt" gilt
    const MIN_AREA_FRAC   = 0.15;   // Beleg muss mind. so viel vom Bild füllen
    const EDGE_MARGIN     = 0.02;   // … und Abstand zum Bildrand halten
    const HANDLE_RADIUS   = 14;     // Griff-Radius im Ecken-Editor (CSS-px)
    const GRAB_RADIUS     = 46;     // so nah muss der Finger an einen Griff
    const LOUPE_SIZE      = 140;    // Lupen-Durchmesser (CSS-px)
    const LOUPE_ZOOM      = 3;      // Vergrößerung gegenüber der Anzeige
    const JPEG_QUALITY    = 0.86;

    const $ = (id) => document.getElementById(id);
    const dom = {
        app: $('scnApp'),
        views: { camera: $('scnViewCamera'), corners: $('scnViewCorners'), pages: $('scnViewPages'), done: $('scnViewDone') },
        video: $('scnVideo'), overlay: $('scnOverlay'), stage: $('scnStage'),
        status: $('scnStatus'), statusFill: $('scnStatusFill'),
        loading: $('scnLoading'), loadingBox: null, loadingText: $('scnLoadingText'), loadingHint: $('scnLoadingHint'),
        progressBar: $('scnProgressBar'), retry: $('scnRetry'), flash: $('scnFlash'),
        autoToggle: $('scnAutoToggle'), flip: $('scnFlip'), torch: $('scnTorch'), shutter: $('scnShutter'),
        stack: $('scnStack'), stackThumb: $('scnStackThumb'), stackCount: $('scnStackCount'),
        cornerStage: $('scnCornerStage'), cornerCanvas: $('scnCornerCanvas'), loupe: $('scnLoupe'), loupeCanvas: $('scnLoupeCanvas'),
        cornersBack: $('scnCornersBack'), cornersFull: $('scnCornersFull'), cornersRetake: $('scnCornersRetake'), cornersApply: $('scnCornersApply'),
        pagesBack: $('scnPagesBack'), pagesTitle: $('scnPagesTitle'), pageDelete: $('scnPageDelete'),
        preview: $('scnPreview'), previewZoom: $('scnPreviewZoom'), previewBusy: $('scnPreviewBusy'), zoomBtn: $('scnZoomBtn'),
        pageCorners: $('scnPageCorners'),
        filter: $('scnFilter'), filterIcon: $('scnFilterIcon'), rotate: $('scnRotate'), thumbs: $('scnThumbs'),
        addPage: $('scnAddPage'), upload: $('scnUpload'),
        uploadProgress: $('scnUploadProgress'), uploadBar: $('scnUploadBar'), uploadText: $('scnUploadText'),
        doneTitle: $('scnDoneTitle'), doneText: $('scnDoneText'), next: $('scnNext'),
        toast: $('scnToast'), work: $('scnWork'),
        close: $('scnClose'), fertig: $('scnFertig'),
    };
    if (!dom.app || !window.ScanDetect) return;
    dom.loadingBox = dom.loading.querySelector('.scn-loading-box');

    const D         = window.ScanDetect;
    // Diagnose in die Browser-Konsole, wenn "scndebug" in der URL steht.
    const DEBUG     = /scndebug/.test(location.search + location.hash);
    const dbg       = (...a) => { if (DEBUG) console.log('[scan]', ...a); };
    const MAX_PAGES = parseInt(dom.app.dataset.maxPages, 10) || 20;
    // Die App haengt die App-Version als ?v= an die Adresse dieses Dokuments.
    // Sie wandert hier an die Bibliothek weiter, damit ein Austausch trotz
    // unveraenderlichem Cache eine neue URL ergibt (s. backend/main.py).
    const VERSION   = new URLSearchParams(location.search).get('v') || '';
    const OPENCV    = (dom.app.dataset.opencv || '/vendor/opencv.js')
                      + (VERSION ? '?v=' + encodeURIComponent(VERSION) : '');
    // Anhang-Grenze in MB, ebenfalls aus der Adresse. Die App kennt sie aus
    // /api/app-info, damit sie nirgends ein zweites Mal geschrieben steht. Der
    // Rückfallwert greift nur, wenn jemand dieses Dokument von Hand aufruft;
    // dann ist die Warnung eben grober.
    const MAX_MB    = parseInt(new URLSearchParams(location.search).get('max'), 10) || 20;
    const MAX_BYTES = MAX_MB * 1024 * 1024;
    // Hier entsteht nur das PDF — wohin es danach abgelegt wird, entscheidet
    // die einbettende Fläche selbst (sie bekommt es per postMessage und lädt
    // es über ihren eigenen Anhang-Weg hoch). Der Pfad ist deshalb fest und
    // muss es auch sein: Er lag einmal unter /api/rechnungen/ und verlangte
    // damit 'rechnungen.einreichen' — weshalb Tickets und Kasse den Scanner
    // nicht benutzen konnten. Jetzt liegt er neutral unter /api/scan/.
    const UPLOAD_URL = '/api/scan/beleg-pdf';

    const state = {
        cv: null, cvError: null,
        stream: null, facing: 'environment', cameraError: null,
        view: 'camera', detecting: false, lastTick: 0,
        liveQuad: null, prevQuad: null, stableCount: 0,
        lostFrames: 0, foundFrames: 0, fresh: false, frameOk: false,
        autoCapture: true, capturePause: 0,
        torch: false, torchAvailable: false,
        draft: null,      // { canvas, quad[4], detected }
        pages: [],        // { color: canvas, filter, rotation, cache:{key,canvas}, thumb }
        current: -1,
        corner: null,     // { fit:{s,ox,oy,W,H}, drag:{idx}|null }
        uploading: false,
        wakeLock: null,
        deleteArmed: 0,
        zoom: null,       // { canvas, cw, ch, ox, oy, W, H, s, tx, ty, pointers:Map, pinch, lastTap }
    };
    // Material Icons (Ligatur als Textinhalt) statt Bootstrap-Icons — die
    // Schrift liegt neben dieser Datei unter /vendor/.
    const FILTER_ICONS = { dokument: 'description', sw: 'contrast', farbe: 'palette' };
    const ZOOM_MAX = 6;
    const ZOOM_TAP = 2.5;

    /* ── Helfer ──────────────────────────────────────────────────────────── */

    function fmtSize(n) {
        if (!n) return '';
        if (n < 1024 * 1024) return (n / 1024).toFixed(0) + ' KB';
        return (n / 1024 / 1024).toFixed(1) + ' MB';
    }
    let toastTimer = 0;
    function toast(msg, type) {
        dom.toast.textContent = msg;
        dom.toast.className = 'scn-toast' + (type ? ' is-' + type : '');
        dom.toast.hidden = false;
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => { dom.toast.hidden = true; }, type === 'error' ? 4200 : 2400);
    }
    function vibrate(ms) { try { navigator.vibrate && navigator.vibrate(ms); } catch (_) { /* egal */ } }
    function flash() {
        dom.flash.classList.remove('is-on');
        void dom.flash.offsetWidth;
        dom.flash.classList.add('is-on');
    }
    function dpr() { return Math.min(window.devicePixelRatio || 1, 3); }

    async function requestWakeLock() {
        try {
            if ('wakeLock' in navigator && !state.wakeLock) {
                state.wakeLock = await navigator.wakeLock.request('screen');
                state.wakeLock.addEventListener('release', () => { state.wakeLock = null; });
            }
        } catch (_) { /* nicht überall erlaubt */ }
    }
    function releaseWakeLock() {
        try { state.wakeLock && state.wakeLock.release(); } catch (_) { /* egal */ }
        state.wakeLock = null;
    }

    function showView(name) {
        Object.entries(dom.views).forEach(([k, el]) => el.classList.toggle('is-active', k === name));
        state.view = name;
        if (name === 'camera') {
            state.capturePause = Date.now() + 1500;
            state.stableCount = 0;
            state.prevQuad = null;
            updateStack();
            requestWakeLock();
            if (!state.stream && !state.cameraError) startCamera();
            state.detecting = !!(state.cv && state.stream);
            requestAnimationFrame(() => { sizeOverlay(); drawOverlay(); });
        } else {
            state.detecting = false;
            if (name === 'done') releaseWakeLock();
        }
    }

    /* ── OpenCV laden (mit Fortschritt) ──────────────────────────────────── */

    function setLoading(text, hint, frac, error) {
        dom.loading.hidden = false;
        dom.loadingText.textContent = text;
        if (hint !== undefined) dom.loadingHint.textContent = hint;
        dom.progressBar.style.width = (Math.max(0, Math.min(1, frac || 0)) * 100) + '%';
        dom.loadingBox.classList.toggle('is-error', !!error);
        dom.retry.hidden = !error;
    }

    /** Lädt ein Skript als normales <script src> und wartet auf onload. */
    function ladeSkript(url) {
        return new Promise((resolve, reject) => {
            const s = document.createElement('script');
            s.src = url;
            s.onload = () => resolve();
            s.onerror = () => reject(new Error('Scanner-Bibliothek ist beschädigt'));
            document.head.appendChild(s);
        });
    }

    /**
     * Zieht die Datei einmal durch und meldet dabei den Fortschritt. Die Bytes
     * werden verworfen — es geht nur darum, den HTTP-Cache zu füllen und den
     * Balken zu zeigen.
     *
     * Das ERP hängt die geladenen Bytes anschließend als Blob-Script ein. Das
     * geht hier nicht: `blob:` steht auch in der gelockerten Richtlinie dieses
     * Dokuments nicht in script-src, weil genau darüber sich eine XSS-Lücke zu
     * Skriptausführung ausbaut. Der zweite Zugriff unten läuft deshalb als
     * normales <script src> und wird aus dem Cache bedient (die Datei kommt mit
     * `immutable`, s. backend/main.py). Fällt der Cache aus, lädt sie ein
     * zweites Mal — unschön, aber richtig.
     */
    async function waermeCache(url, onProgress) {
        const resp = await fetch(url, { credentials: 'same-origin' });
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const total = parseInt(resp.headers.get('Content-Length') || '0', 10);
        if (!resp.body || !resp.body.getReader) {
            const txt = await resp.text();
            onProgress(1, txt.length);
            return txt.length;
        }
        const reader = resp.body.getReader();
        let got = 0;
        for (;;) {
            const { done, value } = await reader.read();
            if (done) break;
            got += value.length;
            onProgress(total ? got / total : 0, got);
        }
        return got;
    }

    /**
     * Liefert { mod: cv } — bewusst in einem Wrapper: das OpenCV-Modul ist ein
     * altes Thenable (cv.then ruft mit cv selbst zurück). Ein Promise, das
     * direkt mit cv aufgelöst wird (auch ein `return cv` aus einer async-
     * Funktion), hängt sich in einer Endlosschleife auf.
     */
    async function loadOpenCv() {
        if (window.cv && window.cv.calledRun && window.cv.Mat) return { mod: window.cv };
        setLoading('Scanner wird geladen …', undefined, 0);
        const bytes = await waermeCache(OPENCV, (frac, got) => {
            setLoading('Scanner wird geladen … ' + (frac ? Math.round(frac * 100) + ' %' : fmtSize(got)), undefined, frac);
        });
        setLoading('Scanner startet …', undefined, 1);
        dbg('opencv geladen', bytes, 'Bytes');
        await ladeSkript(OPENCV);
        // Bereitschaft: calledRun (Modul fertig) oder onRuntimeInitialized abwarten.
        // cv.then NICHT benutzen (altes Emscripten-Thenable → Endlosschleife).
        const wrapped = await new Promise((resolve, reject) => {
            const t0 = Date.now();
            const done = (c) => resolve({ mod: c });
            (function check() {
                const c = window.cv;
                if (c && c.calledRun && c.Mat) { done(c); return; }
                if (c && !c.__scnHooked) {
                    c.__scnHooked = true;
                    const old = c.onRuntimeInitialized;
                    c.onRuntimeInitialized = function () { if (typeof old === 'function') old(); done(c); };
                }
                if (Date.now() - t0 > 90000) { reject(new Error('Scanner-Bibliothek startet nicht')); return; }
                setTimeout(check, 60);
            })();
        });
        dbg('opencv bereit');
        return wrapped;
    }

    /* ── Kamera ──────────────────────────────────────────────────────────── */

    function stopCamera() {
        if (state.stream) {
            state.stream.getTracks().forEach(t => t.stop());
            state.stream = null;
        }
        state.torch = false;
        state.torchAvailable = false;
        dom.torch.hidden = true;
        dom.torch.classList.remove('is-on');
        state.detecting = false;
        state.liveQuad = null;
        dom.shutter.disabled = true;
    }

    async function startCamera() {
        stopCamera();
        state.cameraError = null;
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            state.cameraError = 'Dieser Browser kann die Kamera nicht öffnen.';
            setLoading('Keine Kamera', state.cameraError, 0, true);
            return false;
        }
        const wish = { audio: false, video: { facingMode: { ideal: state.facing }, width: { ideal: 2560 }, height: { ideal: 1920 } } };
        try {
            state.stream = await navigator.mediaDevices.getUserMedia(wish);
        } catch (e1) {
            try {
                state.stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: { facingMode: state.facing } });
            } catch (e2) {
                state.cameraError = 'Kamera-Zugriff nicht möglich: ' + (e2 && e2.message ? e2.message : e2);
                setLoading('Kamera gesperrt', state.cameraError + ' — bitte in den Browser-Einstellungen die Kamera für diese Seite erlauben.', 0, true);
                return false;
            }
        }
        dom.video.srcObject = state.stream;
        try { await dom.video.play(); } catch (_) { /* iOS spielt nach Geste */ }
        dbg('kamera läuft', dom.video.videoWidth + 'x' + dom.video.videoHeight);
        try {
            const track = state.stream.getVideoTracks()[0];
            const caps  = track.getCapabilities ? track.getCapabilities() : null;
            if (caps && caps.focusMode && caps.focusMode.includes('continuous')) {
                await track.applyConstraints({ advanced: [{ focusMode: 'continuous' }] });
            }
            // Blitz/Taschenlampe: Android-Chrome meldet torch=true, iOS-Safari kennt es nicht.
            const torch = caps ? caps.torch : undefined;
            state.torchAvailable = torch === true || (Array.isArray(torch) && torch.includes(true));
            dbg('torch verfügbar', state.torchAvailable);
        } catch (_) { /* Fokus-/Blitz-Abfrage optional */ }
        dom.torch.hidden = !state.torchAvailable;
        return true;
    }

    async function toggleTorch() {
        if (!state.stream || !state.torchAvailable) return;
        const track = state.stream.getVideoTracks()[0];
        const wollen = !state.torch;
        try {
            await track.applyConstraints({ advanced: [{ torch: wollen }] });
            state.torch = wollen;
        } catch (e) {
            state.torch = false;
            toast('Blitz lässt sich hier nicht schalten', 'error');
        }
        dom.torch.classList.toggle('is-on', state.torch);
        dom.torch.setAttribute('aria-pressed', state.torch ? 'true' : 'false');
    }

    function flipCamera() {
        state.facing = state.facing === 'environment' ? 'user' : 'environment';
        startCamera().then(ok => { if (ok) readyCheck(); });
    }

    /** Beides da (OpenCV + Kamera)? Dann Ladeschicht weg, Auslöser frei. */
    function readyCheck() {
        dbg('readyCheck cv=' + !!state.cv + ' stream=' + !!state.stream);
        if (state.cv && state.stream) {
            dom.loading.hidden = true;
            dom.shutter.disabled = false;
            if (state.view === 'camera') state.detecting = true;
            sizeOverlay();
        }
    }

    /* ── Live-Erkennung ──────────────────────────────────────────────────── */

    function sizeOverlay() {
        const r = dom.stage.getBoundingClientRect();
        const k = dpr();
        const w = Math.round(r.width * k), h = Math.round(r.height * k);
        if (dom.overlay.width !== w || dom.overlay.height !== h) {
            dom.overlay.width = w;
            dom.overlay.height = h;
        }
    }

    /** Abbildung Video-Pixel → Anzeige (object-fit: cover). */
    function videoToDisplay() {
        const vw = dom.video.videoWidth, vh = dom.video.videoHeight;
        if (!vw || !vh) return null;
        const r = dom.stage.getBoundingClientRect();
        const s = Math.max(r.width / vw, r.height / vh);
        return { s, ox: (r.width - vw * s) / 2, oy: (r.height - vh * s) / 2, w: r.width, h: r.height };
    }

    function drawOverlay() {
        const c = dom.overlay, ctx = c.getContext('2d'), k = dpr();
        ctx.setTransform(k, 0, 0, k, 0, 0);
        ctx.clearRect(0, 0, c.width / k, c.height / k);
        const q = state.liveQuad, m = videoToDisplay();
        dom.shutter.classList.toggle('is-found', !!q);
        if (!q || !m) return;
        const pts = q.map(p => ({ x: p.x * m.s + m.ox, y: p.y * m.s + m.oy }));
        ctx.beginPath();
        pts.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
        ctx.closePath();
        ctx.fillStyle = 'rgba(153,204,51,.18)';
        ctx.fill();
        ctx.lineWidth = 3;
        ctx.lineJoin = 'round';
        ctx.strokeStyle = '#99CC33';
        ctx.stroke();
        pts.forEach(p => {
            ctx.beginPath();
            ctx.arc(p.x, p.y, 6, 0, Math.PI * 2);
            ctx.fillStyle = '#fff';
            ctx.fill();
            ctx.lineWidth = 2;
            ctx.strokeStyle = '#99CC33';
            ctx.stroke();
        });
    }

    function setStatus(st, text, frac) {
        if (dom.status.dataset.state !== st) {
            dom.status.dataset.state = st;
            dom.status.querySelector('i').textContent = st === 'search' ? 'search' : st === 'paused' ? 'pause_circle' : 'check_circle';
        }
        const span = dom.status.querySelector('span');
        if (span.textContent !== text) span.textContent = text;
        dom.statusFill.style.width = (Math.round((frac || 0) * 100)) + '%';
    }

    function analyseFrame() {
        const v = dom.video;
        const vw = v.videoWidth, vh = v.videoHeight;
        const s  = DETECT_SIZE / Math.max(vw, vh);
        const sw = Math.max(32, Math.round(vw * s)), sh = Math.max(32, Math.round(vh * s));
        const c  = dom.work;
        if (c.width !== sw || c.height !== sh) { c.width = sw; c.height = sh; }
        c.getContext('2d', { willReadFrequently: true }).drawImage(v, 0, 0, sw, sh);
        let quad = null;
        const tA = performance.now();
        const mat = state.cv.imread(c);
        try { quad = D.detectQuad(state.cv, mat); }
        catch (e) { quad = null; dbg('detectQuad Fehler', e && e.message ? e.message : e); }
        finally { mat.delete(); }
        const raw = quad ? quad.map(p => ({ x: p.x / s, y: p.y / s })) : null;
        state.fresh = !!raw;

        // Glätten: der neue Rahmen wird nur anteilig übernommen, ein kurz
        // verlorener Rahmen bleibt ein paar Bilder stehen — sonst zappelt es.
        if (raw) {
            const prev = state.liveQuad;
            const jump = prev ? Math.max(...raw.map((p, i) => Math.hypot(p.x - prev[i].x, p.y - prev[i].y))) : Infinity;
            if (!prev || jump > 0.25 * vw) {
                state.liveQuad = raw;   // erster Treffer oder anderes Objekt: direkt übernehmen
            } else {
                state.liveQuad = raw.map((p, i) => ({
                    x: prev[i].x + (p.x - prev[i].x) * SMOOTH,
                    y: prev[i].y + (p.y - prev[i].y) * SMOOTH,
                }));
            }
            state.lostFrames = 0;
            state.foundFrames++;
            state.frameOk = quadInFrame(state.liveQuad, vw, vh);
        } else {
            state.lostFrames++;
            if (state.lostFrames > LOST_GRACE) {
                state.liveQuad = null;
                state.foundFrames = 0;
                state.frameOk = false;
            }
        }
        if (DEBUG && (state.dbgFrames = (state.dbgFrames || 0) + 1) <= 5) {
            dbg('frame', state.dbgFrames, sw + 'x' + sh, Math.round(performance.now() - tA) + ' ms', quad ? JSON.stringify(quad) : 'kein Viereck');
        }
    }

    /** „Ordentlich im Rahmen": groß genug und mit Abstand zum Bildrand. */
    function quadInFrame(q, vw, vh) {
        let area = 0;
        for (let i = 0; i < q.length; i++) {
            const p = q[i], n = q[(i + 1) % q.length];
            area += p.x * n.y - n.x * p.y;
        }
        if (Math.abs(area) / 2 < MIN_AREA_FRAC * vw * vh) return false;
        const mx = EDGE_MARGIN * vw, my = EDGE_MARGIN * vh;
        return q.every(p => p.x > mx && p.x < vw - mx && p.y > my && p.y < vh - my);
    }

    function updateStability() {
        const q = state.liveQuad;
        const confirmed = !!q && state.foundFrames >= FOUND_CONFIRM;
        if (!confirmed) {
            state.stableCount = 0;
            state.prevQuad = null;
            // Kurz verlorener Rahmen (Gnadenfrist): Status noch nicht umschalten
            if (!q) setStatus('search', 'Beleg ins Bild halten', 0);
            return;
        }
        if (state.fresh) {
            if (state.prevQuad) {
                const tol = AUTO_TOLERANCE * dom.video.videoWidth;
                const moved = q.some((p, i) => Math.hypot(p.x - state.prevQuad[i].x, p.y - state.prevQuad[i].y) > tol);
                // Ein Wackler kostet ein paar Punkte, setzt aber nicht auf null zurück
                state.stableCount = moved ? Math.max(0, state.stableCount - 3) : state.stableCount + 1;
            }
            state.prevQuad = q;
        }
        if (!state.frameOk) {
            state.stableCount = 0;
            setStatus('found', 'Beleg ganz ins Bild — näher ran', 0);
            return;
        }
        if (state.autoCapture) {
            const frac = Math.min(1, state.stableCount / AUTO_FRAMES);
            setStatus('found-auto', 'Beleg erkannt — ruhig halten', frac);
            if (state.stableCount >= AUTO_FRAMES && state.fresh) {
                state.stableCount = 0;
                capture(true);
            }
        } else {
            setStatus('found', 'Beleg erkannt — auslösen', 0);
        }
    }

    function loop(ts) {
        requestAnimationFrame(loop);
        if (!state.detecting || !state.cv || !state.stream) return;
        if (dom.video.readyState < 2 || !dom.video.videoWidth) return;
        if (ts - state.lastTick < DETECT_INTERVAL) return;
        state.lastTick = ts;
        if (Date.now() < state.capturePause) {
            state.liveQuad = null;
            drawOverlay();
            setStatus('paused', 'Bereit', 0);
            return;
        }
        analyseFrame();
        drawOverlay();
        updateStability();
    }

    /* ── Aufnahme ────────────────────────────────────────────────────────── */

    function defaultQuad(w, h) {
        const ix = Math.round(w * 0.08), iy = Math.round(h * 0.08);
        return [{ x: ix, y: iy }, { x: w - ix, y: iy }, { x: w - ix, y: h - iy }, { x: ix, y: h - iy }];
    }

    /**
     * Aufnahme. Ist der Beleg sicher erkannt, wird sofort entzerrt und die Seite
     * abgelegt — kein Ecken-Editor dazwischen (Wunsch von Markos Kollegen,
     * 09.09.2026: „wie Google, ohne nochmal draufdrücken"). Ohne Erkennung geht
     * es in den Editor; und in der Seiten-Ansicht lassen sich die Ecken jeder
     * Seite nachträglich anpassen.
     */
    function capture(auto) {
        if (!state.stream || !dom.video.videoWidth || state.view !== 'camera') return;
        if (state.pages.length >= MAX_PAGES) {
            toast('Höchstens ' + MAX_PAGES + ' Seiten je Beleg', 'error');
            return;
        }
        state.capturePause = Date.now() + 3000;
        const c = document.createElement('canvas');
        c.width = dom.video.videoWidth;
        c.height = dom.video.videoHeight;
        c.getContext('2d').drawImage(dom.video, 0, 0);
        flash();
        vibrate(35);
        const detected = !!state.liveQuad && state.foundFrames >= FOUND_CONFIRM;
        const quad = detected ? state.liveQuad.map(p => ({ x: p.x, y: p.y })) : null;
        state.draft = { canvas: c, quad: quad || defaultQuad(c.width, c.height), detected, pageIndex: null };
        state.liveQuad = null;
        state.prevQuad = null;
        state.foundFrames = 0;
        state.stableCount = 0;
        drawOverlay();
        if (detected) {
            applyDraft();
            toast(auto ? 'Automatisch erfasst' : 'Seite erfasst', 'success');
        } else {
            showView('corners');
            initCornerView();
        }
    }

    /* ── Ecken-Editor mit Lupe ───────────────────────────────────────────── */

    function initCornerView() {
        state.corner = { fit: null, drag: null };
        dom.loupe.hidden = true;
        layoutCornerView();
        drawCornerView();
        const editing = state.draft.pageIndex !== null && state.draft.pageIndex !== undefined;
        dom.cornersRetake.hidden = editing;
        const hint = document.getElementById('scnCornerHint');
        if (hint) {
            hint.innerHTML = editing
                ? '<i class="material-icons">touch_app</i> Ecken nachziehen — Übernehmen entzerrt die Seite neu.'
                : (state.draft.detected
                    ? '<i class="material-icons">touch_app</i> Ecken ziehen — die Lupe zeigt die Kante genau.'
                    : '<i class="material-icons">error_outline</i> Kein Beleg erkannt — Ecken bitte von Hand auf die Blattecken ziehen.');
        }
    }

    function layoutCornerView() {
        const r = dom.cornerStage.getBoundingClientRect();
        const k = dpr();
        dom.cornerCanvas.width = Math.round(r.width * k);
        dom.cornerCanvas.height = Math.round(r.height * k);
        const img = state.draft.canvas;
        const pad = 26;
        const s = Math.min((r.width - pad * 2) / img.width, (r.height - pad * 2) / img.height);
        state.corner.fit = { s, ox: (r.width - img.width * s) / 2, oy: (r.height - img.height * s) / 2, W: r.width, H: r.height };
    }

    const toDisp = (p) => { const f = state.corner.fit; return { x: p.x * f.s + f.ox, y: p.y * f.s + f.oy }; };
    const toImg  = (x, y) => { const f = state.corner.fit; return { x: (x - f.ox) / f.s, y: (y - f.oy) / f.s }; };

    function drawCornerView() {
        const c = dom.cornerCanvas, ctx = c.getContext('2d'), k = dpr();
        const f = state.corner.fit, img = state.draft.canvas, quad = state.draft.quad;
        ctx.setTransform(k, 0, 0, k, 0, 0);
        ctx.fillStyle = '#0e0e0e';
        ctx.fillRect(0, 0, f.W, f.H);
        ctx.drawImage(img, f.ox, f.oy, img.width * f.s, img.height * f.s);

        const pts = quad.map(toDisp);
        // Außerhalb abdunkeln
        ctx.save();
        ctx.beginPath();
        ctx.rect(0, 0, f.W, f.H);
        pts.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
        ctx.closePath();
        ctx.fillStyle = 'rgba(0,0,0,.5)';
        ctx.fill('evenodd');
        ctx.restore();
        // Rahmen
        ctx.beginPath();
        pts.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
        ctx.closePath();
        ctx.lineWidth = 2.5;
        ctx.lineJoin = 'round';
        ctx.strokeStyle = '#99CC33';
        ctx.stroke();
        // Griffe
        pts.forEach((p, i) => {
            const active = state.corner.drag && state.corner.drag.idx === i;
            ctx.beginPath();
            ctx.arc(p.x, p.y, active ? HANDLE_RADIUS + 4 : HANDLE_RADIUS, 0, Math.PI * 2);
            ctx.fillStyle = active ? 'rgba(153,204,51,.95)' : 'rgba(255,255,255,.95)';
            ctx.fill();
            ctx.lineWidth = 3;
            ctx.strokeStyle = active ? '#fff' : '#99CC33';
            ctx.stroke();
        });
    }

    function drawLoupe(idx, fx, fy) {
        const L = LOUPE_SIZE, k = dpr();
        const lc = dom.loupeCanvas;
        if (lc.width !== L * k) { lc.width = L * k; lc.height = L * k; }
        const ctx = lc.getContext('2d');
        const f = state.corner.fit, img = state.draft.canvas, quad = state.draft.quad;
        const c = quad[idx];
        const zoom = f.s * LOUPE_ZOOM;       // Anzeige-Pixel je Bild-Pixel in der Lupe
        const r = (L / 2) / zoom;            // Radius in Bild-Pixeln
        ctx.setTransform(k, 0, 0, k, 0, 0);
        ctx.save();
        ctx.beginPath();
        ctx.arc(L / 2, L / 2, L / 2, 0, Math.PI * 2);
        ctx.clip();
        ctx.fillStyle = '#000';
        ctx.fillRect(0, 0, L, L);
        ctx.imageSmoothingEnabled = true;
        // Quellrechteck in Bild-Pixeln um die Ecke, auf Bildgrenzen zugeschnitten
        const sx = Math.max(0, c.x - r), sy = Math.max(0, c.y - r);
        const ex = Math.min(img.width, c.x + r), ey = Math.min(img.height, c.y + r);
        if (ex > sx && ey > sy) {
            ctx.drawImage(img, sx, sy, ex - sx, ey - sy,
                (sx - (c.x - r)) * zoom, (sy - (c.y - r)) * zoom, (ex - sx) * zoom, (ey - sy) * zoom);
        }
        // Die beiden Kanten, die an dieser Ecke hängen
        const tp = (p) => ({ x: (p.x - c.x) * zoom + L / 2, y: (p.y - c.y) * zoom + L / 2 });
        ctx.lineWidth = 2;
        ctx.strokeStyle = '#99CC33';
        [quad[(idx + 3) % 4], quad[(idx + 1) % 4]].forEach(n => {
            const a = tp(n);
            ctx.beginPath();
            ctx.moveTo(L / 2, L / 2);
            ctx.lineTo(a.x, a.y);
            ctx.stroke();
        });
        // Fadenkreuz
        ctx.lineWidth = 1;
        ctx.strokeStyle = 'rgba(255,255,255,.9)';
        ctx.beginPath();
        ctx.moveTo(L / 2 - 16, L / 2); ctx.lineTo(L / 2 + 16, L / 2);
        ctx.moveTo(L / 2, L / 2 - 16); ctx.lineTo(L / 2, L / 2 + 16);
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(L / 2, L / 2, 4, 0, Math.PI * 2);
        ctx.fillStyle = '#99CC33';
        ctx.fill();
        ctx.restore();

        // Position: über dem Finger, sonst darunter; seitlich im Bild halten
        let left = fx - L / 2, top = fy - L - 34;
        if (top < 6) top = fy + 34;
        left = Math.max(6, Math.min(f.W - L - 6, left));
        dom.loupe.style.left = left + 'px';
        dom.loupe.style.top = top + 'px';
        dom.loupe.hidden = false;
    }

    function cornerPointer(e) {
        const r = dom.cornerCanvas.getBoundingClientRect();
        return { x: e.clientX - r.left, y: e.clientY - r.top };
    }

    function onCornerDown(e) {
        if (!state.draft || !state.corner) return;
        const p = cornerPointer(e);
        let best = -1, bestD = GRAB_RADIUS;
        state.draft.quad.map(toDisp).forEach((d, i) => {
            const dd = Math.hypot(d.x - p.x, d.y - p.y);
            if (dd < bestD) { bestD = dd; best = i; }
        });
        if (best < 0) return;
        e.preventDefault();
        state.corner.drag = { idx: best, pointerId: e.pointerId };
        try { dom.cornerCanvas.setPointerCapture(e.pointerId); } catch (_) { /* egal */ }
        drawCornerView();
        drawLoupe(best, p.x, p.y);
    }

    function onCornerMove(e) {
        const d = state.corner && state.corner.drag;
        if (!d || d.pointerId !== e.pointerId) return;
        e.preventDefault();
        const p = cornerPointer(e);
        const img = state.draft.canvas;
        const ip = toImg(p.x, p.y);
        state.draft.quad[d.idx] = {
            x: Math.max(0, Math.min(img.width, ip.x)),
            y: Math.max(0, Math.min(img.height, ip.y)),
        };
        drawCornerView();
        drawLoupe(d.idx, p.x, p.y);
    }

    function onCornerUp(e) {
        const d = state.corner && state.corner.drag;
        if (!d || d.pointerId !== e.pointerId) return;
        state.corner.drag = null;
        dom.loupe.hidden = true;
        try { dom.cornerCanvas.releasePointerCapture(e.pointerId); } catch (_) { /* egal */ }
        drawCornerView();
    }

    function cornersFullFrame() {
        const c = state.draft.canvas;
        state.draft.quad = [{ x: 0, y: 0 }, { x: c.width, y: 0 }, { x: c.width, y: c.height }, { x: 0, y: c.height }];
        drawCornerView();
    }

    function discardDraft() {
        const idx = state.draft ? state.draft.pageIndex : null;
        state.draft = null;
        if (idx !== null && idx !== undefined) {
            showView('pages');
            renderPages();
        } else {
            showView('camera');
        }
    }

    /** JPEG-Blob → Canvas (fürs Nachziehen der Ecken einer schon abgelegten Seite). */
    async function blobToCanvas(blob) {
        const c = document.createElement('canvas');
        if (typeof createImageBitmap === 'function') {
            const bmp = await createImageBitmap(blob);
            c.width = bmp.width; c.height = bmp.height;
            c.getContext('2d').drawImage(bmp, 0, 0);
            if (bmp.close) bmp.close();
            return c;
        }
        const url = URL.createObjectURL(blob);
        try {
            const img = await new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = url; });
            c.width = img.naturalWidth; c.height = img.naturalHeight;
            c.getContext('2d').drawImage(img, 0, 0);
            return c;
        } finally {
            URL.revokeObjectURL(url);
        }
    }

    /** Ecken einer bereits abgelegten Seite nachträglich anpassen. */
    async function editCorners() {
        const idx = state.current;
        const page = state.pages[idx];
        if (!page) return;
        if (!page.sourceBlob) { toast('Original wird noch gesichert — gleich nochmal'); return; }
        dom.previewBusy.hidden = false;
        try {
            const canvas = await blobToCanvas(page.sourceBlob);
            state.draft = { canvas, quad: page.sourceQuad.map(p => ({ x: p.x, y: p.y })), detected: true, pageIndex: idx };
            showView('corners');
            initCornerView();
        } catch (e) {
            toast('Original konnte nicht geladen werden', 'error');
        } finally {
            dom.previewBusy.hidden = true;
        }
    }

    /* ── Bildverarbeitung ────────────────────────────────────────────────── */

    function matToCanvas(mat) {
        const c = document.createElement('canvas');
        c.width = mat.cols;
        c.height = mat.rows;
        state.cv.imshow(c, mat);
        return c;
    }

    function warpDraft() {
        const cv = state.cv;
        const src = cv.imread(state.draft.canvas);
        let dst = null;
        try {
            dst = D.warp(cv, src, state.draft.quad, OUT_LONG_EDGE);
            return matToCanvas(dst);
        } finally {
            src.delete();
            if (dst) dst.delete();
        }
    }

    function filteredCanvas(page) {
        if (page.filter === 'farbe') return page.color;
        const key = page.filter;
        if (page.cache && page.cache.key === key) return page.cache.canvas;
        const cv = state.cv;
        const src = cv.imread(page.color);
        let out = null;
        try {
            out = D.filter(cv, src, page.filter);
            const canvas = matToCanvas(out);
            page.cache = { key, canvas };
            return canvas;
        } finally {
            src.delete();
            if (out) out.delete();
        }
    }

    function rotateCanvas(src, deg) {
        if (!deg) return src;
        const swap = deg % 180 !== 0;
        const c = document.createElement('canvas');
        c.width = swap ? src.height : src.width;
        c.height = swap ? src.width : src.height;
        const ctx = c.getContext('2d');
        ctx.translate(c.width / 2, c.height / 2);
        ctx.rotate(deg * Math.PI / 180);
        ctx.drawImage(src, -src.width / 2, -src.height / 2);
        return c;
    }

    /** Fertige Seite (Filter + Drehung) — Ergebnis wird je Seite gecacht. */
    function finalCanvas(page) {
        const key = page.filter + '|' + page.rotation;
        if (page.final && page.final.key === key) return page.final.canvas;
        const canvas = rotateCanvas(filteredCanvas(page), page.rotation);
        page.final = { key, canvas };
        return canvas;
    }

    function makeThumb(src, w, h) {
        const t = document.createElement('canvas');
        t.width = w; t.height = h;
        const ctx = t.getContext('2d');
        ctx.fillStyle = '#222';
        ctx.fillRect(0, 0, w, h);
        const s = Math.min(w / src.width, h / src.height);
        const dw = src.width * s, dh = src.height * s;
        ctx.drawImage(src, (w - dw) / 2, (h - dh) / 2, dw, dh);
        return t;
    }

    /**
     * Entwurf (Foto + Ecken) entzerren und als Seite ablegen — oder, beim
     * Nachziehen der Ecken, die bestehende Seite neu entzerren. Das Original
     * wird als JPEG aufgehoben (viel kleiner als ein Canvas), damit die Ecken
     * später noch einmal angefasst werden können.
     */
    function applyDraft() {
        if (!state.draft) return;
        const draft = state.draft;
        dom.cornersApply.disabled = true;
        dom.previewBusy.hidden = false;
        showView('pages');
        setTimeout(() => {
            try {
                const color = warpDraft();
                const quadCopy = draft.quad.map(p => ({ x: p.x, y: p.y }));
                const editing = draft.pageIndex !== null && draft.pageIndex !== undefined && state.pages[draft.pageIndex];
                if (editing) {
                    const page = state.pages[draft.pageIndex];
                    page.color = color;
                    page.cache = null;
                    page.final = null;
                    page.thumb = null;
                    page.sourceQuad = quadCopy;
                    state.current = draft.pageIndex;
                } else {
                    const page = { color, filter: 'dokument', rotation: 0, cache: null, final: null, thumb: null,
                                   sourceBlob: null, sourceQuad: quadCopy };
                    state.pages.push(page);
                    state.current = state.pages.length - 1;
                    draft.canvas.toBlob(b => { page.sourceBlob = b; }, 'image/jpeg', 0.92);
                }
                state.draft = null;
                renderPages();
            } catch (e) {
                toast('Entzerren fehlgeschlagen: ' + (e && e.message ? e.message : e), 'error');
                showView('corners');
            } finally {
                dom.cornersApply.disabled = false;
                dom.previewBusy.hidden = true;
            }
        }, 30);
    }

    /* ── Seiten prüfen ───────────────────────────────────────────────────── */

    function renderPages() {
        const n = state.pages.length;
        if (!n) { showView('camera'); return; }
        if (state.current < 0 || state.current >= n) state.current = n - 1;
        dom.pagesTitle.textContent = n === 1 ? 'Beleg prüfen' : 'Seite ' + (state.current + 1) + ' von ' + n;
        const page = state.pages[state.current];
        dom.filter.value = page.filter;
        dom.filterIcon.textContent = FILTER_ICONS[page.filter] || FILTER_ICONS.dokument;
        dom.previewBusy.hidden = false;
        setTimeout(() => {
            try {
                drawPreview(page);
                page.thumb = makeThumb(finalCanvas(page), 104, 132);
                renderThumbs();
            } finally {
                dom.previewBusy.hidden = true;
            }
        }, 20);
    }

    /**
     * Vorschau: das fertige Canvas selbst (volle Auflösung) wird eingehängt und
     * per CSS-Transform eingepasst — so bleibt es beim Zoomen scharf.
     */
    function drawPreview(page) {
        const src = finalCanvas(page);
        const box = dom.preview.getBoundingClientRect();
        const W = Math.max(100, box.width), H = Math.max(100, box.height);
        const pad = 8;
        const fit = Math.min((W - pad * 2) / src.width, (H - pad * 2) / src.height);
        const cw = src.width * fit, ch = src.height * fit;
        if (src.parentNode !== dom.previewZoom) {
            dom.previewZoom.innerHTML = '';
            dom.previewZoom.appendChild(src);
        }
        src.style.width = cw + 'px';
        src.style.height = ch + 'px';
        state.zoom = {
            canvas: src, cw, ch, W, H,
            ox: (W - cw) / 2, oy: (H - ch) / 2,
            s: 1, tx: 0, ty: 0,
            pointers: new Map(), pinch: null, lastTap: 0, lastTapX: 0, lastTapY: 0,
        };
        applyZoom();
    }

    function applyZoom() {
        const z = state.zoom;
        if (!z) return;
        // Bild im Kasten halten: kleiner als der Kasten → zentriert, sonst ohne Rand
        const vw = z.cw * z.s, vh = z.ch * z.s;
        if (vw <= z.W) z.tx = (z.W - vw) / 2 - z.ox;
        else z.tx = Math.min(-z.ox, Math.max(z.W - vw - z.ox, z.tx));
        if (vh <= z.H) z.ty = (z.H - vh) / 2 - z.oy;
        else z.ty = Math.min(-z.oy, Math.max(z.H - vh - z.oy, z.ty));
        z.canvas.style.transform = 'translate(' + (z.ox + z.tx) + 'px,' + (z.oy + z.ty) + 'px) scale(' + z.s + ')';
        const zoomed = z.s > 1.01;
        dom.preview.classList.toggle('is-zoomed', zoomed);
        dom.zoomBtn.innerHTML = '<i class="material-icons">' + (zoomed ? 'zoom_out' : 'zoom_in') + '</i>';
        dom.zoomBtn.title = zoomed ? 'Zoom zurücksetzen' : 'Vergrößern';
    }

    /** Auf Faktor `s` zoomen, wobei der Anzeigepunkt (px,py) an Ort und Stelle bleibt. */
    function zoomAt(s, px, py) {
        const z = state.zoom;
        if (!z) return;
        s = Math.max(1, Math.min(ZOOM_MAX, s));
        // Bildkoordinate unter dem Punkt (in Anzeige-Einheiten bei Skala 1)
        const ix = (px - z.ox - z.tx) / z.s, iy = (py - z.oy - z.ty) / z.s;
        z.s = s;
        z.tx = px - z.ox - ix * s;
        z.ty = py - z.oy - iy * s;
        applyZoom();
    }

    function zoomReset() {
        if (!state.zoom) return;
        state.zoom.s = 1;
        state.zoom.tx = 0;
        state.zoom.ty = 0;
        applyZoom();
    }

    function previewPoint(e) {
        const r = dom.preview.getBoundingClientRect();
        return { x: e.clientX - r.left, y: e.clientY - r.top };
    }

    function onPreviewDown(e) {
        const z = state.zoom;
        if (!z || e.target === dom.zoomBtn || dom.zoomBtn.contains(e.target)) return;
        e.preventDefault();
        try { dom.preview.setPointerCapture(e.pointerId); } catch (_) { /* egal */ }
        const p = previewPoint(e);
        z.pointers.set(e.pointerId, { x: p.x, y: p.y, sx: p.x, sy: p.y, moved: false });
        if (z.pointers.size === 2) {
            const [a, b] = [...z.pointers.values()];
            z.pinch = {
                dist: Math.hypot(a.x - b.x, a.y - b.y) || 1,
                s: z.s,
                mid: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 },
                // Bildpunkt unter der Mitte (Anzeige-Einheiten bei Skala 1)
                ix: ((a.x + b.x) / 2 - z.ox - z.tx) / z.s,
                iy: ((a.y + b.y) / 2 - z.oy - z.ty) / z.s,
            };
        }
    }

    function onPreviewMove(e) {
        const z = state.zoom;
        if (!z) return;
        const pt = z.pointers.get(e.pointerId);
        if (!pt) return;
        e.preventDefault();
        const p = previewPoint(e);
        const dx = p.x - pt.x, dy = p.y - pt.y;
        pt.x = p.x; pt.y = p.y;
        if (Math.hypot(p.x - pt.sx, p.y - pt.sy) > 6) pt.moved = true;
        if (z.pointers.size >= 2 && z.pinch) {
            const [a, b] = [...z.pointers.values()];
            const dist = Math.hypot(a.x - b.x, a.y - b.y) || 1;
            const mid  = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
            z.s  = Math.max(1, Math.min(ZOOM_MAX, z.pinch.s * dist / z.pinch.dist));
            z.tx = mid.x - z.ox - z.pinch.ix * z.s;
            z.ty = mid.y - z.oy - z.pinch.iy * z.s;
            applyZoom();
        } else if (z.pointers.size === 1 && z.s > 1) {
            z.tx += dx;
            z.ty += dy;
            applyZoom();
        }
    }

    function onPreviewUp(e) {
        const z = state.zoom;
        if (!z) return;
        const pt = z.pointers.get(e.pointerId);
        z.pointers.delete(e.pointerId);
        if (z.pointers.size < 2) z.pinch = null;
        try { dom.preview.releasePointerCapture(e.pointerId); } catch (_) { /* egal */ }
        if (!pt || pt.moved || e.type === 'pointercancel') return;
        // Doppeltipp: rein auf 2,5× an der Stelle, bzw. wieder raus
        const now = Date.now();
        const p = previewPoint(e);
        if (now - z.lastTap < 320 && Math.hypot(p.x - z.lastTapX, p.y - z.lastTapY) < 40) {
            z.lastTap = 0;
            if (z.s > 1.01) zoomReset(); else zoomAt(ZOOM_TAP, p.x, p.y);
        } else {
            z.lastTap = now; z.lastTapX = p.x; z.lastTapY = p.y;
        }
    }

    function onPreviewWheel(e) {
        const z = state.zoom;
        if (!z) return;
        e.preventDefault();
        const p = previewPoint(e);
        zoomAt(z.s * (e.deltaY < 0 ? 1.2 : 1 / 1.2), p.x, p.y);
    }

    function renderThumbs() {
        dom.thumbs.innerHTML = '';
        if (state.pages.length < 2) return;
        state.pages.forEach((p, i) => {
            const b = document.createElement('button');
            b.type = 'button';
            b.className = 'scn-thumb' + (i === state.current ? ' is-current' : '');
            b.title = 'Seite ' + (i + 1);
            if (p.thumb) b.appendChild(p.thumb);
            const nr = document.createElement('span');
            nr.className = 'scn-thumb-nr';
            nr.textContent = String(i + 1);
            b.appendChild(nr);
            b.addEventListener('click', () => { state.current = i; renderPages(); });
            dom.thumbs.appendChild(b);
        });
    }

    function setFilter(f) {
        const page = state.pages[state.current];
        if (!page || page.filter === f) return;
        page.filter = f;
        page.final = null;
        renderPages();
    }

    function rotateCurrent() {
        const page = state.pages[state.current];
        if (!page) return;
        page.rotation = (page.rotation + 90) % 360;
        page.final = null;
        renderPages();
    }

    function deleteCurrent() {
        const page = state.pages[state.current];
        if (!page) return;
        const now = Date.now();
        if (now - state.deleteArmed > 3000) {
            state.deleteArmed = now;
            toast('Nochmal tippen, um die Seite zu löschen');
            return;
        }
        state.deleteArmed = 0;
        state.pages.splice(state.current, 1);
        state.current = Math.min(state.current, state.pages.length - 1);
        toast('Seite gelöscht');
        if (!state.pages.length) { showView('camera'); return; }
        renderPages();
    }

    function updateStack() {
        const n = state.pages.length;
        dom.stack.hidden = n === 0;
        if (!n) return;
        dom.stackCount.textContent = String(n);
        const last = state.pages[n - 1];
        const t = dom.stackThumb, ctx = t.getContext('2d');
        ctx.fillStyle = '#222';
        ctx.fillRect(0, 0, t.width, t.height);
        const src = last.thumb || finalCanvas(last);
        const s = Math.min(t.width / src.width, t.height / src.height);
        const dw = src.width * s, dh = src.height * s;
        ctx.drawImage(src, (t.width - dw) / 2, (t.height - dh) / 2, dw, dh);
    }

    /* ── Hochladen ───────────────────────────────────────────────────────── */

    function showUploadProgress(frac, text) {
        dom.uploadProgress.hidden = false;
        dom.uploadBar.style.width = (Math.round(frac * 100)) + '%';
        dom.uploadText.textContent = text;
    }

    /**
     * Schickt die Seiten in EINEM Request und bekommt das fertige PDF zurück.
     *
     * Alle Seiten zusammen, nicht einzeln: Bricht die Übertragung ab, gibt es
     * keinen halben Beleg, und die Seitenreihenfolge hängt nicht am Zufall der
     * Antwortzeiten. Kein CSRF-Token — die App fährt ein HttpOnly-Cookie mit
     * SameSite=strict, `withCredentials` genügt. Das Cookie gilt auch hier:
     * Dieses Dokument hat dieselbe Herkunft wie die App, es steckt nur in
     * einem eigenen Rahmen.
     */
    function xhrUpload(url, fd, onProgress) {
        return new Promise((resolve) => {
            const xhr = new XMLHttpRequest();
            xhr.open('POST', url, true);
            xhr.responseType = 'blob';
            xhr.withCredentials = true;
            xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total); };
            xhr.onload = async () => {
                if (xhr.status >= 200 && xhr.status < 300) {
                    resolve({ ok: true, blob: xhr.response });
                    return;
                }
                let meldung = 'Der Beleg konnte nicht erzeugt werden (HTTP ' + xhr.status + ').';
                if (xhr.status === 401) meldung = 'Nicht mehr angemeldet — bitte neu anmelden.';
                try {
                    const detail = JSON.parse(await xhr.response.text())?.detail;
                    if (typeof detail === 'string') meldung = detail;
                } catch (_) { /* dann bleibt es beim Standardtext */ }
                resolve({ ok: false, message: meldung });
            };
            xhr.onerror = () => resolve({ ok: false, message: 'Netzwerkfehler beim Hochladen' });
            xhr.ontimeout = () => resolve({ ok: false, message: 'Zeitüberschreitung beim Hochladen' });
            xhr.timeout = 180000;
            xhr.send(fd);
        });
    }

    async function upload() {
        if (state.uploading || !state.pages.length) return;
        state.uploading = true;
        dom.upload.disabled = true;
        showUploadProgress(0, 'Seiten werden vorbereitet …');
        try {
            const fd = new FormData();
            let total = 0;
            for (let i = 0; i < state.pages.length; i++) {
                const c = finalCanvas(state.pages[i]);
                const blob = await new Promise(res => c.toBlob(res, 'image/jpeg', JPEG_QUALITY));
                if (!blob) throw new Error('Seite ' + (i + 1) + ' konnte nicht kodiert werden');
                total += blob.size;
                fd.append('pages', blob, 'seite-' + (i + 1) + '.jpg');
                showUploadProgress(0, 'Seite ' + (i + 1) + ' von ' + state.pages.length + ' vorbereitet');
            }
            // Wiegen, bevor es losgeht. Der Server prüft dasselbe noch einmal
            // (er hat die verbindliche Grenze), aber hier ist der Nutzer noch
            // bei seinen Seiten: Er kann eine löschen oder den Filter wechseln,
            // ohne dass erst alles über die Mobilfunkleitung gegangen ist.
            if (total > MAX_BYTES) {
                const filterHinweis = dom.filter.value === 'farbe'
                    ? ' Filter „Dokument“ statt „Farbe“ wiegt etwa ein Fünftel.'
                    : ' Am besten eine Seite löschen.';
                throw new Error('Der Beleg ist mit ' + fmtSize(total) + ' größer als die '
                                + 'erlaubten ' + MAX_MB + ' MB.' + filterHinweis);
            }
            const res = await xhrUpload(UPLOAD_URL, fd, (frac) => {
                showUploadProgress(frac, 'Wird übertragen … ' + Math.round(frac * 100) + ' % von ' + fmtSize(total));
            });
            if (!res || !res.ok) throw new Error((res && res.message) || 'Upload fehlgeschlagen');
            showDone(res.blob, state.pages.length);
        } catch (e) {
            toast(e && e.message ? e.message : String(e), 'error');
        } finally {
            dom.uploadProgress.hidden = true;
            dom.upload.disabled = false;
            state.uploading = false;
        }
    }

    /**
     * Der Beleg ist fertig, aber noch nicht abgelegt: Er geht per postMessage
     * an die App, hängt dort am Rechnungs-Dialog wie eine selbst gewählte Datei
     * und wandert mit dem Speichern in die Ablage. Deshalb steht hier
     * „übernommen" und nicht „im Eingang" wie im ERP.
     *
     * Ziel-Herkunft ausdrücklich die eigene: Ein `'*'` würde das PDF an jede
     * Seite ausliefern, die dieses Dokument einbettet.
     */
    function showDone(pdf, seiten) {
        const name = 'beleg-scan-' + new Date().toISOString().slice(0, 10) + '.pdf';
        const datei = new File([pdf], name, { type: 'application/pdf' });
        dom.doneTitle.textContent = 'Beleg übernommen';
        dom.doneText.textContent =
            (seiten === 1 ? '1 Seite' : seiten + ' Seiten') + ' · ' + fmtSize(datei.size)
            + '. Der Beleg hängt jetzt an der Rechnung und wird mit ihr gespeichert.';
        vibrate([30, 60, 30]);
        showView('done');
        try {
            parent.postMessage({ typ: 'vtb-beleg-scan', datei: datei, seiten: seiten },
                               location.origin);
        } catch (e) {
            toast('Der Beleg konnte nicht an die Rechnung übergeben werden.', 'error');
        }
    }

    function nextBeleg() {
        state.pages = [];
        state.current = -1;
        state.draft = null;
        dom.thumbs.innerHTML = '';
        showView('camera');
    }

    /* ── Ereignisse ──────────────────────────────────────────────────────── */

    dom.shutter.addEventListener('click', () => capture());
    dom.flip.addEventListener('click', flipCamera);
    dom.torch.addEventListener('click', toggleTorch);
    dom.autoToggle.addEventListener('click', () => {
        state.autoCapture = !state.autoCapture;
        dom.autoToggle.classList.toggle('is-on', state.autoCapture);
        dom.autoToggle.setAttribute('aria-pressed', state.autoCapture ? 'true' : 'false');
        try { localStorage.setItem('vtb-scan-auto', state.autoCapture ? '1' : '0'); } catch (_) { /* egal */ }
        toast(state.autoCapture ? 'Auto-Auslöser an' : 'Auto-Auslöser aus — selbst auslösen');
        state.stableCount = 0;
    });
    dom.stack.addEventListener('click', () => { if (state.pages.length) { showView('pages'); renderPages(); } });
    dom.retry.addEventListener('click', () => boot());

    // Zurück zur Rechnung. Das Dokument kann sich nicht selbst schließen — es
    // steckt im Rahmen der App, die den Dialog hält. Also Bescheid sagen.
    function schliessenMelden() {
        stopCamera();
        releaseWakeLock();
        try {
            parent.postMessage({ typ: 'vtb-beleg-scan-schliessen' }, location.origin);
        } catch (_) { /* dann bleibt der Dialog offen, der Nutzer hat den Rahmen-Knopf */ }
    }
    dom.close.addEventListener('click', schliessenMelden);
    dom.fertig.addEventListener('click', schliessenMelden);

    dom.cornerCanvas.addEventListener('pointerdown', onCornerDown);
    dom.cornerCanvas.addEventListener('pointermove', onCornerMove);
    dom.cornerCanvas.addEventListener('pointerup', onCornerUp);
    dom.cornerCanvas.addEventListener('pointercancel', onCornerUp);
    dom.cornersBack.addEventListener('click', discardDraft);
    dom.cornersRetake.addEventListener('click', discardDraft);
    dom.cornersFull.addEventListener('click', cornersFullFrame);
    dom.cornersApply.addEventListener('click', applyDraft);
    dom.pageCorners.addEventListener('click', editCorners);

    dom.pagesBack.addEventListener('click', () => showView('camera'));
    dom.addPage.addEventListener('click', () => showView('camera'));
    dom.pageDelete.addEventListener('click', deleteCurrent);
    dom.rotate.addEventListener('click', rotateCurrent);
    dom.filter.addEventListener('change', () => setFilter(dom.filter.value));
    dom.zoomBtn.addEventListener('click', () => {
        const z = state.zoom;
        if (!z) return;
        if (z.s > 1.01) zoomReset(); else zoomAt(ZOOM_TAP, z.W / 2, z.H / 2);
    });
    dom.preview.addEventListener('pointerdown', onPreviewDown);
    dom.preview.addEventListener('pointermove', onPreviewMove);
    dom.preview.addEventListener('pointerup', onPreviewUp);
    dom.preview.addEventListener('pointercancel', onPreviewUp);
    dom.preview.addEventListener('wheel', onPreviewWheel, { passive: false });
    dom.upload.addEventListener('click', upload);
    dom.next.addEventListener('click', nextBeleg);

    window.addEventListener('resize', () => {
        if (state.view === 'camera') { sizeOverlay(); drawOverlay(); }
        else if (state.view === 'corners' && state.draft) { layoutCornerView(); drawCornerView(); }
        else if (state.view === 'pages' && state.pages[state.current]) { drawPreview(state.pages[state.current]); }
    });
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
            stopCamera();
            releaseWakeLock();
        } else if (state.view === 'camera' || state.view === 'corners' || state.view === 'pages') {
            startCamera().then(ok => { if (ok) { readyCheck(); if (state.view === 'camera') requestWakeLock(); } });
        }
    });

    /* ── Start ───────────────────────────────────────────────────────────── */

    try { state.autoCapture = localStorage.getItem('vtb-scan-auto') !== '0'; } catch (_) { /* egal */ }
    dom.autoToggle.classList.toggle('is-on', state.autoCapture);
    dom.autoToggle.setAttribute('aria-pressed', state.autoCapture ? 'true' : 'false');

    async function boot() {
        dom.retry.hidden = true;
        dom.loadingBox.classList.remove('is-error');
        const cam = startCamera();
        try {
            state.cv = (await loadOpenCv()).mod;
        } catch (e) {
            state.cvError = e;
            setLoading('Scanner konnte nicht geladen werden', (e && e.message ? e.message : String(e)) + ' — Verbindung prüfen und nochmal versuchen.', 0, true);
            return;
        }
        const ok = await cam;
        if (!ok) return;
        readyCheck();
    }

    requestAnimationFrame(loop);
    boot();
})();
