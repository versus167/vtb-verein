# Notizen: zweite Produktiv-Instanz

> Status (2026-08-03): **Gedankensammlung, keine Entscheidung.** Anlass ist der
> LINEAR-Import (s. `LINEAR_IMPORT_PLAN.md`): Wenn dessen Daten aus einem
> anderen Verein stammen, endet das plausibel in einer eigenen Instanz.

## Grundsatzfrage zuerst

**Zweite Instanz** (zweiter Stack: eigene DB, eigene Domain, eigene Container)
gegen **Mandantenfähigkeit im Code** (`verein_id` in jeder Tabelle, jeder
Abfrage, jeder ACL, jedem Export).

Empfehlung: **zweite Instanz.** Mandantenfähigkeit nachzurüsten hieße, jedes
Repository, jede Berechtigungsprüfung und jeden Export anzufassen — bei zwei
Vereinen steht der Aufwand in keinem Verhältnis, und jeder vergessene Filter
ist ein Datenleck über Vereinsgrenzen hinweg. Der Preis der zweiten Instanz ist
doppelter Betrieb, nicht doppelte Entwicklung.

Aber: Der Code ist heute nicht *vereinsneutral*, sondern *VTB-spezifisch*. Das
ist der eigentliche Arbeitsanteil — nicht das Aufsetzen des Stacks.

## Was pro Instanz zwingend getrennt gehört

| Sache | Warum |
|---|---|
| Datenbank | Eigene DB **und** eigene Rolle, nicht nur ein anderes Schema |
| `./uploads`-Volume | Rechnungsanhänge, Ticket-Bilder, Belege |
| `VTB_VAULT_KEY` | Tresor-Verschlüsselung. Eigener Schlüssel je Instanz, niemals teilen — und niemals verlieren, sonst sind die Tresordaten unlesbar |
| `VTB_SECRET_KEY` | Signatur der Session-Tokens. Geteilter Schlüssel = Sitzungen der einen Instanz gelten in der anderen |
| VAPID-Schlüsselpaar | Web-Push hängt an Origin **und** Schlüsselpaar; geteilte Keys auf zwei Domains geben unzustellbare Subscriptions |
| `BASE_URL` | Steckt in Magic-Links und in der Wappen-URL der Mails. Falsch gesetzt = Login-Links zeigen auf die andere Instanz |
| `MAIL_FROM` / SMTP | Eigener Absender je Verein, inkl. SPF/DKIM für die Domain |
| TTLock-Zugang | Eigenes Konto. Achtung: die Callback-URL ist global pro Developer-App (s. Ticket #61) — zwei Instanzen an einer App sind nicht sauber trennbar |
| Backups | DB **und** `uploads`, getrennt je Instanz |

## Was heute fest verdrahtet ist

Die Vereinsidentität liegt an vier unabhängigen Stellen. Wer nur eine ändert,
bekommt einen Mischmasch:

1. **Farben**: `frontend/src/css/quasar.variables.scss` (`$vtb-blau`,
   `$vtb-gelb` und die daraus abgeleiteten Navy-/Hell-Töne).
2. **Theme**: `frontend/src/css/app.scss` — der „VTB-Look" (blaue Flächen auf
   Vereinsgelb) und der Dark Mode sind ~500 Zeilen, die auf genau diesen zwei
   Farben aufbauen. Ein Verein mit Rot/Weiß bekommt hier echte Arbeit, kein
   Variablen-Tausch. (Hängt mit Ticket #131 zusammen: ein neutraleres Theme
   würde die zweite Instanz billiger machen.)
