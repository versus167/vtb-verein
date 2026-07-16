// Geteilte Helfer für Termine-Darstellung (TerminePage, TerminCard, Dashboard-Widget).
// Zeiten sind lokale Wandzeit als Text ('YYYY-MM-DDTHH:MM' bzw. 'HH:MM').
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
