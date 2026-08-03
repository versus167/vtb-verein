# Plan: Spielplan-Import aus dem DFBnet (Ticket #95, Etappe 3)

> Status (2026-08-03): **Konzept, noch keine Umsetzung.** Grundlage ist ein
> Muster-Export des Vereinsspielplans für die Saison 26/27.
>
> **Keine Echtdaten im Repo:** Der Export enthält Namen und Ausweisnummern von
> Schiedsrichtern. Alle Beispiele hier sind gekürzt oder erfunden.

## Quellformat — die Überraschungen zuerst

- **UTF-16LE mit BOM, Tab-getrennt.** Nicht Semikolon, nicht UTF-8. Damit haben
  wir die dritte Kodierungsvariante im Haus (SPG: cp1252, LINEAR: UTF-8,
  DFBnet: UTF-16). Wer die Datei blind als Text öffnet, sieht zwischen jedem
  Zeichen ein Leerzeichen — das sind die Null-Bytes.
- **Der Spaltenname „Typ" kommt zweimal vor**: einmal als Platztyp
  (Rasenplatz / Kunstrasenplatz), einmal als Spieltyp (Meisterschaft, Pokal,
  Freundschaftsspiel, Turnier, Spielnachmittag). Ein `csv.DictReader` behält
  davon nur eine — der Parser muss **positionsbasiert** lesen.
- **Personenbezogene Spalten**: Spielleitung, Assistent 1/2, die zugehörigen
  Ausweisnummern und Schirigebiete. Für den Kalender brauchen wir davon nichts
  — **nicht importieren**, dann stellt sich die Frage nach Aufbewahrung und
  Löschung gar nicht erst.

## Zwei Annahmen, die der Export nicht erfüllt

**1. Nicht jede Zeile hat eine eigene Mannschaft.** Im Muster sind vier Zeilen
Spiele *fremder* Vereine auf unserem Platz (Schönau – Platz Windweg,
Guerickestr. 48) im Rahmen eines E-Junioren-Turniers. Der Vereinsspielplan ist
eben auch ein **Platzbelegungsplan** — und die Zeilen werden gebraucht, s. u.
Erkennung über die **Spielstätten-Nr.**, nicht über die Adresse; die steht in
wechselnder Schreibweise drin.

**2. Der Teamname ist nicht eindeutig.** „VTB Chemnitz 2" ist im selben Export
sowohl die 2. Herren (1. Kreisklasse) als auch eine E-Junioren-Mannschaft. Ein
Abgleich allein über den Namen ordnet Spiele der falschen Mannschaft zu. Das
Matching braucht **Mannschaftsart + Name**, mit Staffel/Liga als Zusatzprüfung.

## Zuordnung Team ↔ DFBnet

Wie vorgeschlagen als Einstellung am Team: Feld `dfbnet_name` plus
`dfbnet_mannschaftsart` an der Mannschaft.

