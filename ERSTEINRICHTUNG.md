# Ersteinrichtung

Der Weg von „Repository geklont" bis „Verein arbeitet damit" — in der Reihenfolge,
in der die Schritte aufeinander aufbauen.

Diese Datei beschreibt den **Ablauf**. Was die einzelnen Variablen bedeuten, steht
vollständig und kommentiert in [`.env.example`](.env.example) — bitte dort
nachschlagen statt hier eine zweite Liste zu pflegen.

> Für eine **zweite Instanz neben einer bestehenden** kommen Betriebsthemen dazu
> (getrennte Volumes, Container-Namen, Ports, Backups): siehe
> [`ZWEITE_INSTANZ.md`](ZWEITE_INSTANZ.md).

## Was mindestens gesetzt sein muss

| Sorte | Variablen | Ohne sie … |
|---|---|---|
| **Pflicht** | `VTB_SECRET_KEY`, Datenbank (`VTB_DATABASE_URL` bzw. `VTB_PG_*`) | läuft die App unsicher bzw. gar nicht |
| **Dringend empfohlen** | `VTB_VAULT_KEY`, SMTP + `BASE_URL`, Vereins-Stammdaten | kein Passwort-Tresor, kein Login per Magic-Link, Instanz heißt „Beispielverein" |
| **Optional** | VAPID (Push), TTLock, Matrix, Branding-Ordner, Mail-Farben | fehlt nur die jeweilige Funktion, die App läuft normal |

## 1. Repository und `.env`

```bash
git clone https://github.com/versus167/vtb-verein.git
cd vtb-verein
cp .env.example .env
```

## 2. Geheimnisse erzeugen

**Vor dem ersten Start** — nicht später nachholen. Ein Wechsel des Signaturschlüssels
wirft alle angemeldeten Nutzer heraus, ein Wechsel des Tresor-Schlüssels macht
gespeicherte Passwörter unlesbar.

```bash
# Signaturschlüssel der Session-Tokens (JWT) – ohne ihn läuft die App mit dem
# Default aus dem öffentlichen Quellcode, und jeder kann sich Sitzungen ausstellen.
python -c "import secrets; print(secrets.token_urlsafe(48))"     # → VTB_SECRET_KEY

# Passwort-Tresor (At-rest-Verschlüsselung). Sicher aufbewahren: Geht der Schlüssel
# verloren, sind ALLE gespeicherten Passwörter unwiederbringlich weg.
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # → VTB_VAULT_KEY

# Web-Push (optional, kann später nachgezogen werden)
./venv/bin/python tools/gen_vapid_keys.py                        # → VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY
```

Die Werte in die `.env` eintragen. `VTB_VAULT_KEY` darf leer bleiben — dann ist nur
das Tresor-Feature deaktiviert (HTTP 503), die App läuft normal weiter.

## 3. Datenbank und Start

**Docker Compose** (empfohlen): `VTB_PG_USER`, `VTB_PG_PASSWORD`, `VTB_PG_DB`
setzen — der Stack baut `VTB_DATABASE_URL` daraus zusammen.

```bash
docker compose up -d --build
```

