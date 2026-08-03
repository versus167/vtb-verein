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
| `VTB_STORAGE_SECRET` | Sessions/Cookies |
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

- Die **Ticket-Brücke** (`tools/vtb_tickets.py` + `tools/tickets.local.env`)
  zeigt auf genau eine Instanz. Bei zwei Instanzen braucht es zwei
  Konfigurationen — und eine Entscheidung, wo Entwickler-Tickets leben: der
  Bereich „VTB-App" existiert dann zweimal, oder Meldungen aus Instanz B müssen
  in die eine Entwicklungs-Instanz gespiegelt werden.
- Die **Feedback-Funktion** in der App legt Tickets in der jeweils eigenen
  Instanz an — für Vereinsanliegen richtig, für Bugs an der Software nicht.
- **Zugriff des Entwicklers** auf Echtdaten des zweiten Vereins: eigener
  Account, dokumentiert, und ein AV-Vertrag. Kein geteiltes Admin-Konto.

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

## Offene Fragen

- Läuft die zweite Instanz auf **demselben Host** oder getrennt? Auf demselben
  Host teilen sich beide Instanzen Ausfälle, Ressourcen und die Postgres-Version.
- Wie viel **Branding** ist gefordert? Nur Name und Logo ist überschaubar;
  eigene Vereinsfarben bedeuten Arbeit am Theme.
- Wer betreibt die zweite Instanz — dieselbe Person oder der zweite Verein
  selbst? Davon hängen Update-Prozess, Zugriffsrechte und Datenschutz ab.
