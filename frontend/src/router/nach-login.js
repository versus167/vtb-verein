// Nach erfolgreicher Anmeldung MUSS die Übersicht erscheinen (bzw. das gemerkte
// Ziel, s. merkeZiel). Passiert das nicht,
// steht der Nutzer weiter vor dem Passwortfeld, obwohl die Sitzung längst steht —
// der Kern von Ticket #157.
//
// `router.push()` meldet einen Fehlschlag auf drei Arten, und nur eine davon
// sieht ein `try/catch`:
//   1. Es wirft — Seiten-Chunk nicht ladbar, Fehler in einem Guard.
//   2. Es liefert ein NavigationFailure ZURÜCK: ein Guard bricht ab oder leitet
//      auf die Seite um, auf der wir schon stehen; oder eine zweite Navigation
//      (z. B. der 401-Interceptor) überholt die erste. Die Promise *erfüllt*
//      sich dabei — ein `catch` greift hier nie. Genau das endet stumm.
//   3. Es kommt gar nicht zurück — das Nachladen hängt am Netz oder an einem
//      Service Worker, der sich gerade erst installiert.
//
// Alle drei heilt derselbe Griff, den Nutzer bisher selbst getan haben: die
// Übersicht hart aufrufen. Ein sichtbarer Neustart ist besser als ein Klick,
// der nichts tut.

// Großzügig bemessen: Die Chunks sind normalerweise vorgeladen, der Wachhund
// greift nur, wenn wirklich nichts mehr kommt.
const WACHHUND_MS = 5000

// ── Ziel über den Login hinweg ──
// Wer einen Link aus einer Benachrichtigung öffnet (Ticket, Termin …) und dabei
// nicht angemeldet ist, soll nach dem Login dort landen und nicht auf der
// Übersicht. Bewusst im localStorage und nicht als Query-Parameter an /login:
// Der Standardweg ist der Login-Link per Mail, und der öffnet einen neuen Tab
// ohne die Query der Login-Seite. Die Frist verhindert, dass ein abgebrochener
// Versuch Tage später beim nächsten normalen Login wieder aufpoppt.
const ZIEL_KEY = 'vtb_nach_login'
const ZIEL_FRIST_MS = 60 * 60 * 1000

export function merkeZiel(pfad) {
  if (!pfad || pfad === '/') return
  try {
    localStorage.setItem(ZIEL_KEY, JSON.stringify({ pfad, zeit: Date.now() }))
  } catch { /* ohne Speicher eben zur Übersicht */ }
}

function holeZiel() {
  try {
    const eintrag = JSON.parse(localStorage.getItem(ZIEL_KEY) || 'null')
    localStorage.removeItem(ZIEL_KEY)
    // Nur app-interne Pfade – „//host" wäre für den Browser eine fremde Seite.
    if (eintrag && typeof eintrag.pfad === 'string' && eintrag.pfad.startsWith('/')
        && !eintrag.pfad.startsWith('//') && Date.now() - eintrag.zeit < ZIEL_FRIST_MS) {
      return eintrag.pfad
    }
  } catch { /* kaputter Eintrag – ignorieren */ }
  return null
}

export async function zurUebersicht(router) {
  const ziel = holeZiel()
  let fertig = false
  const hart = (grund) => {
    if (fertig) return
    fertig = true
    // Eine Zeile fürs Protokoll: Bleibt der Login trotzdem auffällig, sagt sie,
    // welcher der drei Fälle es war.
    console.warn('[Login] Wechsel zur Übersicht fehlgeschlagen (%s) – lade neu.', grund)
    window.location.assign(ziel || '/')
  }

  const wachhund = setTimeout(() => hart('keine Antwort'), WACHHUND_MS)
  try {
    const fehlschlag = await router.push(ziel || { name: 'dashboard' })
    if (fehlschlag) hart(`NavigationFailure ${fehlschlag.type}`)
    else fertig = true
  } catch (err) {
    hart(err?.message || 'Fehler')
  } finally {
    clearTimeout(wachhund)
  }
}
