/**
 * CSV-Download für Berichte (#155).
 *
 * Semikolon, BOM und CRLF – so öffnet Excel die Datei ohne Nachfrage, genau wie
 * bei den Exporten aus dem Backend (rechnung_export_service._uebersicht_csv).
 * Gebaut wird im Browser aus den angezeigten Daten: Die Datei enthält damit
 * exakt, was am Bildschirm steht.
 */

function feld(wert) {
  const s = wert == null ? '' : String(wert)
  return /[;"\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

export function csvDownload(dateiname, kopf, zeilen) {
  const text = [kopf, ...zeilen].map((z) => z.map(feld).join(';')).join('\r\n')
  const url = URL.createObjectURL(new Blob(['﻿' + text], { type: 'text/csv;charset=utf-8' }))
  const a = document.createElement('a')
  a.href = url; a.download = dateiname; a.click()
  URL.revokeObjectURL(url)
}
