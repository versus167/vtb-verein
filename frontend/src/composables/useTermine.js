// Geteilte Helfer für Termine-Darstellung (TerminePage, TerminCard, Dashboard-Widget).
// Zeiten sind lokale Wandzeit als Text ('YYYY-MM-DDTHH:MM' bzw. 'HH:MM').
import { ref } from 'vue'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'

// Zu-/Absage-Kategorien (RSVP) inkl. Icon + semantischer Farbe (Vereinskonvention:
// positive/warning/negative – kein Fremd-Blau).
export const ANTWORTEN = [
  { key: 'zu', icon: 'thumb_up', color: 'positive', label: 'Zusage' },
  { key: 'vielleicht', icon: 'help', color: 'warning', label: 'Vielleicht' },
  { key: 'ab', icon: 'thumb_down', color: 'negative', label: 'Absage' },
]

export function typIcon(typ) {
  return { training: 'fitness_center', spiel: 'sports_soccer' }[typ] ?? 'event'
}

export function terminTitel(t) {
  if (t.typ === 'spiel') {
    const ha = t.heim_auswaerts === 'heim' ? ' (H)' : t.heim_auswaerts === 'auswaerts' ? ' (A)' : ''
    return `Spiel${t.gegner ? ` vs. ${t.gegner}` : ''}${ha}`
  }
  return t.typ === 'training' ? 'Training' : 'Sonstiges'
}

export function uhrzeit(wandzeit) {
  return (wandzeit ?? '').slice(11, 16)
}

// „Mi." – kurzer Wochentag für den Datumsblock der Card.
export function wochentag(iso) {
  if (!iso) return ''
  return new Date(`${iso}T12:00`).toLocaleDateString('de-DE', { weekday: 'short' })
}

// „15.07." – Tag/Monat für den Datumsblock der Card.
export function tagMonat(iso) {
  if (!iso) return ''
  return new Date(`${iso}T12:00`).toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit' })
}

// „Mi., 15.07.2026" – volles Datum (Gruppen-/Dialog-Text).
export function datumLabel(iso) {
  if (!iso) return ''
  return new Date(`${iso}T12:00`).toLocaleDateString('de-DE',
    { weekday: 'short', day: '2-digit', month: '2-digit', year: 'numeric' })
}

// Spielstätten-Auswahl für Termin- und Serien-Dialog: Liste laden und tippend
// filtern. Ein reines Dropdown reicht nicht mehr — mit dem Spielplan-Import
// kommt jeder gegnerische Platz in die Stammdaten, die Liste wird lang.
export function useSpielstaettenAuswahl() {
  const alle = ref([])
  const optionen = ref([])
  const laedt = ref(false)

  async function laden() {
    laedt.value = true
    try {
      const { data } = await api.get('/api/spielstaetten/')
      alle.value = data
    } catch {
      alle.value = []
    } finally {
      optionen.value = alle.value
      laedt.value = false
    }
  }

  // Sucht in Name UND Adresse: „Limbach" soll den Platz auch dann finden, wenn
  // der Ort nur in der Anschrift steht.
  function filtern(eingabe, update) {
    const suche = (eingabe || '').toLowerCase().trim()
    update(() => {
      optionen.value = !suche ? alle.value : alle.value.filter((p) =>
        `${p.name} ${p.strasse ?? ''} ${p.plz ?? ''} ${p.ort ?? ''}`
          .toLowerCase().includes(suche))
    })
  }

  // Adresszeile unter dem Namen – zwei Plätze heißen schnell mal ähnlich.
  function adresse(p) {
    return [p.strasse, [p.plz, p.ort].filter(Boolean).join(' ')].filter(Boolean).join(', ')
  }

  // Ortstext zur Spielstätte, in derselben Form wie ihn der Spielplan-Import
  // schreibt: „Platz, Straße, PLZ Ort". Platzhalter („Kein Vereinsgelände",
  // „Nicht erfasst") haben keine Anschrift und liefern hier bewusst nichts.
  function ortText(id) {
    const p = alle.value.find((x) => x.id === id)
    if (!p || p.platzhalter) return ''
    return [p.name, adresse(p)].filter(Boolean).join(', ')
  }

  return { alle, optionen, laedt, laden, filtern, adresse, ortText }
}

