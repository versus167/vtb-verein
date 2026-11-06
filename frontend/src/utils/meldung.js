// Gemeinsames für die Meldungen im Bereich „Berichte" (#155).

// Spalten der Jahrgangstabellen – Schlüssel wie im Backend (_GESCHLECHTER).
export const GESCHLECHTER = [
  { key: 'm', label: 'männlich' },
  { key: 'w', label: 'weiblich' },
  { key: 'd', label: 'divers' },
  { key: 'ohne', label: 'ohne Angabe' },
]

export const JAHRGANG_KOPF = ['Jahrgang', ...GESCHLECHTER.map((g) => g.label), 'Summe']

// Eine Jahrgangstabelle als CSV-Zeilen (ohne Kopf); `vorne` stellt jeder Zeile
// Spalten voran, z. B. den Abteilungsnamen in der B-Meldung.
export function jahrgangZeilen(tabelle, vorne = []) {
  return tabelle.zeilen.map((z) => [
    ...vorne, z.jahrgang ?? 'ohne Geburtsdatum', ...GESCHLECHTER.map((g) => z[g.key]), z.summe,
  ])
}