3. **Mail-Layout**: `vtb_verein/app/services/email_service.py` — eigene
   Hex-Konstanten (`_VTB_BLAU`, `_VTB_GELB`), Wappen-URL, „VTB Chemnitz" in
   Kopf und Signatur, Betreffzeilen („Login-Link für VTB Vereinsverwaltung").
4. **Bilder**: `frontend/public/icons/vtb-wappen-512.png`, Favicons,
   `apple-touch-icon.png`, `mstile-150x150.png`, `browserconfig.xml`.

Dazu die Textstellen:

- `frontend/src/layouts/MainLayout.vue` — Dokumenttitel und Kopfzeile („VTB –
  <Seite>").
- `frontend/src/pages/LoginPage.vue` — Wappen, „VTB Chemnitz",
  „Vereinsverwaltung".
- PWA-Manifest und `index.html` (App-Name auf dem Homescreen).

Und die Seed-Daten in `database.py::_seed_data`, die einen Fußballverein
annehmen: Ticket-Bereiche „Platz 1", „Platz 2", „Kabinen", „Vereinsheim",
„Aussenanlage" samt Kategorien. Für einen anderen Verein passt das nicht
zwingend — entweder anpassbar machen oder nach dem Aufsetzen in der App
korrigieren.

Schließlich `docker-compose.yml`: die Container heißen fest `vtb-pg`,
`vtb-verein`, `vtb-zutritt-sync`, `vtb-clubdeckel-beitrag`, dazu feste Ports
und `./pg_data`. Auf demselben Host kollidiert das — Namen, Ports und Pfade
müssen je Instanz variabel sein (Compose-Projektname oder eigenes Verzeichnis).

## Was ohne Code pro Verein gepflegt wird

Das meiste Vereinsspezifische liegt schon in der DB und ist damit automatisch
getrennt: Abteilungen, Funktionen und Rechte, Beitragsregeln, Gebühren, Kassen,
Tresor, Schließanlage, Prune-Einstellungen — und wichtig für die Buchhaltung:
**Fibu-Einstellungen** (Berater-/Mandantennummer, Kostenstellen) sowie
**SEPA-Gläubiger-ID, -Name und -IBAN** stehen in `fibu_einstellungen`, nicht im
Code. Hier ist nichts zu tun außer Pflege.

## Betrieb

- **Ein Codestand, zwei Deployments.** `VERSION` ist global; die Instanzen
  können trotzdem auf unterschiedlichen Ständen laufen. Reihenfolge festlegen —
  die kleinere Instanz zuerst als Kanarienvogel ist der billigere Weg.
- **Migrationen laufen beim Start automatisch** (`SCHEMA_VERSION`). Das heißt:
  Update = Migration, ohne Rückfrage und ohne Downgrade-Pfad. Vor jedem Update
  ein Backup, und zwar je Instanz.
- **Der Frischaufbau wird erstmals produktiv genutzt.** Die bestehende Instanz
  ist über Migrationen gewachsen; `_create_tables` & Co. sind bisher nur in
  Tests gelaufen. Genau deshalb gilt „Fresh == Migriert" — vor dem Aufsetzen
  einmal beide Pfade gegeneinander prüfen (leere DB vs. durchmigrierte DB,
  Schema-Diff), damit Instanz B nicht subtil anders aussieht als Instanz A.
- **Reverse-Proxy/TLS** für zwei Domains; heute exponiert der Stack nur Ports.
- **Monitoring und Logs** getrennt, sonst ist im Fehlerfall unklar, wer betroffen ist.

## Support und Entwicklung

- **Entschieden (2026-08-06): kein zweites Profil der Ticket-Brücke.** Externe
  Nutzer melden Fehler an der Software über **GitHub Issues**, nicht über die
  App. Die Brücke (`tools/vtb_tickets.py`) bleibt damit auf die VTB-Instanz
  gerichtet, der Bereich „VTB-App" existiert nur dort.
- Die **Feedback-Funktion** in der App legt Tickets weiterhin in der jeweils
  eigenen Instanz an — für Vereinsanliegen richtig. Meldungen zur Software
  landen in Instanz B also zunächst beim dortigen Admin, der sie nach GitHub
  weiterträgt. Die Adresse ist in der App bereits vorhanden: `/api/app-info`
  liefert `source_url` (AGPL §13), heute als Quell-Link im Menü.
- **Zugriff des Entwicklers** auf Echtdaten des zweiten Vereins: eigener
  Account, dokumentiert. Kein geteiltes Admin-Konto. Betreibt der Verein selbst
  (s. Entscheidung unten), ist er datenschutzrechtlich Verantwortlicher — ein
  Auftragsverarbeitungsvertrag entsteht erst dadurch, dass für Support Zugriff
  auf Echtdaten eingeräumt wird. Im Zweifel juristisch prüfen lassen.

## Fallen, die beim ersten Aufsetzen zubeißen

- Der **Standard-Admin** (`admin` / `admin123`) wird beim Frischaufbau
  angelegt; das Log warnt. Bei einer erreichbaren Instanz sofort ändern —
  besser noch, vor dem ersten Öffnen nach außen.
- **Push-Subscriptions** hängen an Origin und VAPID-Key. Ein späterer
  Domainwechsel entwertet alle Abos, die Nutzer müssen neu zustimmen (das
  Muster kennen wir schon vom Umzug auf `app.vtbchemnitz.de`).
- **Mitgliedsnummern** laufen je Instanz eigenständig — beim Import aus LINEAR
  ist das genau richtig (s. Entscheidung 2 dort), aber es heißt auch: Nummern
  sind über Instanzen hinweg nicht eindeutig.
- **`VTB_COOKIE_SECURE`** muss hinter TLS auf 1 stehen, sonst wandern
  Session-Cookies unverschlüsselt.

## Vereinsneutral machen — Diskussionsstand (2026-08-03)

Festgehalten als Richtung; entschieden ist bisher nur der Zuschnitt der
Seed-Daten (s. u.). Reihenfolge und Umfang des Restes stehen noch offen.

### Seed-Daten

**Entschieden (2026-08-05): Bereiche und Kategorien werden beim Start jeweils
auf genau einen Eintrag „Allgemein" eingedampft.** Statt heute sechs Bereichen
(„Platz 1", „Kabinen", „Aussenanlage" …) und sechs Kategorien („Schaden",
„Sicherheit", „Reinigung" …) startet eine frische Instanz mit je einem
neutralen Eintrag; alles Weitere legt der Verein über die Ticket-Verwaltung an.

Die Bereiche unterstellen einen Fußballverein mit eigener Anlage — das war klar.
Die Kategorien wirken zwar vereinsneutraler, sind aber dieselbe Vorannahme in
schwächerer Form: „Schaden" und „Reinigung" beschreiben eine Liegenschaft, nicht
einen Verein. Eine vorgefundene Liste wird außerdem selten aufgeräumt, sondern
mitgeschleppt.

Warum je *ein* Eintrag statt gar keinem: `bereich_id` und `kategorie_id` sind
zwar nullable, aber ohne Bereich greifen die Bereichsrechte nicht und der
Auswahl-Dialog steht leer. Ein einzelner Startwert hält beides funktionsfähig,
ohne etwas zu behaupten.

Betrifft nur den Frischaufbau: `_seed_data` läuft einmalig beim Anlegen des
Schemas, bestehende Instanzen behalten ihre gepflegten Bereiche und Kategorien.
Hier ist „Fresh == Migriert" ausdrücklich **nicht** gemeint — Seed-Daten sind
Startwerte, keine Struktur.

### Env-Namen

Vereinheitlichen ja, ersatzlos streichen nein. Heute ist die Benennung
inkonsistent (`VTB_DATABASE_URL`, `VTB_PORT`, aber `SMTP_*`, `MAIL_FROM`,
`BASE_URL`, `VAPID_*`, `TTLOCK_*` ohne Präfix). Ein neutrales `APP_` ist besser
als gar kein Präfix: `PORT`, `HOST`, `SECRET_KEY`, `DATABASE_URL` sind so
generisch, dass sie sich im Container mit anderer Software überschneiden.

**Bruchgefahr:** Das Umbenennen trifft die laufende Instanz. Eine Release lang
beide Namen lesen (neuer zuerst, alter als Fallback), sonst startet die
Produktivinstanz nach dem Update ohne Datenbank-URL.

### Vereinsname und Kürzel

Zur Hälfte vorhanden: `VEREIN_NAME`, `VEREIN_STRASSE`, `VEREIN_PLZ_ORT`,
`VEREIN_REGISTRIER_NR` stehen in `backend/core/config.py` — sie werden aber nur
für PDF-Belege genutzt, nicht für Oberfläche und Mails. Das **Kürzel** fehlt.
Transportweg ins Frontend existiert ebenfalls schon: `/api/app-info` liefert
öffentlich Name, Version und Quell-Link. Dort kämen Kürzel (und später Farben)
dazu; Header, Login-Seite und Mail-Layout ziehen sich die Werte von da. Wenig
Aufwand, größter Hebel.

### Farben

Die Idee „eine helle und eine dunkle Farbe" trägt, mit drei Präzisierungen:

1. **Nach Rolle benennen, nicht nach Helligkeit.** Eine Farbe trägt *Flächen*
   (Karten, Header — muss weißen Text tragen können), die andere ist *Akzent*
   (muss dunklen Text tragen können). Damit ist der Kontrast-Vertrag explizit,
   und ein Verein mit zwei dunklen Farben (Blau/Schwarz) fällt sofort auf,
   statt ein unlesbares Ergebnis zu erzeugen.
2. **Abgeleitete Töne berechnen statt handmischen.** Heute stehen acht
   handgewählte Navy-Werte in `quasar.variables.scss`; aus zwei Eingangsfarben
   lassen sie sich per SCSS-Funktionen erzeugen. Ebenso die Textfarbe: statt
   der Regel „nie weiß auf Gelb" entscheidet ein Helligkeits-Helfer zwischen
   Schwarz und Weiß. Preis: Beim VTB verschiebt sich die Optik minimal — oder
   die aktuellen Werte werden als Ausnahme gepinnt.
3. **Build-Zeit gegen Laufzeit — der eigentliche Knackpunkt.** Name und Kürzel
   aus der Env wirken zur Laufzeit; SCSS-Farben werden beim Bauen eingebacken,
   und das Docker-Image enthält die fertige SPA. Zwei Vereine mit eigenen
   Farben heißen also entweder **zwei Images** oder ein Theme auf
   CSS-Variablen, das seine Werte aus `/api/app-info` bezieht — dann bleibt es
   ein Image und die zweite Instanz ist reine Konfiguration.

Vorschlag: Töne aus zwei Eingangsfarben berechnen und als CSS-Variablen auf
`:root` ausspielen, `app.scss` nur noch `var(--…)` verwenden lassen. Der
spätere Schritt „Werte kommen aus der Konfiguration" ist damit fast geschenkt.

**Berührungspunkt mit Ticket #131:** Ein neutraler Hintergrund mit
Vereinsfarben nur als Akzent ist genau die Struktur, die sich generalisieren
lässt. Der heutige Look mit Vereinsgelb als Seitenfläche überträgt sich am
schlechtesten auf einen anderen Verein — #131 zuerst zu machen, verbilligt die
zweite Instanz.

### Logo

Der unangenehmste Teil, weil es keine Konfiguration ist, sondern Dateien:
vierzehn in `frontend/public/icons/` (PWA 128–512, maskable, Apple 120–180,
MS-Kachel, dazu ein monochromes `safari-pinned-tab.svg`) plus Favicons und
`browserconfig.xml`. In die Env passt bestenfalls ein Pfad.

- **Pragmatisch:** Dateinamen neutralisieren (`vtb-wappen-512.png` →
  `logo-512.png`) und pro Instanz ein Verzeichnis über `/icons` mounten. Die
  Mail-Grafik zieht automatisch mit, sie ist nur `BASE_URL` + Pfad. Der
  Icon-Satz wird einmal von Hand erstellt — das maskable braucht
  Sicherheitsrand, das Safari-SVG ist einfarbig, dabei hilft kein Automatismus.
- **Komfortabel:** Logo-Upload in der App mit serverseitiger Ableitung aller
  Größen. Dafür fehlt heute eine Bildbibliothek in den Abhängigkeiten.

Tendenz: der pragmatische Weg.

### Branding-Ordner für Mail und Icons — entschieden (2026-08-05)

**Der pragmatische Weg wird gebaut**, und zwar für Icons *und* Mail-Layout
gemeinsam: ein Verzeichnis `branding/`, Pfad aus `VTB_BRANDING_PATH` (Default
`./branding`), im Docker als Volume gemountet — bewusst **nicht** im Image,
damit ein Image für alle Instanzen reicht. Ist der Ordner leer, läuft die App
mit neutralen Standards weiter.

Beim Nachsehen im Code (2026-08-05) zeigte sich, dass der Zuschnitt kleiner ist
als im Absatz oben angenommen: Die Icon-Referenzen heißen **bereits neutral**
(`favicon.ico`, `apple-touch-icon.png`, `icon-512x512.png`,
`mstile-150x150.png`). Der einzige Dateiname mit VTB darin ist
`vtb-wappen-512.png`, und den benutzt ausschließlich das Mail-Layout. Es muss
also fast nichts umbenannt werden.

**Icons.** Das Backend mountet `/icons` schon heute (`backend/main.py`, Mount
auf `frontend_dist/icons`). Daraus wird eine Schicht, die zuerst im
Branding-Ordner sucht und sonst auf das Ausgelieferte zurückfällt — **Fallback
je Datei, nicht alles-oder-nichts**. Das ist der wichtigste Punkt am Entwurf:
Sonst reicht ein vergessenes `apple-icon-180x180.png` und das PWA-Manifest ist
kaputt. So legt ein Verein nur ab, was er hat.

**Mail.** Hier entscheidet der Ordner über die Bauform:

- Logo im Branding-Ordner vorhanden → heutiges Layout mit Bild und
  Vereinsfarben.
- Nichts da → **vereinfachte Mail**: kein Bild, neutrale Typografie,
  Vereinsname als Text. Besser ein schlichter Brief als ein fremdes Wappen.

Die Texte in `email_service.py` („VTB Chemnitz" im Kopf, Signatur „VTB
Vereinsverwaltung", Betreff „Login-Link für VTB Vereinsverwaltung") kommen
künftig aus `VEREIN_NAME`/`VEREIN_KURZ` — die Werte stehen längst in der
Konfiguration, sie werden dort nur nicht benutzt. Die beiden Mail-Farben
(`_VTB_BLAU`, `_VTB_GELB`) werden Env-Werte mit neutralen Defaults; in der Mail
ist das billig, weil sie zur Laufzeit entsteht. Das SPA-Theme bleibt außen vor
— das ist der SCSS-/Build-Zeit-Brocken aus dem Farben-Abschnitt.

**Bewusst nicht in den Ordner:** Texte oder Templates als Dateien. Das wird
schnell ein zweites Template-System mit eigenem Wartungsbedarf. Name und Kürzel
aus der Env genügen, alles andere bleibt Code.

### Neutraler Icon-Satz in der Auslieferung — entschieden (2026-08-06)

**Was ausgeliefert wird, ist neutral; gebrandet wird über Env-Variablen und den
Branding-Ordner.** Der Name der Software bleibt „VTB-App" — das ist der
Produktname, keine Instanz-Beschriftung.

Folge, die man am Update-Tag nicht vergessen darf: **Danach ist auch der VTB
eine gebrandete Instanz.** Die Produktivinstanz zeigt neutrale Icons, bis ihr
Branding-Ordner das Wappen enthält — das gehört in den Deploy-Schritt, nicht in
die Nacharbeit.

**Korrektur am Entwurf oben:** Der `/icons`-Mount deckt nur den PWA-Satz ab.
`index.html` verweist zusätzlich auf `/favicon.ico`, `/favicon-16x16.png`,
`-32x32`, `-48x48` und `/apple-touch-icon.png`; dazu kommen
`mstile-150x150.png` und `browserconfig.xml`. Diese Dateien liegen im **Root**
von `frontend/public/` und werden über den SPA-Fallback ausgeliefert, nicht über
den Mount. Die Überlagerung braucht deshalb **zwei Stellen** — den Mount und
einen Vorrang-Griff im Fallback —, sonst bleibt das Browser-Tab-Icon fremd,
während die PWA schon stimmt.

Zu erzeugen sind damit (neutral, als Auslieferungs-Standard): `icon-128`, `-192`,
`-256`, `-384`, `-512`, `icon-maskable-512x512`, `apple-icon-120|152|167|180`,
`ms-icon-144x144`, `favicon-128x128`, `safari-pinned-tab.svg` sowie im Root
`favicon.ico`, `favicon-16|32|48x48`, `apple-touch-icon.png`,
`mstile-150x150.png` — und ein neutrales Logo als Ersatz für
`vtb-wappen-512.png` im Mail-Layout.

**Ein Fallstrick bleibt:** Im Dev-Server kommen die Icons aus
`frontend/public/`, nicht vom Backend. Die Überlagerung greift nur im echten
Betrieb, wo das Backend die SPA ausliefert — lokal sieht man immer den
ausgelieferten Satz.

Aufwandsverhältnis: Der Mail-Umbau ist der größere Teil (Layout plus drei
Mailtypen, Tests gegen feste Strings), die Icon-Überlagerung ist ein Mount und
ein Dateiname. Umsetzung gehört auf einen eigenen Branch von `master`.

## Stand der Umsetzung (2026-08-05)

Auf diesem Branch (`feature/linear-import`) liegt bereits:

- **Neutrale Seed-Daten** — je ein Bereich und eine Kategorie „Allgemein", eine
  Funktion „Vorstand" (`vtb_verein/app/db/database.py::_seed_data`). Folge: Die
  Blöcke, die Rechte an `uebungsleiter`/`abteilungsleiter` hängen, laufen frisch
  ins Leere; auf einer neuen Instanz vergibt der Admin die Funktionsrechte über
  die Oberfläche.
- **Kopfzeile und Browser-Tab** ziehen das Kürzel aus `/api/app-info`
  (`frontend/src/layouts/MainLayout.vue`) statt „VTB" fest zu verdrahten.
  Solange nichts geladen ist, bleibt das Präfix weg.
- **„Teamtresor" heißt „Teamkasse"** (nur die Bezeichnung; `clubdeckel` und die
  Rechte-Keys bleiben).

Noch offen und weiterhin VTB-fest: Login-Seite („VTB Chemnitz" + Wappen),
Mail-Layout (siehe Branding-Ordner), Farben in `quasar.variables.scss` und
`app.scss`, PWA-Manifest (`src-pwa/manifest.json`: Name und Kurzname).

## Testinstanz lokal starten

Frischer Aufbau gegen eine leere DB — damit lässt sich der Seed-Stand
anschauen, ohne eine gewachsene Instanz anzufassen:

```bash
docker start vtb-pg-test                     # postgres:18, Port 5432, User/PW vtb
docker exec vtb-pg-test psql -U vtb -d postgres -c "CREATE DATABASE frischstart;"

VTB_DATABASE_URL="postgresql://vtb:vtb@localhost:5432/frischstart" \
VTB_PORT=8000 VTB_COOKIE_SECURE=false \
VTB_VEREIN_KURZ="BSC" VTB_VEREIN_NAME="BSC Rapid Kappel" \
  ./venv/bin/python -m backend.main            # Schema + Seeds entstehen beim Start

cd frontend && npx quasar dev                  # Port 9000, Proxy auf 8000 (Node 22)
```

Login `admin` / `admin123` (der Standard-Admin aus dem Seed). `VTB_VEREIN_NAME`
wirkt derzeit nur in PDF-Belegen — in der Oberfläche ist bisher allein das
Kürzel sichtbar.

## Zuschnitt entschieden (2026-08-06)

Die vier Grundsatzfragen sind beantwortet. Sie hängen zusammen — zwei der
Antworten entscheiden Punkte mit, die oben noch offen standen.

| Frage | Antwort |
|---|---|
| Host | **Getrennte Hosts** |
| Branding | **Name, Kürzel, Logo *und* eigene Vereinsfarben** |
| Betrieb | **Der zweite Verein selbst** |
| Verbindlichkeit | **Konkret — Aufsetzen am 20.08.2026** |

**Getrennte Hosts** streichen die Compose-Parametrierung (feste Container-Namen,
Ports, `./pg_data`) ersatzlos — sie kollidieren nur auf einem gemeinsamen Host.
Der Verein braucht dafür eine eigene `docker-compose.yml` als Vorlage.

**Eigene Farben bei Fremdbetrieb schließen „zwei Images" aus.** Im Farben-Absatz
oben standen zwei Images und ein Laufzeit-Theme noch gleichwertig nebeneinander.
Baut der Betreiber nicht selbst, wäre ein instanzspezifisches Image ein zweiter
Build je Release und ein Artefakt, das nur für einen Verein existiert. Es bleibt
also: abgeleitete Töne als **CSS-Variablen auf `:root`**, Werte aus
`/api/app-info`, `app.scss` nur noch über `var(--…)`, **ein Image für alle**.

Damit rückt **Ticket #131 auf den kritischen Pfad**. Der heutige Look mit
Vereinsgelb als Seitenfläche lässt sich nicht parametrieren — ein neutraler
Grund mit den Vereinsfarben als Akzent ist die Voraussetzung dafür, dass zwei
Eingangsfarben überhaupt genügen. #131 ist damit keine Sparmaßnahme mehr,
sondern Vorarbeit.

**Fremdbetrieb macht die Auslieferung zum Produkt.** Das Deployment ist heute
undokumentiertes Kopfwissen. Dazu gehören mindestens: compose-Vorlage,
`.env.example` (vorhanden), eine Update- und eine Backup-Anleitung — und
ausdrücklich die zwei Stellen, an denen Fremdbetrieb wehtut: Migrationen laufen
beim Start **ohne Rückfrage und ohne Downgrade-Pfad**, und ein verlorener
`VTB_VAULT_KEY` macht die Tresordaten dauerhaft unlesbar.

**Software-Tickets brauchen einen Weg zurück.** Die Feedback-Funktion legt
Meldungen in der jeweils eigenen Instanz an — Bugs an der Software landen damit
in Instanz B, wo sie niemand sieht. Die Brücke (`tools/vtb_tickets.py`) zeigt
heute auf genau eine Instanz und braucht ein zweites Profil.

## Reihenfolge bis zum 20.08.2026

Zwei Wochen reichen nicht für alles. Der Maßstab ist deshalb nicht „fertig",
sondern **was am Starttag nicht fehlen darf**: Die Instanz muss auf einer leeren
DB sauber hochkommen, darf nirgends „VTB" sagen, muss brauchbare Mails
verschicken, die Mitgliederdaten tragen und vom Verein selbst betreibbar sein.
Ein noch nicht in Vereinsfarben getauchtes Theme ist am Starttag verzeihlich —
ein fremdes Wappen auf der Login-Seite oder ein fehlgeschlagener Import nicht.

**Woche 1 — das Unverzichtbare**

1. ~~**Schema-Diff Frischaufbau gegen Migration.**~~ **Erledigt am 2026-08-06**
   (s. u.) — zwei Abweichungen gefunden und mit Schema v87 eingeebnet.
2. **Neutraler Icon-Satz** als Auslieferungs-Standard (ersetzt den
   Wappen-basierten Satz in `frontend/public/`, Namen bleiben).
3. **Branding-Ordner** (`VTB_BRANDING_PATH`): Überlagerung mit Fallback je Datei
   an beiden Stellen (Mount `/icons` **und** Root-Favicons über den
   SPA-Fallback), Mail-Layout auf `VEREIN_NAME`/`VEREIN_KURZ` und Env-Farben,
   dazu die vereinfachte Mail ohne Logo.
4. **Restliche VTB-Texte**: Login- und Magic-Link-Seite, PWA-Manifest.
5. **LINEAR-Import** gegen den Muster-Export: Parser, Endpunkt, Formatauswahl,
   Tests — ohne Schema-Migration, seit die Staatsangehörigkeit draußen bleibt.

**Woche 2 — Betriebsfähigkeit und Puffer**

6. **Auslieferungs-Doku**: compose-Vorlage, Update- und Backup-Anleitung, die
   beiden Warnungen (Migration ohne Rückfrage, `VTB_VAULT_KEY` nicht verlieren),
   dazu der Hinweis auf GitHub Issues als Meldeweg für Software-Fehler.
7. **Ticket #131 / neutrales Theme**, so weit es trägt. Wenn es knapp wird,
   startet Instanz B mit dem neutralen Grund ohne eigene Vereinsfarben — die
   Parametrierung ist nachrüstbar, ohne dass die Instanz noch einmal aufgesetzt
   werden muss.
8. **Puffer für den Echt-Export**: Anpassung des Parsers und ein Probelauf als
   Dry-Run gegen die echten Daten.

**Was ausdrücklich nach dem Termin kommt:** die volle Farb-Parametrierung und
jede Verfeinerung am Theme. Ein zweites Profil der Ticket-Brücke ist gestrichen
(s. „Support und Entwicklung").

**Größtes Terminrisiko** ist der LINEAR-Echt-Export, weil er nicht in unserer
Hand liegt. Bisher gibt es nur den Muster-Auszug; die vier offenen Fragen im
`LINEAR_IMPORT_PLAN.md` (Status-Werte, zusätzliche Spalten, Dubletten mit dem
Bestand, einmalig oder wiederholt) lassen sich erst daran beantworten. Der
Parser entsteht deshalb gegen das Muster — er muss aber **spätestens am
17.08.** echte Daten gesehen haben, sonst ist der Import am Starttag ungeprüft.

## Schema-Diff: Ergebnis (2026-08-06)

Verglichen wurde eine frisch aufgebaute DB gegen das gewachsene Schema der
Dev-DB (Katalog-Abzug: Spalten, Constraints, Indexe, Trigger, Funktionsrümpfe
mit normalisiertem Whitespace). Von ~2.690 Katalogzeilen wichen **zehn** ab —
davon vier reine Einrückung. Übrig blieben zwei echte Funde, beide mit **v87**
behoben:

**1. Audit-Trigger ohne SEPA-Spalten (betraf die Produktivinstanz).**
v78→v79 hat `sepa_glaeubiger_id/-name/-iban/-bic` an `fibu_einstellungen` und
deren History gehängt, die Audit-Funktionen aber nicht neu erzeugt — dort stand
noch die Fassung aus v62→v63. Folge: Änderungen an den Gläubiger-Angaben landen
zwar in `fibu_einstellungen_history`, die fünf SEPA-Spalten bleiben dort aber
NULL. Kein Fehler, keine Warnung, nur eine still unvollständige Historie. Der
Frischaufbau war korrekt, weil er dieselbe Konstante nutzt — genau deshalb
konnte das nur der Vergleich beider Pfade zeigen. Alte History-Zeilen lassen
sich nicht nachfüllen; ab v87 wird wieder vollständig mitgeschnitten.

**2. Zwei Indexe fehlten im Frischaufbau (hätte Instanz B getroffen).**
`idx_ticket_teilnehmer_deleted_at` und `idx_ticket_teilnehmer_history_id`
entstanden nur in v43→v44, nicht in `_create_indexes`. Gewachsene DBs haben sie,
frisch aufgesetzte nie — also genau der Fall, um den es hier geht. Sie liegen
jetzt als geteilte Konstante `_TICKET_TEILNEHMER_INDEXES` in beiden Pfaden.

**Dauerhafte Absicherung:**
`vtb_verein/tests/test_audit_trigger_spalten_integration.py` prüft für jede
`*_history`-Tabelle, dass die Audit-Funktion jede Spalte mitschreibt, die es
auch in der Live-Tabelle gibt. Eine künftig vergessene Spalte fällt damit sofort
auf, egal in welcher Migration sie entsteht. (History-Spalten ohne Gegenstück in
der Live-Tabelle sind ausgenommen — `mitglied_history.email/telefon` etwa sind
Altbestand aus der Kontakt-Umstellung in v74 und halten nur alte Zeilen lesbar.)

Nach dem Fix bleibt zwischen beiden Pfaden nur noch eine
Einrückungs-Variante in `fn_mitglied_mannschaft_audit_*` — identische
Spaltenliste, semantisch gleich.

## Offene Fragen

- **Vereinsfarben** des zweiten Vereins (zwei Hexwerte: Fläche und Akzent) sowie
  der Icon-Satz. Ohne die Werte bleibt es beim neutralen Theme.
- Bekommt der Entwickler **Zugriff auf die laufende Instanz B** (Support,
  Fehlersuche) oder läuft alles über Exporte und Beschreibungen?
- **LINEAR-Echt-Export**: Termin für die Bereitstellung.