// Ort an die Karten-/Navi-App des Geräts übergeben.
//
// Android kennt das geo:-Schema und lässt den Nutzer die App wählen (Google Maps,
// OsmAnd, Organic Maps …) – genau das ist gewollt, die App schreibt keinen
// Routingdienst vor. iOS kennt geo: nicht und braucht maps.apple.com; alles
// andere (Desktop) bekommt Google Maps im Browser.
//
// `platform` ist Quasars `$q.platform.is` – als Parameter, damit die Funktion
// ohne Quasar-Kontext testbar bleibt.
export function kartenLink(ort, platform = {}) {
  const ziel = (ort || '').trim()
  if (!ziel) return ''
  const q = encodeURIComponent(ziel)
  if (platform.ios) return `https://maps.apple.com/?q=${q}`
  if (platform.android) return `geo:0,0?q=${q}`
  return `https://www.google.com/maps/search/?api=1&query=${q}`
}

// Felder des DFBnet-Abgleichs (#95). Hier zentral, weil zwei Stellen dieselbe
// Sprache sprechen müssen: der Abweichungs-Dialog und der Hinweis an der Karte.
export const ABWEICHUNG_FELDER = {
  beginn: 'Anstoß', ort: 'Spielort', heim_auswaerts: 'Heimrecht',
  gegner: 'Gegner', entfallen: 'Nicht mehr in diesem DFBnet-Auszug',
}

export function abweichungFeldLabel(feld) {
  return ABWEICHUNG_FELDER[feld] ?? feld
}

export function abweichungWert(feld, wert) {
  if (!wert) return '–'
  if (feld === 'beginn') return `${datumLabel(wert.slice(0, 10))} ${uhrzeit(wert)}`
  if (feld === 'heim_auswaerts') return wert === 'heim' ? 'Heimspiel' : 'Auswärtsspiel'
  return wert
}

// Verwalter-Aktionen (Absagen/Reaktivieren/Löschen) – geteilt zwischen
// TerminePage und Dashboard-Widget. `reload` wird nach jeder Änderung gerufen.
export function useTerminAktionen(reload) {
  const $q = useQuasar()

  function setStatus(t, aktion) {
    const absagen = aktion === 'absagen'
    $q.dialog({
      title: absagen ? 'Termin absagen' : 'Termin reaktivieren',
      message: `„${terminTitel(t)}" am ${datumLabel(t.beginn.slice(0, 10))} ${absagen ? 'absagen' : 'reaktivieren'}?`,
      options: {
        type: 'checkbox',
        model: [],
        items: [{ label: 'Team benachrichtigen', value: 'benachrichtigen' }],
      },
      cancel: true, persistent: true,
    }).onOk(async (auswahl) => {
      try {
        await api.post(`/api/termine/${t.id}/${aktion}`, {
          expected_version: t.version,
          benachrichtigen: auswahl.includes('benachrichtigen'),
        })
        await reload()
        $q.notify({ type: 'positive', message: absagen ? 'Termin abgesagt' : 'Termin reaktiviert' })
      } catch (e) {
        $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' })
      }
    })
  }

  function confirmDelete(t) {
    $q.dialog({
      title: 'Termin löschen',
      message: `„${terminTitel(t)}" am ${datumLabel(t.beginn.slice(0, 10))} wirklich löschen?`,
      cancel: true, persistent: true,
    }).onOk(async () => {
      try {
        await api.delete(`/api/termine/${t.id}`)
        await reload()
      } catch (e) {
        $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Fehler' })
      }
    })
  }

  return { setStatus, confirmDelete }
}
