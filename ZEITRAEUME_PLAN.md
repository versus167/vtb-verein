# Plan: Zeiträume bei Abteilungs-Zuordnungen und Funktionen

> Status (2026-08-20): **A–E umgesetzt** auf `feature/zuordnung-wechsel`, 1792 Tests
> grün. **F ist beschlossen, aber nicht umgesetzt** – „passiv" wird eine Funktion,
> und damit fällt der Abteilungs-Status ganz weg. Anlass war die Frage, ob ein Wechsel „ab 1.8. passiv" richtig
> abgerechnet wird — er wird es, wenn die Daten stimmen, und die Oberfläche sorgte
> bis dahin dafür, dass sie es nicht tun.
>
> Drei Abweichungen vom Entwurf, jeweils dort vermerkt: Die Warnung kommt aus einem
> eigenen Vorab-Endpunkt statt aus der Wechsel-Antwort (sie muss *vor* dem Klick
> stehen), sie nennt keine Beträge, und der Zeitfilter fehlte nicht nur in
> `abteilungsuebersicht`, sondern auch im Abteilungs-Scope und in `exists_active`.

## Der Befund

`mitglied_abteilung` und `mitglied_funktion` führen beide `von`/`bis`. Der
Beitragslauf liest genau diese Felder und rechnet daraus monatsgenau
(`aktive_monate_menge`, „angefangener Monat zählt voll"); Funktions-Einschlüsse
und -Ausnahmen wirken über dieselbe Zeitachse
(`funktions_monats_restriktion`). Das Modell kann also alles, was gebraucht wird.

Kaputt geht es bei der **Pflege**: Beide Dialoge schreiben Änderungen in die
*bestehende* Zeile (`PUT …/abteilungen/{id}` bzw. `PUT …/funktionen/{id}`). Wer
den Status auf „passiv" umstellt, macht das Mitglied damit rückwirkend für die
gesamte Laufzeit passiv. Wer bei einer Funktion die Abteilung ändert, verschiebt
die ganze Vergangenheit mit.

Gemessen an einem Abteilungsbeitrag von 10 €/Monat im Quartalsturnus, Wechsel
zum 1.8., Lauf für Q3:

```
MIT Zeitschnitt (zwei Zeilen)        2026-Q3: 10,00 € – 1 von 3 Monaten
OHNE Zeitschnitt (Status umgestellt) keine Sollstellung – das Quartal fällt komplett aus
```

Der zweite Fall ist der, den die App heute erzeugt. Er meldet keinen Fehler: Es
fehlt schlicht eine Position im Lauf, und das merkt nur, wer nachrechnet.

## Kernidee: Korrektur oder Wechsel — die Oberfläche muss fragen

Zwei Änderungen sehen im Formular identisch aus und meinen das Gegenteil:

* **Korrektur** — „das Von-Datum war vertippt", „war von Anfang an passiv".
  Gehört in die bestehende Zeile, genau wie heute.
* **Wechsel** — „ist ab August passiv", „macht ab September Volleyball statt
  Tischtennis". Braucht einen Schnitt: alte Zeile auf `bis` = Vortag, neue Zeile
  ab dem Stichtag.

Deshalb: Ändert sich an einer **laufenden** Zuordnung das *Was* (Status; bei
Funktionen die Funktion oder die Abteilung), fragt der Dialog nach — mit dem
**Ersten des laufenden Monats** als Vorschlag für den Schnitt. Ändert sich nur
ein Datum, bleibt es beim stillen Update.

Ein Muster für beide Stellen, nicht zwei Sonderfälle.

## Der Schnitt liegt immer auf einem Monatswechsel

`aktive_monate_menge` zählt einen Monat voll, sobald ihn das Intervall an **einem
Tag** berührt — und das gilt für beide Zeilen. Ein Schnitt zum 15.8. lässt den
August deshalb in der alten *und* in der neuen Zeile landen:

| Zeile | Zeitraum | zählt August |
|---|---|---|
| alt: Tischtennis | … – 14.08. | ja |
| neu: Volleyball | ab 15.08. | ja |

Bei zwei beitragspflichtigen Abteilungen wird der August damit doppelt berechnet;
bei aktiv → passiv bleibt er voll berechnet, obwohl der halbe Monat gemeint war.
Beides meldet der Lauf nicht — es steht nur eine Position zu viel bzw. ein zu
hoher Betrag da. Derselbe stille Fehler wie oben, nur mit umgekehrtem Vorzeichen.

Deshalb ist `ab` **immer ein Monatserster**, und zwar als Regel im Backend (422
sonst), nicht bloß als Vorbelegung im Formular. Wer „ab Mitte August" wechselt,
meint fachlich ohnehin entweder den 1.8. oder den 1.9.; die Entscheidung trifft
die Oberfläche nicht heimlich, sondern lässt sie treffen.

## Was heute schon da ist (und nicht neu gebaut werden muss)

* Beide Listen im Mitglied-Dialog zeigen **alle** Zeilen, auch beendete und
  künftige, jeweils mit „ab … bis …" als Unterzeile.
* Jede Zeile hat bereits **Bearbeiten** und **Löschen** (rechte-abhängig über
  `canWrite`/`canDelete`).
* Die Historie der Zuordnungen steht zusätzlich in der Personen-Historie
  (`*_history`), inklusive „wer hat wann geändert".

Was fehlt, ist also nicht die Sichtbarkeit, sondern die **Unterscheidbarkeit**:
Eine 2024 beendete Zeile sieht aus wie eine laufende, und sortiert wird nach
Abteilungs- bzw. Funktionsname, nicht nach Zeit.

## Umsetzung

### A) Wechsel als eigener Vorgang (Backend) *(umgesetzt)*

Zwei neue Endpunkte, je einer für Zuordnung und Funktion:

```
POST /api/mitglieder/{mitglied_id}/abteilungen/{id}/wechsel   { ab, status, expected_version }
POST /api/mitglieder/{mitglied_id}/funktionen/{id}/wechsel     { ab, funktion, abteilung_id, expected_version }
```

Ein Endpunkt statt „Client schickt PUT und dann POST", weil beides **zusammen**
gelten muss: Bricht der zweite Aufruf ab, stünde sonst eine beendete Zuordnung
ohne Nachfolger da — jemand wäre still aus seiner Abteilung verschwunden. Der
Endpunkt setzt in einer Transaktion `bis` = `ab` − 1 Tag auf der alten Zeile und
legt die neue ab `ab` an.

Regeln:

* `ab` ist ein **Monatserster** (s. o.) — sonst 422.
* `ab` muss **nach** dem `von` der alten Zeile liegen (sonst ist es eine
  Korrektur, kein Wechsel) und darf nicht hinter einem gesetzten `bis` liegen.
* Die alte Zeile behält ihren Status/ihre Funktion — sie beschreibt die
  Vergangenheit und wird nicht umgeschrieben.
* `expected_version` wie überall (optimistisches Sperren).
* Ist die alte Zeile bereits beendet (`bis` in der Vergangenheit), gibt es
  nichts zu schneiden → 409 mit dem Hinweis, eine neue Zuordnung anzulegen.
* Ein **rückwirkender** Schnitt ist erlaubt — auch in ein abgerechnetes Quartal.

*Umgesetzt, mit einer Abweichung:* Die betroffenen Zeiträume kommen nicht aus der
Antwort des Wechsels, sondern aus einem eigenen Vorab-Endpunkt
`GET /api/mitglieder/{id}/abrechnung-betroffen?ab=…`. Zwei Gründe: Die Warnung muss
*vor* dem Klick stehen, nicht danach — und sie nennt nur Zeitraum-Labels, keine
Beträge. Wer Personen pflegen darf, sieht deshalb keine Beitragsdaten.

### B) Die Rückfrage (Frontend) *(umgesetzt)*

Im Bearbeiten-Dialog beider Listen: Wird an einer laufenden Zeile das *Was*
geändert, erscheint statt „Speichern" eine Auswahl.

```
Was hat sich geändert?
( ) Korrektur – der Eintrag war von Anfang an falsch
(•) Wechsel – gilt ab [ 01.08.2026 ▾ ]   nur Monatserste wählbar
                Die bisherige Zeile endet dann am 31.07.2026.
```

Vorbelegt ist der Erste des laufenden Monats. Der Datumswähler lässt nur
Monatserste zu (`options` in `q-date`) — die Regel steht im Backend, aber sie
soll gar nicht erst verletzt werden können.

Nur „Korrektur" schickt das bisherige `PUT`, „Wechsel" den neuen Endpunkt. Bei
reinen Datumsänderungen erscheint die Frage nicht.

**Rückwirkend in ein abgerechnetes Quartal** ist erlaubt, aber nicht stillschweigend:

```
⚠ Für 2026-Q3 wurde bereits abgerechnet (30,00 €).
  Die Sollstellung muss **gelöscht** und der Lauf wiederholt werden.
  Nicht stornieren: Storno heißt „diesmal nicht abrechnen" – die korrigierte
  Forderung entstünde dann nie.
```

Der Unterschied ist keine Wortklauberei, sondern steht so im Endpunkt: Storno
(`PATCH …/sollstellungen/{id}`) lässt die Sollstellung bestehen und die erneute
Abrechnung überspringt sie; Löschen (`DELETE …`) heißt „für diesen Zeitraum wurde
nichts abgerechnet", und der nächste Lauf legt sie neu an — mit den korrigierten
Monaten. Wer hier storniert, hat die falsche Forderung weg und die richtige nie.

Ob die Sollstellung schon an die Fibu übergeben wurde, hindert das Löschen nicht
— die Gegenbuchung entsteht dann im nächsten Export (#165). Einen Bezahlt-Zustand
gibt es hier nicht: Zahlung und Ausgleich führt die App grundsätzlich nicht, das
passiert in der Fibu. Die Warnung nennt deshalb Zeitraum und Betrag und sonst
nichts.

### C) Vergangenes kenntlich machen *(umgesetzt)*

* Sortierung beider Listen nach Zeit statt nach Namen: laufend zuerst, dann
  künftig, dann beendet (absteigend).
* Beendete Zeilen gedämpft mit Kennzeichen („beendet"), künftige wie bisher mit
  „ab …" (Ticket #91).
* Damit wird die vorhandene Bearbeiten/Löschen-Möglichkeit auch für alte Zeilen
  brauchbar: Man sieht, was man korrigiert.

### D) Queries geradeziehen *(umgesetzt, weiter gefasst)*

`abteilungsuebersicht()` prüft `ma.status = 'aktiv'`, aber **nicht** `ma.von`/
`ma.bis` — eine vor Jahren beendete Zuordnung zählt heute mit. Das widerspricht
der Kennzahl „davon in Abteilungen" (v2026.08.19.204), die es richtig macht.
Beim Schnitt-Umbau mitziehen, sonst entstehen erst recht beendete Zeilen, die
weiter mitgezählt werden.

Beim Umbau kamen zwei weitere Stellen mit demselben Fehler dazu:

* Der **Abteilungs-Scope** der KPIs (`_scope`) joint ebenfalls nur über
  `status = 'aktiv'`. Dadurch zählte `gesamt` beendete Zuordnungen mit, während
  `aktiv_in_abteilung` sie korrekt ausließ — die beiden Zahlen liefen auseinander.
* `exists_active` (Duplikatschutz beim Anlegen) kannte nur „Zeile vorhanden".
  Damit ließ sich niemand wieder in eine Abteilung aufnehmen, die er verlassen
  hat — und mit dem Wechsel wird die beendete Zeile zum Normalfall.

Die Bedingung steht jetzt einmal als `_laeuft_heute(alias)` und wird an allen drei
Stellen benutzt.

### E) Abteilungs-Status eindampfen *(umgesetzt, Schema v104)*

`VALID_STATUS = ('aktiv', 'passiv', 'trainer', 'vorstand', 'ehrenmitglied')`
trägt zwei Dinge in einem Feld: Beitragsrelevanz (aktiv/passiv) und Rolle. Weil
beides dieselbe Spalte belegt, kann ein „trainer" nicht passiv sein — und zahlt
über die Grundregel „alle außer passiv" automatisch. Rollen gehören zu den
Funktionen (Datum, Abteilung, Rechte, monatsgenaue Beitragsauswertung).

Zwei Fallen steckten im Bestand. Beide löst die Migration, ohne vorher zählen zu
müssen — weil es in beiden Fällen genau eine Abbildung gibt, die **nichts an der
Abrechnung ändert**:

1. **Wohin mit den alten Werten?** Auf `aktiv`. Beitragsfrei war bisher allein
   `passiv` (`ABTEILUNG_STATUS_BEITRAGSFREI`); `trainer`, `vorstand` und
   `ehrenmitglied` waren also beitragspflichtig und bleiben es. Auf `passiv`
   abzubilden — naheliegend bei „Ehrenmitglied" — hieße, jemandem den Beitrag
   stillschweigend zu erlassen. Wer wirklich beitragsfrei sein soll, wird danach
   einzeln umgestellt: eine Entscheidung, keine Nebenwirkung.
2. **Zeigt eine Beitragsregel darauf?** `bedingung_abteilung_status` ist eine
   kommagetrennte Liste und kann `trainer` enthalten. Fiele der Wert weg, würde
   die Regel **still stumm** — keine Fehlermeldung, nur fehlende Beiträge. Die
   Migration schreibt solche Regeln deshalb mit (Wert → `aktiv`, entdoppelt) und
   protokolliert jede einzelne als Warnung.

Beides wird protokolliert, auch die Verteilung der vorgefundenen Werte — der
Deploy-Log sagt also, was tatsächlich umgestellt wurde.

Erst danach bleibt `status` zweiwertig, und das Modell lässt sich in einem Satz
erklären: *Eine Abteilungs-Zuordnung gilt von…bis und ist entweder aktiv oder
passiv; alles andere ist eine Funktion.*

## Was bewusst NICHT gemacht wird

* **Die History als Rechengrundlage.** Sie hält fest, *wann jemand etwas
  eingetragen hat* (Systemzeit), nicht *ab wann es gilt* (fachliche Zeit).
  „Ist seit Januar passiv", im März eingetragen, ergäbe dort März. Rückwirkende
  Korrekturen wären gar nicht abbildbar. Geprüft: Kein Service liest `*_history`
  — nur Prune (Aufräumen) und die Personen-Historie (Anzeige).
* ~~**„Passiv" als Funktion abbilden.**~~ Der Einwand war: Die Zuordnung hat doch
  schon von/bis, zwei Orte für dieselbe Beziehung wären das Muster aus #173. Er
  hält nicht — die Zuordnung hat ein Datum, der *Status daran* nicht. Siehe F.

## Betroffene Dateien

| Datei | Änderung |
|---|---|
| `backend/api/mitglied_abteilungen.py` | Endpunkt `…/wechsel` |
| `backend/api/mitglied_funktionen.py` | Endpunkt `…/wechsel` |
| `vtb_verein/app/db/mitglied_abteilung_repository.py` | Schnitt in einer Transaktion, Sortierung nach Zeit |
| `vtb_verein/app/db/mitglied_funktion_repository.py` | dito |
| `vtb_verein/app/db/statistik_repository.py` | `abteilungsuebersicht` um von/bis ergänzen (D) |
| `frontend/src/components/MitgliedEditDialog.vue` | Rückfrage, Kennzeichnung beendeter Zeilen |
| `frontend/src/utils/zeitraum.js` | **neu** – Monatserste, Vortag, beendet/künftig (Spiegel der Backend-Regeln) |
| `vtb_verein/app/services/mitgliedschaft.py` | `pruefe_wechselstichtag`, `zuordnung_beendet` |
| `vtb_verein/app/services/beitrags_service.py` | `zeitraum_ende`, `betroffene_zeitraeume` |
| `backend/core/validation.py` | `wechselstichtag_or_422`, `nicht_beendet_or_409` |
| `backend/api/mitglieder.py` | `GET …/abrechnung-betroffen` (Warnung ohne Beträge) |
| `vtb_verein/tests/test_wechsel_stichtag.py` | **neu** – Regeln + Endpunkte (36 Tests, ohne DB) |
| `vtb_verein/tests/test_zuordnung_wechsel_integration.py` | **neu** – Schnitt, Transaktion, Beitragslauf (10 Tests) |
| `vtb_verein/app/db/database.py` | Schema v104: CHECK + Migration (E) |
| `frontend/src/pages/BeitragsverwaltungPage.vue` | Status-Auswahl der Beitragsregel (E) |
| `vtb_verein/tests/test_abteilung_status_integration.py` | **neu** – Fresh == Migriert für v104 (9 Tests) |

A–D kamen ohne Schema-Schritt aus: `von`/`bis` gibt es in beiden Tabellen
bereits. E bringt Schema **v104** (CHECK auf zwei Werte plus Bestandsumstellung).

## Tests

* Wechsel erzeugt zwei Zeilen, die alte endet am Vortag, keine Lücke, keine
  Überlappung.
* Beitragslauf über den Wechselmonat: anteilige Monate wie oben gemessen
  (aktive Zeile Juli, passive ab August).
* Wechsel mit `ab` vor dem `von` der alten Zeile → 422.
* Wechsel mit `ab` mitten im Monat → 422 (die Regel, die den Doppelmonat verhindert).
* Gegenprobe zur Regel: Ein von Hand gesetzter Schnitt zum 15. berechnet den
  Monat in beiden Zeilen — der Test hält fest, *warum* es die Regel gibt.
* Wechsel an einer bereits beendeten Zeile → 409.
* Rückwirkender Wechsel in ein abgerechnetes Quartal: geht durch und meldet die
  betroffenen Sollstellungen zurück.
* Nach Löschen der Sollstellung und erneutem Lauf steht der korrigierte Betrag
  da (nach Storno dagegen keiner — der Fall, vor dem die Warnung schützt).
* Abbruch mitten im Wechsel lässt keine beendete Zeile ohne Nachfolger zurück
  (Transaktion).
* `abteilungsuebersicht` zählt beendete Zuordnungen nicht mehr mit.

## Entschieden (2026-08-20)

* **Stichtag:** der Erste des laufenden Monats, vorbelegt und überschreibbar —
  aber nur auf andere Monatserste. Ein Schnitt mitten im Monat ist kein zulässiger
  Sonderfall, sondern der nächste stille Abrechnungsfehler (s. o.).
* **Rückwirkender Wechsel:** erlaubt, auch in ein abgerechnetes Quartal, mit
  Warnung und dem ausdrücklichen Hinweis auf **Löschen statt Storno** der
  betroffenen Sollstellungen.


### F) „Passiv" wird eine Funktion *(beschlossen, nicht umgesetzt)*

Der Abteilungs-Status ist auch nach E noch der einzige Ort im Modell, an dem eine
Aussage über eine Person **kein eigenes Datum** hat. Im Beitragslauf ist er ein
reines Zeilen-Filter (`ma.status <> 'passiv'`); monatsgenau wird die Rechnung erst
dadurch, dass man die Zuordnung *aufteilt* — deshalb überhaupt Teil A. Eine
Funktion braucht diesen Umweg nicht: `funktions_monats_restriktion` wertet
Funktionen längst **monatsweise** aus, mit optionalem Abteilungsbezug
(`ausnahme_abteilung_ids`). Die Maschine ist da; der Status ist der Fremdkörper.

Dazu das Argument, das den Ausschlag gibt: Für den Erfasser ist es **dieselbe
Logik**. Ehrenmitglied, Übungsleiter, Vorstand, passiv — alles eine Sache mit
Zeitraum und optionaler Abteilung, an einer Stelle gepflegt.

#### Die Semantik fällt aus den Regeln, nicht aus einem Sonderfall

Eine Beitragsregel hat einen Abteilungsbezug oder keinen. Die `passiv`-Funktion
auch. Daraus ergibt sich alles:

| `passiv` gilt … | Vereinsbeitrag (Regel ohne Abteilung) | Abteilungsbeitrag TT | Abteilungsbeitrag VB |
|---|---|---|---|
| für Abteilung TT | zahlt | entfällt | zahlt |
| vereinsweit (ohne Abteilung) | zahlt | entfällt | entfällt |

Ausgeschlossen werden also nur Regeln **mit** Abteilungsbezug; der Vereinsbeitrag
läuft weiter. Das ist keine neue Festlegung, sondern die heutige: „Passiv in der
Abteilung heißt nicht passiv im Verein."

#### Das Feld „Beitragspflichtiger Abteilungs-Status" fällt ersatzlos weg

Beides, was es heute ausdrückt, sagen Bedingung und Ausnahme ohnehin — und zwar
mit Zeitraum, den das Feld nie hatte:

| heute im Status-Feld | künftig |
|---|---|
| leer (= alle außer passiv) | **Ausnahme** `passiv` |
| `passiv` (reduzierter Passiv-Beitrag) | **Bedingung** `passiv` |
| `aktiv,passiv` (alle) | weder noch |

Damit steht in der Regel, was sie tut, statt in einem zweiten Feld daneben.

Der Preis: Der Ausschluss ist nicht mehr eingebaut, sondern muss je Regel gesetzt
sein — wer ihn bei einer neuen Regel vergisst, rechnet Passiven den vollen Beitrag
ab und merkt es beim Einzug. Die Bestandsregeln zieht die Migration nach (s. u.);
für neue braucht das Formular einen sichtbaren Hinweis, sobald ein
Abteilungsbeitrag `passiv` weder ein- noch ausschließt. Ein stiller Fehler wäre
genau das, wogegen dieser Plan angeht — eine gezeigte Entscheidung ist in Ordnung.

#### Migration (Schema v105)

1. Funktion `passiv` seeden.
2. Je Zuordnung mit `status = 'passiv'` eine `mitglied_funktion`-Zeile anlegen —
   dieselbe Abteilung, dasselbe `von`/`bis`.
3. Bestandsregeln umschreiben, jeweils mit dem Abteilungsbezug der Regel:
   * leer oder `'aktiv'` → `ausnahme_funktionen += ['passiv']`.
   * `= 'passiv'` → `bedingung_funktionen += ['passiv']` (der Passiv-Beitrag muss
     Passive weiterhin *treffen* — hier kehrt sich die Bedeutung um, das ist die
     Stelle, an der eine schlampige Migration Beiträge verlöre).
   * `= 'aktiv,passiv'` → weder noch, die Regel trifft dann alle.
4. `version`-Bump auf den Zuordnungen, damit der alte Status in
   `mitglied_abteilung_history` steht — **bevor** die Spalte fällt.
5. `mitglied_abteilung.status` entfernen, ebenso `bedingung_abteilung_status`
   und `ABTEILUNG_STATUS_BEITRAGSFREI`.

#### Was sonst noch mitgeht

* **Statistik:** „aktiv in Abteilung" fragt dann nach *laufender Zuordnung ohne
  laufende `passiv`-Funktion* (für diese Abteilung oder vereinsweit) — an allen
  drei Stellen von `_laeuft_heute`.
* **Oberfläche:** Der Status verschwindet aus dem Zuordnungs-Dialog und aus der
  Beitragsregel. Damit verliert die Wechsel-Rückfrage an der **Abteilungs-Zuordnung**
  ihren Auslöser (es bleibt nur noch das Datum, also immer Korrektur) — der
  **Funktions**-Wechsel bleibt und wird die Stelle, an der „ab August passiv"
  entsteht. Teil A wird dadurch für Zuordnungen obsolet; das ist in Ordnung, er
  hat den Fehler erst sichtbar gemacht.

#### Vorher zu lösen: die Abteilung im Paar meint heute etwas anderes

`bedingung_abteilung_ids` / `ausnahme_abteilung_ids` koppeln eine Funktion an eine
Abteilung — aber an die **Abteilungsmitgliedschaft**, nicht an die Abteilung der
Funktions-Zeile. Gemessen an `funktions_monats_restriktion`:

```
Person ist Übungsleiter FÜR Volleyball, aber Mitglied in Tischtennis.
Bedingung: Funktion 'uebungsleiter' + Abteilung Tischtennis
  → trifft alle drei Monate   (gelesen als „ÜL irgendwo UND Mitglied in TT")
  → gemeint wäre: leer        („ÜL für TT")
```

Der Grund steckt in `_monate_je_schluessel(..., 'funktion')`: Es gruppiert nur
nach Funktion, die `abteilung_id` der Funktions-Zeile fällt dabei weg. Bei „ÜL
Tischtennis" fällt das kaum auf, weil beides meist zusammenfällt. Bei `passiv` ist
es genau der Unterschied: „passiv in TT" darf nicht den VB-Beitrag treffen, und
umgekehrt.

F braucht deshalb, dass das Paar die Abteilung der **Funktions-Zeile** prüft
(zusätzlich oder statt der Mitgliedschaft). Das ist keine Zutat zu F, sondern
Voraussetzung — und es ist unabhängig davon schon heute schief: Was das Formular
verspricht („Je Zeile eine Funktion mit optionaler Abteilung") deckt sich nicht
mit dem, was gerechnet wird. Vor F zu klären, ob bestehende Regeln von der
Korrektur betroffen wären.

#### Zu klären, bevor es losgeht

`funktion` hat kein Schutz-Kennzeichen: Wer `passiv` in der Funktions-Verwaltung
löscht oder umbenennt, hebelt die Beitragsfreiheit aus — ohne Fehlermeldung, nur
mit Beiträgen für Passive im nächsten Lauf. Entweder bekommt die Tabelle ein
`system`-Flag (löschen/umbenennen gesperrt), oder der Service muss den Fall
merklich behandeln. Ein stummer Ausfall ist hier die schlechteste Variante — es
ist derselbe Fehlertyp, gegen den dieser ganze Plan angeht.
