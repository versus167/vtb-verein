# Archiv: abgeschlossene Planungsdokumente

Hier liegen Pläne, deren Vorhaben **umgesetzt** ist. Sie stehen nicht mehr im
Wurzelverzeichnis, weil dort nur gelten soll, was noch etwas ankündigt — ein
Plan, der schon Code ist, führt sonst jeden in die Irre, der ihn für eine
Absichtserklärung hält.

Gelöscht werden sie trotzdem nicht: Sie halten die **Begründungen** fest, die
sich aus dem Code nicht ablesen lassen — warum ein Fachmodell so und nicht
anders geschnitten ist, welche Alternative verworfen wurde und wer wann was
entschieden hat. Genau das braucht man beim nächsten Umbau.

| Datei | Vorhaben | Umgesetzt in |
|---|---|---|
| `CLUBDECKEL_PLAN.md` | Teamkasse (mannschaftsinterne Strichliste) | Schema v75/v76, `backend/api/clubdeckel.py`, `TeamkassePage.vue` |
| `SPIELBETRIEB_PLAN.md` | Termine, Zu-/Absagen, Spielplan-Import (Etappen 1–3) | Schema v68–v70, `backend/api/termine.py`, `TerminePage.vue` |

**Was hier nicht hingehört:** Pläne mit offenen Etappen. Die bleiben im
Wurzelverzeichnis, auch wenn der größere Teil schon steht — solange etwas
aussteht, ist das Dokument eine Ansage und keine Chronik. Aktuell betrifft das
`DFBNET_IMPORT_PLAN.md`, `ZUTRITTSKONTROLLE_PLAN.md`, `LINEAR_IMPORT_PLAN.md`
und `ZWEITE_INSTANZ.md`.

**Ebenfalls entfernt (2026-08-18):** `CLUBTRESOR_MIGRATION.md` — eine
vollständige Spezifikation der fremden PHP-App *Clubtresor*, geschrieben als
Vorlage für den Nachbau. Der Nachbau ist die Teamkasse; über diesen Code hat das
Dokument nie etwas ausgesagt. Bei Bedarf über die Git-Historie erreichbar
(entfernt im Commit dieser Aufräumaktion).
