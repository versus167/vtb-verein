import { useRouter } from 'vue-router'

// Zurück-Pfeile in Seitenköpfen sollen einen echten Schritt zurückgehen statt
// auf eine feste Seite zu springen (#193): Wer eine Unterseite über einen
// anderen Weg erreicht hat, landete sonst woanders als dort, wo er herkam — und
// der Verlauf wuchs, statt zu schrumpfen, sodass die Zurück-Geste danach erst
// recht im Kreis lief.
//
// `history.state.back` setzt vue-router selbst und nur für App-eigene Einträge.
// Fehlt es (Direktlink, neuer Tab, frisch geladene PWA), bleibt das übergebene
// Ziel als Rückfall — sonst käme man aus der Seite nicht mehr heraus.
export function useZurueck(ziel) {
  const router = useRouter()
  return () => {
    if (window.history.state?.back) router.back()
    else router.push(ziel)
  }
}
