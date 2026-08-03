# Plan: Datenübernahme aus dem Vereinsprogramm LINEAR

> Status (2026-08-03): **Konzept, noch keine Umsetzung.** Zuschnitt aus einer
> Diskussionsrunde anhand eines Muster-Exports. Die Entscheidungen unten sind
> getroffen, die offenen Fragen brauchen einen Blick in den Echt-Export.
>
> **Keine Echtdaten im Repo:** Der Muster-Export enthält Namen, Adressen und
> Bankverbindungen realer Mitglieder. Alle Beispiele hier sind erfunden.

## Kernidee

Eine **zweite Import-Variante** neben dem bestehenden SPG-Verein-Import, kein
generisches Spalten-Mapping. Begründung: Es geht um eine einmalige Übernahme,
und die beiden Formate unterscheiden sich weniger in der Syntax als in der
Semantik — LINEAR führt die Abteilungen als *Kreuz-Spalten* (eine Spalte je
Abteilung, Zugehörigkeit als „X"), SPG als nummerierte Feldgruppen
(`Abteilung_1..7` mit Status und Datum). Ein gemeinsamer Mapper müsste beide
Welten abbilden und wäre teurer als zwei schmale Parser. Als eigene Variante
lassen sich die Unterschiede jeweils dort adressieren, wo sie auftreten.

## Vorhandene Bausteine (werden wiederverwendet)

- **`spg_import_service.run_import`**: Dry-Run (`commit=False` schreibt nichts),
  strukturiertes `ImportResult`, Abteilungen werden **nur gematcht, nie
  angelegt**, Abbruch mit Klartext bei unbekannten Abteilungen, Update-Modus
  (Kind-Zuordnungen soft-löschen und neu schreiben), Wiedererkennung beim
  Re-Import über einen Vermerk in `bemerkungen`.
- **`backend/api/imports.py`**: Admin-Endpunkt (`system.config`),
  Multipart-Upload, Flags `commit` / `update` / `allow_unmatched`.
- **`frontend/src/pages/ImportPage.vue`**: Datei wählen, Dry-Run, Ergebnis- und
  Abgleichsanzeige.

Neu zu bauen sind also **Parser und Feld-Mapping**, nicht das Schreib-Gerüst.

## Quellformat

Semikolon-getrennte CSV. Textfelder in Anführungszeichen, Datumsfelder
**unquoted mit Uhrzeit-Anhang**. Nach der Kopfzeile stehen zwei Leerzeilen,
danach die Datensätze (schematisch, erfundene Werte):

```
"MITGLNR";"Anrede";"Nachname";"Vorname";"Geburtsdatum";"Strasse";"PLZ";"Ort";"IBAN1";"BIC1";"Status";"Eintritt";"Austritt";"Telefon";"Geschlecht";"Staatsangehörigkeit";"Mobiltelefon";<Abteilungsspalten…>
;;;;;;;;;;;;;;;;;;;;;;;
"0999";"Herr";"Mustermann";"Max";01.01.2000 00:00;"Musterweg 1";"09111";"Chemnitz , Sachs";"DE00…";"…XXX";"Aktiv";01.01.2020 00:00;;;"MÄNNLICH";"DE";"01700000000";;"X";;;;;
```

Ab der Spalte „Allgemeine Sportgruppe" folgen die Abteilungen. Im Muster-Export
sind das: Allgemeine Sportgruppe, Fußball, Kegeln, Kegeln o. LFV, Kraft- und
Fitnesssport, Tischtennis, Tischtennis o. LFV. Die Spaltenliste ist damit
**vereinsspezifisch** — der Parser darf sie nicht fest verdrahten, sondern muss
alles ab der ersten Abteilungsspalte als Abteilung behandeln (Grenze: die
letzte bekannte Stammdatenspalte, `Mobiltelefon`).

## Feld-Mapping

| LINEAR | Ziel | Anmerkung |
|---|---|---|
| MITGLNR | `bemerkungen` → `[LINEAR:0999]` | s. Entscheidung 2 |
| Anrede | — | kein Zielfeld; Information steckt im Geschlecht |
| Nachname, Vorname | `nachname`, `vorname` | trimmen (Export hat Leerzeichen am Ende) |
| Geburtsdatum, Eintritt, Austritt | `geburtsdatum`, `eintrittsdatum`, `austrittsdatum` | Format `%d.%m.%Y %H:%M` |
| Strasse, PLZ, Ort | `strasse`, `plz`, `ort` | Ort-Zusatz abschneiden, s. Entscheidung 4 |
| IBAN1, BIC1 | `iban`, `bic` | `zahlungsart` = `lastschrift`, wenn IBAN vorhanden, sonst `ueberweisung` |
| Status | `status` | „Aktiv" → `aktiv`; gefülltes Austrittsdatum gewinnt → `ausgetreten` |
| Telefon | Kontakt `telefon` (primär) | zusätzlich `mitglied.telefon` |
| Mobiltelefon | Kontakt `mobil` (primär) | |
| Geschlecht | `geschlecht` | MÄNNLICH → `m`, WEIBLICH → `w`, sonst `d`/leer |
| Staatsangehörigkeit | neues Feld | s. Entscheidung 3 |
| Abteilungsspalten mit „X" | `mitglied_abteilung` | Status `aktiv`, Von = Eintrittsdatum |
| | `kontoinhaber` | LINEAR hat kein Zahler-Feld → „Vorname Nachname" |

## Entschieden (2026-08-03)

1. **„o. LFV"-Spalten werden eigene Abteilungen.** „Tischtennis o. LFV" bleibt
   von „Tischtennis" getrennt, die Unterscheidung (ohne Landesfachverband)
   bleibt damit auswertbar. Folge: Diese Abteilungen müssen **vor dem Import in
   der App angelegt** sein, sonst bricht der Lauf mit der Liste der Unbekannten
   ab — so wie beim SPG-Import.
2. **MITGLNR wird nicht zur Mitgliedsnummer.** Sie wandert als `[LINEAR:0999]`
   in die Bemerkungen (Wiedererkennung beim Re-Import), intern vergibt die App
   eine neue Nummer. Grund: `mitgliedsnummer` ist numerisch, führende Nullen
   gingen verloren, und die alten Nummern könnten mit dem Bestand kollidieren.
3. **Staatsangehörigkeit bekommt ein eigenes Feld** am Mitglied — inklusive
   Schema-Migration und Anzeige im Mitglied-Dialog. Nicht in die Bemerkungen,
   damit die Angabe auswertbar bleibt.
4. **Ort wird bereinigt:** „Chemnitz , Sachs" → „Chemnitz". Der Zusatz ist die
   postalische Unterscheidung gleichnamiger Orte und in der App nur Ballast.

## Technische Punkte

1. **Kodierung**: Der SPG-Parser dekodiert hart `cp1252`. Der Muster-Export
   sieht nach UTF-8 aus (Symptom bei falschem Griff: „StaatsangehÃ¶rigkeit",
   „FuÃball"). Der neue Parser probiert `utf-8-sig` → `utf-8` → `cp1252` durch;
   sonst landen kaputte Umlaute dauerhaft in der DB.
2. **Datumsformat** `13.01.2005 00:00` — `to_iso` kennt bisher nur `%d.%m.%Y`
   und `%Y-%m-%d`.
3. **Leerzeilen** unter dem Header fängt die bestehende Prüfung („Zeile ohne
   jeden Inhalt") ab.
4. **Re-Import** über den `[LINEAR:<nr>]`-Vermerk: ohne `update`-Flag werden
   bekannte Sätze übersprungen, mit Flag aktualisiert (Kontakte und
   Abteilungszuordnungen vorher soft-löschen — Muster aus dem SPG-Import).
5. **Unbekannte Werte** (Geschlecht, Status) nicht raten, sondern leer lassen
   und im `ImportResult` zählen, damit sie im Dry-Run auffallen.

## Was die Datei nicht liefert

- **SEPA-Mandatsreferenz und -datum.** Die Sätze sind danach zwar da, aber
  nicht einziehbar — für den Lastschrifteinzug (#114) nachzupflegen.
- **E-Mail-Adressen.** Ohne die gibt es keinen Magic-Link-Zugang für die
  Mitglieder.
- **Funktionen** (Übungsleiter, Vorstand …), **Mannschaften/Kader**, Beiträge,
  Ehrungen.

## Etappen

1. **Schema**: Feld `staatsangehoerigkeit` am Mitglied — `SCHEMA_VERSION`
   hochzählen, `_migrate_vN_to_vN+1`, Frischaufbau und Migration gleichziehen,
   Anzeige im Mitglied-Dialog.
2. **`linear_import_service.py`**: Parser (Kodierung, Datum, Kreuz-Spalten) und
   Mapping. Dabei prüfen, was sich mit dem SPG-Service teilen lässt (Kontakte,
   Abteilungs-Matching, Update-Pfad) — gemeinsame Teile herausziehen statt
   kopieren.
3. **Endpunkt** `POST /api/import/linear` analog `/spg`; ImportPage um eine
   Formatauswahl erweitern.
4. **Tests**: Parser-Einheiten (Kodierungsvarianten, Leerzeilen, Datum,
   Kreuz-Spalten, fehlende Pflichtfelder) und ein Integrationstest gegen den
   Wegwerf-Postgres — Dry-Run und Commit.

## Offene Fragen

- Welche Werte kann **„Status"** in LINEAR annehmen? Der Auszug zeigt nur
  „Aktiv". Gibt es Passiv-/Austritts-Sätze im Echt-Export?
- Enthält der Echt-Export **weitere Spalten** als der Auszug (z. B. E-Mail,
  Funktionen)? Das Mapping oben beschreibt nur den bekannten Spaltensatz.
- **Dubletten mit dem Bestand**: Können Personen gleichzeitig aus dem
  SPG-Import und aus LINEAR kommen? Wenn ja, braucht der Dry-Run einen
  Namens-/Geburtsdatums-Abgleich als Warnung — der `[LINEAR:…]`-Vermerk erkennt
  nur eigene Wiederholungsläufe.
- Wird LINEAR **einmalig** übernommen oder wiederholt abgeglichen? Bei einmalig
  reicht der Import; bei wiederholt lohnt ein Blick darauf, welche Felder in
  der App führend sind und nicht überschrieben werden dürfen.
