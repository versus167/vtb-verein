/* ==========================================================================
   ScanDetect — reine Bildlogik des Handy-Dokumentenscanners (OpenCV.js).

   Bewusst ohne DOM, damit sie in Node gegen dieselbe opencv.js getestet
   werden kann (tools/oneoff/scan_detect_test.js). Der Browser-Teil
   (scan.js) reicht cv.Mat rein und holt cv.Mat raus.

   Alle Funktionen nehmen `cv` als ersten Parameter. Jede intern angelegte
   cv.Mat wird hier auch wieder freigegeben — die Rückgabe-Mats gehören dem
   Aufrufer.
   ========================================================================== */
(function (root, factory) {
    if (typeof module === 'object' && module.exports) module.exports = factory();
    else root.ScanDetect = factory();
}(typeof self !== 'undefined' ? self : this, function () {
    'use strict';

    /* ── Geometrie ───────────────────────────────────────────────────────── */

    function dist(a, b) { return Math.hypot(a.x - b.x, a.y - b.y); }

    /** Vier Punkte in die Reihenfolge oben-links, oben-rechts, unten-rechts, unten-links. */
    function orderQuad(pts) {
        const s = pts.map(p => p.x + p.y);
        const d = pts.map(p => p.x - p.y);
        const idx = (arr, pick) => arr.reduce((best, v, i) => (pick(v, arr[best]) ? i : best), 0);
        const tl = idx(s, (a, b) => a < b);
        const br = idx(s, (a, b) => a > b);
        const tr = idx(d, (a, b) => a > b);
        const bl = idx(d, (a, b) => a < b);
        return [pts[tl], pts[tr], pts[br], pts[bl]].map(p => ({ x: p.x, y: p.y }));
    }

    /**
     * Plausibilität eines Vierecks als fotografiertes Blatt: keine winzigen
     * Kanten, keine extrem spitzen Ecken (35°–145°), nicht das komplette Bild.
     */
    function quadIsSane(pts, w, h) {
        if (!pts || pts.length !== 4) return false;
        const minEdge = 0.12 * Math.min(w, h);
        for (let i = 0; i < 4; i++) {
            const a = pts[i], b = pts[(i + 1) % 4], c = pts[(i + 2) % 4];
            if (dist(a, b) < minEdge) return false;
            const v1x = a.x - b.x, v1y = a.y - b.y, v2x = c.x - b.x, v2y = c.y - b.y;
            const cos = (v1x * v2x + v1y * v2y) / (Math.hypot(v1x, v1y) * Math.hypot(v2x, v2y) || 1);
            const deg = Math.acos(Math.max(-1, Math.min(1, cos))) * 180 / Math.PI;
            if (deg < 35 || deg > 145) return false;
        }
        // Berührt das Viereck alle vier Bildränder, ist es der Bildrahmen selbst.
        const xs = pts.map(p => p.x), ys = pts.map(p => p.y);
        const m = 0.015 * Math.max(w, h);
        const touchesAll = Math.min(...xs) <= m && Math.min(...ys) <= m && Math.max(...xs) >= w - m && Math.max(...ys) >= h - m;
        return !touchesAll;
    }

    /* ── Erkennung ───────────────────────────────────────────────────────── */

    /**
     * Größtes konvexes Viereck in einem (verkleinerten) RGBA- oder Grau-Bild.
     * Zwei Durchgänge: Canny-Kanten (Beleg auf beliebigem Grund), dann Otsu-
     * Schwelle (helles Papier auf dunklem Grund, wenn Kanten zu schwach sind).
     *
     * @param {object} cv   OpenCV.js
     * @param {cv.Mat} src  8UC4 oder 8UC1
     * @returns {Array<{x:number,y:number}>|null} geordnete Ecken oder null
     */
    function detectQuad(cv, src) {
        const w = src.cols, h = src.rows, imgArea = w * h;
        const gray = new cv.Mat(), blur = new cv.Mat(), work = new cv.Mat();
        let best = null, bestArea = 0;

        function scan(binary) {
            const contours = new cv.MatVector(), hier = new cv.Mat();
            try {
                cv.findContours(binary, contours, hier, cv.RETR_LIST, cv.CHAIN_APPROX_SIMPLE);
                for (let i = 0; i < contours.size(); i++) {
                    const c = contours.get(i);
                    try {
                        const area = cv.contourArea(c, false);
                        if (area < imgArea * 0.10 || area > imgArea * 0.97 || area <= bestArea) continue;
                        const approx = new cv.Mat();
                        try {
                            cv.approxPolyDP(c, approx, 0.02 * cv.arcLength(c, true), true);
                            if (approx.rows !== 4 || !cv.isContourConvex(approx)) continue;
                            const pts = [];
                            for (let k = 0; k < 4; k++) pts.push({ x: approx.data32S[k * 2], y: approx.data32S[k * 2 + 1] });
                            if (quadIsSane(pts, w, h)) { best = pts; bestArea = area; }
                        } finally { approx.delete(); }
                    } finally { c.delete(); }
                }
            } finally { contours.delete(); hier.delete(); }
        }

        try {
            if (src.channels() === 1) src.copyTo(gray);
            else cv.cvtColor(src, gray, cv.COLOR_RGBA2GRAY, 0);
            cv.GaussianBlur(gray, blur, new cv.Size(5, 5), 0, 0, cv.BORDER_DEFAULT);

            // Durchgang 1: Kanten
            cv.Canny(blur, work, 40, 120, 3, false);
            const kernel = cv.Mat.ones(3, 3, cv.CV_8U);
            try {
                cv.dilate(work, work, kernel, new cv.Point(-1, -1), 1, cv.BORDER_CONSTANT, cv.morphologyDefaultBorderValue());
            } finally { kernel.delete(); }
            scan(work);

            // Durchgang 2: Helligkeitsschwelle (Papier hell, Unterlage dunkel)
            if (!best) {
                cv.threshold(blur, work, 0, 255, cv.THRESH_BINARY + cv.THRESH_OTSU);
                scan(work);
            }
        } finally {
            gray.delete(); blur.delete(); work.delete();
        }

        return best ? orderQuad(best) : null;
    }

    /* ── Entzerren ───────────────────────────────────────────────────────── */

    /** Zielgröße aus den Kantenlängen des Vierecks, lange Kante gedeckelt. */
    function targetSize(quad, maxLong) {
        const q = orderQuad(quad);
        let w = Math.round(Math.max(dist(q[0], q[1]), dist(q[3], q[2])));
        let h = Math.round(Math.max(dist(q[0], q[3]), dist(q[1], q[2])));
        const long = Math.max(w, h);
        if (maxLong && long > maxLong) {
            const k = maxLong / long;
            w = Math.round(w * k);
            h = Math.round(h * k);
        }
        return { w: Math.max(64, w), h: Math.max(64, h), quad: q };
    }

    /**
     * Perspektivische Entzerrung: Viereck → Rechteck.
     * @returns {cv.Mat} neue Mat (gehört dem Aufrufer)
     */
    function warp(cv, src, quad, maxLong) {
        const t = targetSize(quad, maxLong);
        const q = t.quad;
        const srcPts = cv.matFromArray(4, 1, cv.CV_32FC2, [q[0].x, q[0].y, q[1].x, q[1].y, q[2].x, q[2].y, q[3].x, q[3].y]);
        const dstPts = cv.matFromArray(4, 1, cv.CV_32FC2, [0, 0, t.w, 0, t.w, t.h, 0, t.h]);
        const M = cv.getPerspectiveTransform(srcPts, dstPts);
        const dst = new cv.Mat();
        try {
            cv.warpPerspective(src, dst, M, new cv.Size(t.w, t.h), cv.INTER_LINEAR, cv.BORDER_REPLICATE, new cv.Scalar());
        } finally {
            srcPts.delete(); dstPts.delete(); M.delete();
        }
        return dst;
    }

    /* ── Filter ──────────────────────────────────────────────────────────── */

    /**
     * 'dokument': Beleuchtung ausgleichen (Hintergrund weiß), Kontrast anheben,
     *             Grautöne bleiben — ideal für Thermo-Bons und die KI-Erfassung.
     * 'sw':       harte Schwarz-Weiß-Schwelle (kleinste Datei).
     * 'farbe':    unverändert (Kopie).
     * @returns {cv.Mat} neue Mat (8UC1 bei dokument/sw, sonst wie src)
     */
    function filter(cv, src, mode) {
        if (mode === 'farbe') return src.clone();
        const gray = new cv.Mat();
        try {
            if (src.channels() === 1) src.copyTo(gray);
            else cv.cvtColor(src, gray, cv.COLOR_RGBA2GRAY, 0);

            if (mode === 'sw') {
                const bin = new cv.Mat();
                cv.adaptiveThreshold(gray, bin, 255, cv.ADAPTIVE_THRESH_GAUSSIAN_C, cv.THRESH_BINARY, 41, 15);
                return bin;
            }

            // dokument: Hintergrundhelligkeit schätzen (Schrift „zuschließen",
            // dann glätten) und das Bild dadurch teilen → Hintergrund ≈ 255.
            const bg = new cv.Mat(), norm = new cv.Mat();
            const kernel = cv.getStructuringElement(cv.MORPH_RECT, new cv.Size(21, 21), new cv.Point(-1, -1));
            try {
                cv.morphologyEx(gray, bg, cv.MORPH_CLOSE, kernel, new cv.Point(-1, -1), 1, cv.BORDER_REPLICATE, cv.morphologyDefaultBorderValue());
                cv.medianBlur(bg, bg, 21);
                cv.divide(gray, bg, norm, 255, -1);
                // Kontrast: 255 bleibt 255, alles darunter wird deutlich dunkler.
                norm.convertTo(norm, cv.CV_8U, 1.6, -153);
            } finally {
                bg.delete(); kernel.delete();
            }
            return norm;
        } finally {
            gray.delete();
        }
    }

    return { orderQuad, quadIsSane, detectQuad, targetSize, warp, filter, dist };
}));
