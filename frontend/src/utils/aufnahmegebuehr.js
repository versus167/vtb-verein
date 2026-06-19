// Ticket #42: Aufnahmegebühr bei Neuanlage / Abteilungs-Neuzuordnung vorschlagen.
//
// Fragt passende Aufnahmegebühren vom Backend ab und legt die gewählte nach
// Bestätigung als Forderung an. abteilungId = null → Vereins-Aufnahmegebühr,
// sonst die der Abteilung. Mehrere Kandidaten (z. B. Erwachsene/Kinder) schließen
// sich aus → Einfach-Auswahl. Fehlt die Gebühren-Berechtigung (403), wird der
// Vorschlag stillschweigend übersprungen.
import { api } from 'src/boot/axios'

function euro(betrag) {
  return `${Number(betrag).toFixed(2)} €`
}

async function createForderung($q, mitgliedId, gebuehr, datum) {
  try {
    await api.post('/api/gebuehren/forderungen', {
      mitglied_id: mitgliedId, gebuehr_id: gebuehr.id, datum,
    })
    $q.notify({ type: 'positive', message: `Aufnahmegebühr „${gebuehr.name}" als Forderung angelegt` })
  } catch (e) {
    $q.notify({ type: 'negative', message: e.response?.data?.detail || 'Forderung konnte nicht angelegt werden' })
  }
}

export async function proposeAufnahmegebuehr($q, { mitgliedId, abteilungId = null, datum }) {
  if (!mitgliedId || !datum) return

  let kandidaten = []
  try {
    const { data } = await api.get('/api/gebuehren/vorschlag', {
      params: { mitglied_id: mitgliedId, abteilung_id: abteilungId ?? undefined, datum },
    })
    kandidaten = data
  } catch {
    return // keine Berechtigung / Backend ohne Endpoint → kein Vorschlag
  }
  if (!kandidaten.length) return

  await new Promise((resolve) => {
    // Genau ein Kandidat → einfache Ja/Nein-Bestätigung.
    if (kandidaten.length === 1) {
      const g = kandidaten[0]
      $q.dialog({
        title: 'Aufnahmegebühr berechnen?',
        message: `Für „${g.name}" eine Forderung über ${euro(g.betrag)} (Datum ${datum}) anlegen?`,
        cancel: { label: 'Nein', flat: true },
        ok: { label: 'Forderung anlegen', color: 'primary', unelevated: true },
        persistent: true,
      })
        .onOk(async () => { await createForderung($q, mitgliedId, g, datum); resolve() })
        .onCancel(resolve)
      return
    }

    // Mehrere (sich ausschließende) Varianten → Einfach-Auswahl.
    $q.dialog({
      title: 'Aufnahmegebühr berechnen?',
      message: `Welche Aufnahmegebühr soll als Forderung (Datum ${datum}) angelegt werden?`,
      options: {
        type: 'radio',
        model: null,
        items: kandidaten.map((g) => ({ label: `${g.name} (${euro(g.betrag)})`, value: g.id })),
      },
      cancel: { label: 'Keine', flat: true },
      ok: { label: 'Forderung anlegen', color: 'primary', unelevated: true },
      persistent: true,
    })
      .onOk(async (gebuehrId) => {
        const g = kandidaten.find((k) => k.id === gebuehrId)
        if (g) await createForderung($q, mitgliedId, g, datum)
        resolve()
      })
      .onCancel(resolve)
  })
}