**Lokal:** eine erreichbare PostgreSQL-Instanz bereitstellen und
`VTB_DATABASE_URL` setzen (Details in der [README](README.md#option-2-lokale-entwicklung)).

**Zum Port:** `VTB_PORT` meint im Compose-Stack den Port auf dem *Host* — der
Container lauscht immer auf 8000, das steht fest im Dockerfile. Beim direkten
Start (`python -m backend.main`) ist es dagegen der Port der App selbst. Wer den
Wert ändert und im Container nichts anders vorfindet, sucht sonst länger.
`BASE_URL` muss in beiden Fällen die Adresse tragen, unter der Nutzer die App
erreichen — hinter einem Reverse-Proxy also dessen Adresse.

Schema und Startdaten entstehen **beim ersten Verbinden automatisch**; spätere
Updates migrieren beim Start ebenso automatisch. Im Log steht, was passiert ist:

```
Frische Datenbank – Schema v87 wird erstellt …
Standard-Admin erstellt: Username='admin', Passwort='admin123' - BITTE ÄNDERN!
Schema v87 erfolgreich angelegt.
```

Hinter TLS gehört `VTB_COOKIE_SECURE=true` (Default); für lokale http-Entwicklung
muss es auf `false`, sonst verwirft der Browser das Session-Cookie und die
Anmeldung schlägt ohne sichtbaren Grund fehl.

## 4. Erste Anmeldung

Anmelden mit `admin` / `admin123` — und **als erstes das Passwort ändern**, bevor
die Instanz von außen erreichbar ist.

## 5. Vereins-Stammdaten

Ohne diese Angaben nennt sich die Instanz überall sichtbar **„Beispielverein"** —
auf der Login-Seite, in der Kopfzeile, in System-Mails und auf PDF-Belegen. Das ist
Absicht: So fällt sofort auf, dass die Stammdaten noch fehlen.

Zu setzen sind `VTB_VEREIN_NAME`, `VTB_VEREIN_KURZ`, `VTB_VEREIN_STRASSE`,
`VTB_VEREIN_PLZ_ORT` und — falls vorhanden — `VTB_VEREIN_REGISTRIER_NR`. Das
Kürzel steht vor Mannschaftsnamen („VTB" + „AH" → im Spieltitel „VTB AH – SV X")
und in der Kopfzeile, gehört also kurz gehalten.

## 6. E-Mail (Magic-Link)

Ohne SMTP kann sich niemand außer dem Admin anmelden — der Login läuft über einen
per Mail verschickten Einmal-Link. Nötig sind `SMTP_*`, `MAIL_FROM` und
`BASE_URL`. **`BASE_URL` muss die Adresse sein, unter der Nutzer die App
erreichen** — sie steckt in jedem Login-Link und in den Bildern der Mails.

Danach eine Test-Mail auslösen (Login-Link anfordern) und prüfen, ob sie ankommt
und der Link zur richtigen Adresse führt.

## 7. Aussehen (optional)

- **Icons und Logo:** Ein Verzeichnis über `VTB_BRANDING_PATH` mounten; es
  überlagert die ausgelieferten Dateien **einzeln**. Was fehlt, kommt weiter aus
  der Auslieferung — ein leerer Ordner bedeutet also „neutrales Aussehen", keinen
  Fehler. Struktur wie `branding/vtb/`.
- **System-Mails:** `VTB_MAIL_FARBE_FLAECHE` und `VTB_MAIL_FARBE_AKZENT` setzen
  die beiden Vereinsfarben; `VTB_MAIL_LOGO=aus` schaltet auf eine schlichte Mail
  ohne Bild.
- Die **Farben der Oberfläche** stecken dagegen im Build (SCSS) und sind nicht per
  Env änderbar — siehe [`ZWEITE_INSTANZ.md`](ZWEITE_INSTANZ.md).

## 8. Zusatzfunktionen (optional)

| Funktion | Variablen | Ohne Konfiguration |
|---|---|---|
| Web-Push | `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` | Benachrichtigung fällt auf E-Mail zurück |
| Schließanlage | `TTLOCK_*` | Zutrittsfunktionen bleiben leer, Sidecar läuft im Leerlauf |
| Matrix-Nachrichten | `MATRIX_HOMESERVER_URL`, `MATRIX_BOT_USER_ID`, `MATRIX_BOT_TOKEN` | Kanal steht Nutzern nicht zur Verfügung |

## 9. Im Verein einrichten

Ab hier passiert alles **in der App**, nicht in Konfigurationsdateien: Abteilungen,
Funktionen und deren Rechte, Mitglieder, Beitragsregeln, Gebühren, Kassen,
Ticket-Bereiche und -Kategorien.

Eine frische Instanz startet bewusst schlank: je **ein** Ticket-Bereich und eine
Kategorie „Allgemein" sowie die Funktion „Vorstand". Alles Weitere legt der Verein
selbst an — insbesondere die Funktionen für Übungsleiter und Abteilungsleiter samt
ihren Rechten, sonst kann niemand ÜL-Stunden erfassen oder Rechnungen freigeben.

Die **Fibu-Einstellungen** (Debitor-Konto-Basis, Kostenstellen, Berater-/Mandanten-
nummer) und die **SEPA-Gläubigerdaten** stehen ebenfalls in der App, nicht in der
`.env`.

## Update einer bestehenden Instanz

Diese Anleitung beschreibt den Weg für eine *neue* Instanz. Eine bereits laufende
braucht beim Update auf diesen Stand zwei Handgriffe, die vorher unnötig waren —
beide, weil die App vereinsneutral geworden ist und Werte nicht mehr errät, die
früher fest im Code standen.

**1. Vereins-Stammdaten in die `.env` eintragen.** Die Defaults waren bis hierher
die Daten des VTB; jetzt sind es erkennbare Platzhalter. Eine `.env` ohne diese
Zeilen führt nach dem Update dazu, dass die Instanz sich überall „Beispielverein"
nennt — Login-Seite, Kopfzeile, Mail-Betreff und PDF-Belege inklusive Anschrift.
Betroffen sind `VTB_VEREIN_NAME`, `VTB_VEREIN_KURZ`, `VTB_VEREIN_STRASSE`,
`VTB_VEREIN_PLZ_ORT`, `VTB_VEREIN_REGISTRIER_NR` (s. Schritt 5).

**2. Image neu bauen, nicht nur neu starten.** Der Branding-Ordner liegt im Image;
`docker compose up -d` allein zieht ihn nicht mit:

```bash
docker compose up -d --build
```

Ohne `VTB_BRANDING_PATH` zeigt die App die neutrale Wortmarke statt des
Vereinswappens — die Icons sind dann nicht kaputt, nur unbeschriftet. Der
Compose-Stack setzt die Variable bereits auf `/app/branding/vtb`.

**Vorher ein Backup.** Migrationen laufen beim Start automatisch, ohne Rückfrage
und ohne Weg zurück. Gesichert gehören Datenbank **und** `uploads/`.

## Fehler melden

Für Fehler und Wünsche an der **Software** gibt es
[GitHub Issues](https://github.com/versus167/vtb-verein/issues).

Wichtig zu wissen: Die **Feedback-Funktion in der App** legt ein Ticket in der
*eigenen* Instanz an. Für Vereinsanliegen ist das richtig — eine Meldung über die
Software erreicht damit aber niemanden außerhalb des eigenen Vereins. Solche
Meldungen gehören auf GitHub.

Den Link zum Quellcode dieser Fassung trägt die App selbst (Menü-Fußzeile, aus
`/api/app-info`); das erfüllt zugleich AGPL §13. Wer eine veränderte Fassung
betreibt, muss dort über `VTB_SOURCE_URL` die eigene Quelle eintragen.

## Checkliste

- [ ] `.env` aus `.env.example` angelegt
- [ ] `VTB_SECRET_KEY` erzeugt und eingetragen
- [ ] `VTB_VAULT_KEY` erzeugt, Schlüssel sicher hinterlegt
- [ ] Datenbank-Zugang gesetzt, Stack gestartet, Schema laut Log angelegt
- [ ] Admin-Passwort geändert
- [ ] Vereins-Stammdaten gesetzt (App zeigt nicht mehr „Beispielverein")
- [ ] SMTP und `BASE_URL` gesetzt, Test-Login-Mail erfolgreich
- [ ] `VTB_COOKIE_SECURE=true` hinter TLS
- [ ] Backup eingerichtet: Datenbank **und** `uploads/`
- [ ] Optional: Push, TTLock, Matrix, Branding-Ordner