Dazu eine **Alias-Liste**, denn bei Spielgemeinschaften steckt unser Team im
zusammengesetzten Namen („VTB Chemnitz / SG Handwerk Rabenstein II"). Wichtig:
**kein Teilstring-Matching** — „VTB Chemnitz" ist Teilstring von „VTB Chemnitz
2", das ordnet die 1. Herren jedem Nachwuchsspiel zu. Also exakter Vergleich
gegen Name und Aliasse.

Unbekannte DFBnet-Teams werden im Dry-Run gemeldet, nichts wird automatisch
angelegt — dasselbe Muster wie beim SPG-Import.

## Abbildung auf den Termin

Anker ist die **Spielkennung → `termine.extern_ref`**. Das Feld existiert
bereits, mitsamt partiellem Unique-Index (`uix_termine_extern_ref`) und dem
Kommentar „DFBnet-Spielkennung"; es ist bewusst nicht über die API setzbar. Die
Spielkennung bleibt bei einer Verlegung stabil — genau deshalb taugt sie als
Schlüssel.

| DFBnet | Termin |
|---|---|
| Spielkennung | `extern_ref` |
| Spieldatum + Uhrzeit | `beginn` (lokale Wandzeit als Text, wie überall) |
| — | `ende`: liefert DFBnet nicht, s. offene Fragen |
| Heim-/Gastmannschaft | `heim_auswaerts` (steht unser Team links → `heim`), `gegner` = das jeweils andere Team |
| Spielstätte + Straße + PLZ/Ort | `ort` |
| Spieltyp, Liga/Staffel, Sptg. | `beschreibung` |
| Mannschaftsart + Team | Zuordnung zur `mannschaft_id` |

`typ` ist immer `spiel`. Treffpunkt und Treffpunktzeit kommen **nicht** aus
DFBnet — die pflegt das Team, ein Import darf sie nie überschreiben.

## Der Kern: Änderungen und Konflikte

Damit die App „das Team hat geändert" von „das DFBnet hat geändert"
unterscheiden kann, reicht ein Vergleich App ↔ Datei **nicht**. Es braucht den
**letzten importierten Stand** als Schnappschuss am Termin (`extern_stand`, z. B.
JSON mit Beginn, Ort, Heimrecht, Gegner). Damit ergeben sich drei Fälle:

| DFBnet gegen letzten Import | App gegen letzten Import | Aktion |
|---|---|---|
| geändert | unverändert | **automatisch übernehmen** und den Kader benachrichtigen — Zu-/Absagen hängen an der Zeit |
| geändert | ebenfalls geändert | **nicht anfassen** → Abweichung anlegen, Betreuer entscheidet |
| unverändert | geändert | **nichts tun** — das Team weicht bewusst ab |

Der dritte Fall ist der Grund für den Schnappschuss: Ohne ihn würde die App bei
*jedem* Lauf erneut nachfragen, obwohl das Team die Abweichung längst so will —
also genau die Situation „im DFBnet steht es noch falsch".

### Abweichungen sichtbar machen

Neue Tabelle `termin_abweichung`: `termin_id`, Quelle, Feld, Wert in der App,
Wert laut DFBnet, erkannt am, Status (`offen` / `uebernommen` / `verworfen`),
entschieden von/am. Mit Soft-Delete, History-Trigger und — wie in `CLAUDE.md`
gefordert — einem Eintrag im **`PRUNE_REGISTRY`** (Kind vor Eltern, Elternteil
ist der Termin).

In der Oberfläche: ein Hinweis-Badge am Termin für alle mit Kader-Recht
„verwalten", dahinter ein Dialog im Stil „Laut DFBnet ist der Anstoß 15:00 statt
14:00 — übernehmen oder verwerfen?". Übernehmen schreibt den Termin und nutzt
die bestehende Terminmeldung, um den Kader zu informieren.

### Verschwundene Spiele

Ein Spiel, das nicht mehr im Export steht, wird **nie automatisch gelöscht**.
Der Export ist ein Zeitfenster-Auszug, kein Vollbestand — „fehlt" heißt nicht
„abgesagt". Der Abgleich läuft deshalb nur innerhalb des in der Datei
vorkommenden Datumsbereichs, und Fehlendes wird als Abweichung „im DFBnet nicht
mehr enthalten" gemeldet.

## Platzbelegung — fremde Spiele auf unseren Plätzen

Diese Zeilen werden **mitimportiert**, nicht verworfen. Später sollen die
Platzwarte einen Lesezugriff auf den Belegungsplan bekommen; das ist ein
eigener Schritt, hier wird nur die Grundlage dafür gelegt.

**Nicht als Termin.** `termine.mannschaft_id` ist `NOT NULL`, und die gesamte
Logik darum herum — Kader-ACL, Zu-/Absagen, Benachrichtigungen, „Meine
Termine" — setzt eine Mannschaft voraus. Die Spalte nullable zu machen hieße,
jede dieser Stellen auf den Sonderfall „Termin ohne Team" zu prüfen. Ein
fremdes Spiel ist fachlich auch kein Termin des Vereins, sondern eine Belegung.
Deshalb eine eigene Tabelle:

- **`spielstaette`** (Stammdaten): Name, DFBnet-Spielstätten-Nr., Adresse,
  Kennzeichen „eigener Platz". Braucht der Import ohnehin, um überhaupt zu
  erkennen, welche Zeilen uns betreffen — und es ist die Liste, die der
  Belegungsplan später als Spalten oder Filter nutzt.
- **`platzbelegung`**: `spielstaette_id`, Beginn, Ende, Heim- und
  Gastmannschaft, Liga/Staffel, `extern_ref` (Spielkennung), Quelle. Mit
  Soft-Delete, History und Eintrag im **`PRUNE_REGISTRY`** (Kind der
  Spielstätte).

Für die Belegungen gilt derselbe Drei-Wege-Abgleich wie für Termine — nur ohne
Konfliktfall, weil an fremden Spielen niemand in der App etwas ändert. Verlegte
Spiele werden also einfach nachgezogen.

**Vorbereitung für den Platzwart-Zugriff** (später umzusetzen):

- Permission-Key `platzbelegung.read` — als Konstante in `permission.py`, im
  Admin-Seed und per Migration für Bestands-Admins nachgezogen (Fresh ==
  Upgrade, s. `CLAUDE.md`). Platzwarte bekommen ihn über eine Funktion oder
  einen individuellen Grant, ohne Zugriff auf Mitglieder- oder Kaderdaten.
- Die Ansicht zeigt **beides**: importierte Fremdspiele und eigene Heimspiele.
  Letztere stecken in `termine` — die Ansicht ist also eine Vereinigung beider
  Quellen, keine dritte Datenhaltung.

**Eine Lücke, die dabei sichtbar wird:** Unsere Trainings stehen als Termine mit
`ort` als freiem Text, ohne Bezug zu einer Spielstätte. Ein Belegungsplan, der
nur Spiele kennt, zeigt den Platz als frei, obwohl dort trainiert wird. Wenn der
Plan mehr sein soll als eine Spielübersicht, brauchen Termine später eine
optionale `spielstaette_id` — das ist der eigentliche Umfang des
Platzwart-Schritts, nicht die Leseberechtigung.

## Etappen

1. **Stammdaten + Team-Zuordnung**: Spielstätten (inkl. eigener Plätze),
   `dfbnet_name`/`dfbnet_mannschaftsart` plus Alias-Liste an der Mannschaft,
   Pflege in der Mannschaftsverwaltung.
2. **Parser + Dry-Run**: Datei lesen, Zeilen zuordnen, Bericht „würde anlegen /
   würde ändern / Konflikt / kein Team zugeordnet / Platzbelegung". Schreibt
   nichts.
3. **Anlegen und unstrittige Übernahme**: `extern_ref`, Schnappschuss,
   Benachrichtigung des Kaders bei Änderungen. Fremde Spiele laufen im selben
   Lauf in die Platzbelegung.
4. **Abweichungen**: Tabelle, Badge, Entscheidungs-Dialog.
5. **Platzwart-Zugriff** (späterer Schritt): Permission-Key, Belegungsansicht
   aus beiden Quellen, optionale `spielstaette_id` an Terminen, damit auch
   Trainings im Plan stehen.

## Offene Fragen

- **Spielende**: DFBnet liefert nur den Anstoß. Feste Dauer je Mannschaftsart
  (Herren 2×45 plus Halbzeit, Junioren kürzer) als Vorgabe, oder `ende` leer
  lassen und das Team pflegt es?
- **Wer darf importieren?** Der SPG-Import ist Admin-only (`system.config`).
  Für den Spielplan wäre der Kader-Verwalter der passendere Adressat — dann
  aber nur für die eigenen Teams.
- **Turniere**: Beim Kinderfestival stehen mehrere Einzelspiele desselben Tages
  für die Teams 1–6 in der Datei. Je Spiel ein Termin, oder ein Sammeltermin
  „Kinderfestival" mit Zeitraum?
- **Wie oft läuft der Import** — Datei-Upload von Hand oder regelmäßig? Bei
  regelmäßigem Lauf ist die Abweichungs-Tabelle Pflicht; bei reinem Handbetrieb
  ginge auch eine Vorschau mit Häkchen pro Zeile.
- **Spielstätten-Stammdaten**: von Hand pflegen, oder beim ersten Import aus
  den vorkommenden Spielstätten vorschlagen und der Verein hakt die eigenen ab?
- **Umfang des Belegungsplans**: nur die eigenen Plätze, oder auch fremde
  Spielstätten, auf denen unsere Teams antreten (dann ist es eher ein
  Auswärtsplan als eine Belegung)?
- **Platzwarte als Rolle**: eigene Funktion im Funktionskatalog oder
  individuelle Grants? Davon hängt ab, ob der Zugriff abteilungsweit
  eingegrenzt werden kann.
