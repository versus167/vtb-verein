# Club-Tresor — Vollständige Migrations- & Übergabe-Dokumentation

> Zweck dieses Dokuments: Die komplette Anwendung **Club-Tresor** (alle Funktionen, Ansichten, Datenbank, Auth, API, PWA/Push, Business-Logik) so vollständig beschreiben, dass sie in eine andere, größere Vereins-App integriert / dort neu aufgebaut werden kann — unabhängig vom Ziel-Stack. Es ist als Spezifikation für Menschen **und** für KI-Coding-Agenten gedacht.
>
> Quell-Repository (online): `https://github.com/okram0815/Clubtresor.git`
> Stand: rekonstruiert aus dem kompletten Quellcode (kein separates `.sql`-Schema vorhanden; DB-Schema hier aus allen SQL-Statements abgeleitet). Umfang: ~9.360 Zeilen PHP + JS/CSS.

---

## Inhaltsverzeichnis

1. [Was ist Club-Tresor?](#1-was-ist-club-tresor)
2. [Tech-Stack & Abhängigkeiten](#2-tech-stack--abhängigkeiten)
3. [Repository-Struktur](#3-repository-struktur)
4. [Request-Lifecycle, Routing & Bootstrap](#4-request-lifecycle-routing--bootstrap)
5. [Authentifizierung, Session & Mandantenfähigkeit](#5-authentifizierung-session--mandantenfähigkeit)
6. [Datenbank-Schema (vollständig rekonstruiert)](#6-datenbank-schema-vollständig-rekonstruiert)
7. [Domänen- & Geschäftslogik (Kern)](#7-domänen--geschäftslogik-kern)
8. [Klassen-Referenz (`classes/`)](#8-klassen-referenz-classes)
9. [Seiten-/View-Referenz (`pages/`)](#9-seiten--view-referenz-pages)
10. [API-Endpunkte (`public/api/`)](#10-api-endpunkte-publicapi)
11. [PWA & Web-Push](#11-pwa--web-push)
12. [Theming & Frontend](#12-theming--frontend)
13. [Konfiguration & Umgebungsvariablen](#13-konfiguration--umgebungsvariablen)
14. [Bekannte Probleme, toter Code & Sicherheits-Hinweise](#14-bekannte-probleme-toter-code--sicherheits-hinweise)
15. [Migrations-Checkliste & Empfehlungen](#15-migrations-checkliste--empfehlungen)

---

## 1. Was ist Club-Tresor?

Club-Tresor ist eine **deutschsprachige Vereins-/Mannschaftskassen-App** (Kassen-/„Deckel"-System) als installierbare **PWA** (Manifest, Service-Worker, Web-Push). Kernidee:

- Mitglieder loggen sich ein und **buchen Konsum-Artikel auf ihren „Deckel"** (z. B. Getränke).
- Ein **doppelter Buchungssatz-Ledger** (`club_transactions`) hält alle Geldbewegungen; jeder Saldo ergibt sich aus Summen über diese Tabelle.
- **Events** sind spezielle Artikel (Sammelaktionen), zu denen Mitglieder Beträge beisteuern.
- **Admins** (`roleIds == 1`) verwalten Mitglieder, Sortiment, Buchungen, Events, Startseite, Benachrichtigungen und sehen ein Zugriffs-Log.
- Push-Benachrichtigungen informieren Admins über Buchungen/Event-Beiträge und alle Mitglieder über neue Events.

Die App ist **mandantenfähig** (mehrere „Clubs" pro Instanz, getrennt über `clubId` / `clubHash` / Domain), wird aber praktisch mit einem Haupt-Club (`clubId = 1`) betrieben.

---

## 2. Tech-Stack & Abhängigkeiten

| Bereich | Technologie |
|---|---|
| Sprache | **PHP 8.0+** (nutzt `match`, Union-Return-Types, Named Args, `??=`) |
| Framework | **Keins** — eigener Front-Controller + eigener Autoloader |
| Datenbank | **MySQL/MariaDB** über **`mysqli`** (prepared statements), Charset `utf8mb4`, Engine InnoDB |
| Auth | **Eigene Session-basierte Auth** (PHP-Sessions) |
| Frontend | **Bootstrap 5.3** + **Bootstrap Icons** (vendored), Vanilla JS (eine eigene Datei `app.js`), keine Build-Pipeline |
| PWA | Manifest + Service-Worker + **hand-implementiertes Web-Push** (VAPID / RFC 8291/8292/8188) |
| Composer-Deps | **nur** `vlucas/phpdotenv ^5.6` (+ dessen Transitive: `graham-campbell/result-type`, `phpoption/phpoption`, `symfony/polyfill-ctype|mbstring|php80`) |
| PHP-Extensions | `mysqli`, `openssl` (braucht `openssl_pkey_derive`, PHP ≥ 7.3), `curl`, `json`, `mbstring`/`ctype` (polyfilled) |
| Webserver | Apache mit `mod_rewrite` (siehe `.htaccess`) |
| Deployment | SFTP (`.vscode/sftp.json` vorhanden, nicht eingecheckt), Sessions in projekt-eigenem `sessions/`-Ordner |

**Keine** Node-Abhängigkeiten für die Laufzeit (JS ist statisch vendored). **Keine** Test-Suite, **keine** Migrations, **kein** ORM.

---

## 3. Repository-Struktur

```
Clubtresor/
├── .htaccess (in public/)         # Rewrite: alles → index.php?param=…
├── .env                           # DB-Credentials (nicht eingecheckt)
├── autoload.php                   # Custom-Autoloader für Namespace Clubtresor\
├── composer.json / composer.lock  # nur phpdotenv
│
├── app/                           # Prozeduraler Bootstrap-Layer
│   ├── sessionboot.php            # Session-Konfiguration (MUSS zuerst laufen)
│   ├── session.php                # Logout-Handling
│   ├── db.php                     # prozedurales $db (mysqli)
│   ├── log.php                    # Zugriffslog → club_log
│   └── helper.php                 # globale (nicht-namespaced) class helper (Formatierung)
│
├── classes/                       # OO-Businesslogik, Namespace Clubtresor\
│   ├── Db.php                     # mysqli-Wrapper + _query()
│   ├── Helper.php                 # Clubtresor\Helper (Währung, Kurzname, Datum)
│   ├── Item.php                   # Artikel, Artikelgruppen, Events (Gruppe 8)
│   ├── Member.php                 # Einzel-Mitglied (⚠ defekt, siehe §14)
│   ├── Members.php                # Mitglieder-Liste + Rollen
│   ├── Transaction.php            # Ledger: Salden, Buchungen, Historie
│   └── Push.php                   # Web-Push (VAPID, Verschlüsselung, Abos)
│
├── pages/                         # Views + teilweise Controller-Logik
│   ├── segments/                  # header, footer, navbar, pushAuto (Shared Shell)
│   ├── login.php / loginClub.php  # Login-Screens (ausgeloggt)
│   ├── start.php                  # Home „Deckel" (Default-Route)
│   ├── member.php / members.php   # Profil (self) / Mitglieder-Admin
│   ├── history.php / histories.php# eigene Historie / Club-Historie + Storno
│   ├── transaction.php            # Admin: manuelle Zahlungen
│   ├── event.php / events.php     # Event beitragen / Event-Verwaltung
│   ├── consumptions.php           # Admin: Artikel×Mitglied-Buchungsmatrix
│   ├── clubtable.php / tester.php # „Liga-Tabelle" nach Saldo
│   ├── settings.php               # Sortiment-Verwaltung (Gruppen/Artikel)
│   ├── startpage.php              # Startseiten-Inhalte konfigurieren
│   ├── notifications.php          # Push-Konsole
│   ├── log.php                    # Zugriffslog-Viewer
│   └── admin.php                  # ⚠ toter Legacy-Partial
│
└── public/                        # Web-Root (DocumentRoot)
    ├── index.php                  # Front-Controller / Router
    ├── .htaccess                  # Rewrite-Regeln
    ├── api/                       # JSON/Form-Endpunkte (siehe §10)
    │   ├── login.php, item.php, transaction.php, histories.php,
    │   ├── memberUpdate.php, membersUpdate.php, push.php,
    │   ├── startpageUpdate.php, startpageDeleteImage.php, db.php
    │   ├── cron.php (leer) und cron/<md5("1")>/cron.php (echter Cron)
    ├── app/session.php            # ⚠ Debug-Dump von $_SESSION (entfernen!)
    ├── restore-events.php         # ⚠ Admin-Wartungstool (entfernen!)
    ├── manifest.json, service-worker.js, maintenance.html
    ├── css/ (bootstrap + theme.css), js/ (bootstrap + app.js), images/, favicon.ico
```

**Wichtig:** DocumentRoot ist `public/`. Alles außerhalb (`app/`, `classes/`, `pages/`, `.env`, `sessions/`) liegt bewusst **oberhalb** des Web-Roots und wird nur per `require` eingebunden.

### `.htaccess` (Routing-Grundlage)

```apache
RewriteEngine On
RewriteBase /
RewriteCond %{REQUEST_FILENAME} !-f
RewriteRule ^(.*)$ /index.php?param=$1 [L,QSA]
```

Jede Anfrage, die keine existierende Datei ist, wird auf `index.php?param=<pfad>` umgeschrieben. Bei der Migration muss diese Rewrite-Semantik (oder ein äquivalentes Routing) erhalten bleiben.

---

## 4. Request-Lifecycle, Routing & Bootstrap

### Einstiegspunkt `public/index.php` — Boot-Reihenfolge

1. `require app/sessionboot.php` — Session **zuerst** starten.
2. Maintenance-Gate (Wartungsmodus + Dev-Bypass, s. u.).
3. `$param = explode('/', $_GET['param'])` — `$param[0]` = Seite, `$param[1]` = optionales Segment (Tenant-Hash beim Login).
4. `require autoload.php` — Custom-Autoloader `Clubtresor\`.
5. `require vendor/autoload.php` — Composer (dotenv).
6. `.env` laden (immutable), Pflichtfelder `DB_HOST, DB_NAME, DB_USER, DB_PASS`.
7. `require app/session.php` — Logout-Handling.
8. `require app/log.php` — schreibt eine Zugriffslog-Zeile (`club_log`).
9. `require app/helper.php` — globale `class helper` (Formatierung).
10. Auth-Verzweigung (eingeloggt vs. nicht) → Routing.

### `app/sessionboot.php` — kanonische Session-Konfiguration

```php
if (session_status() === PHP_SESSION_NONE) {
    $lifetime = 3600 * 24 * 90;                 // 90 Tage
    ini_set('session.gc_maxlifetime', $lifetime);
    $path = __DIR__ . '/../sessions';           // eigener Ordner außerhalb webroot
    if (!is_dir($path)) { @mkdir($path, 0700, true); }
    if (is_dir($path) && is_writable($path)) { session_save_path($path); }
    session_set_cookie_params($lifetime, '/');  // 90-Tage-Cookie, path=/
    session_start();
}
```

- **Cookie:** Lebensdauer 90 Tage, Path `/`. **Keine** expliziten `secure`/`httponly`/`samesite`/`domain`-Flags → PHP-Defaults (Härtungsbedarf bei Migration).
- **Session-Dateien** liegen in projekt-eigenem `sessions/` (überlebt Hoster-Cleanup), Fallback auf Default-Pfad.

### `autoload.php` — Custom-Autoloader

```php
spl_autoload_register(function ($class_name) {
    $class_name = str_replace('\\', '/', $class_name);
    $class_name = str_replace('Clubtresor/', '', $class_name);
    if (file_exists(__DIR__."/classes/$class_name.php")) {
        include __DIR__ . "/classes/$class_name.php";
    }
});
```

Mappt `Clubtresor\Foo` → `classes/Foo.php`. PHP-Klassennamen sind case-insensitive → `new DB()` löst `Clubtresor\Db` auf (im Cron genutzt).

### Route-Tabelle (eingeloggter Zweig, `switch($param[0])`)

| `param[0]` | Datei | Zweck |
|---|---|---|
| `member` / `members` | `pages/member.php` / `members.php` | eigenes Profil / Mitglieder-Admin |
| `history` / `histories` | `pages/history.php` / `histories.php` | eigene Historie / Club-Historie + Storno |
| `transaction` | `pages/transaction.php` | Admin: manuelle Zahlungen |
| `tester` | `pages/tester.php` | Dev-Preview (nur `memberId == 10002`) |
| `event` / `events` | `pages/event.php` / `events.php` | Event beitragen / Event-Admin |
| `consumptions` | `pages/consumptions.php` | Admin: Buchungsmatrix |
| `clubtable` | `pages/clubtable.php` | Liga-Tabelle nach Saldo |
| `settings` | `pages/settings.php` | Sortiment-Verwaltung |
| `notifications` | `pages/notifications.php` | Push-Konsole |
| `log` | `pages/log.php` | Zugriffslog |
| `startpage` | `pages/startpage.php` | Startseiten-Editor |
| *(sonst / leer)* | `pages/start.php` | Home „Deckel" (`$activePage='home'`) |
| `logout` | (in `app/session.php`) | Session zerstören → `/` |

> `pages/{$param[0]}.php` wird direkt interpoliert, ist aber durch die `case`-Whitelist abgesichert. Beim Refactoring diese Absicherung beibehalten.

### Login-Redirect-Logik

- Nicht eingeloggt & Seite ≠ `login` → Slug in `$_SESSION['requestedPage']` merken, `Location: /login`.
- Nach erfolgreichem Login → gespeicherte Seite (`requestedPage`) erneut anspringen.

### Wartungsmodus & Dev-Bypass (oben in `index.php`)

```php
$maintenance = false;                         // hart aus
if (isset($_SESSION['dev'])) { /* volle Fehleranzeige */ }
if ($maintenance && $_SESSION['dev'] !== true) {
    if ($_GET['dev'] != '924e0bc62ecd30fe04e018c829c2303d') {
        include 'maintenance.html'; exit(1);
    } else { $_SESSION['dev'] = true; }        // Magic-Query schaltet Dev frei
}
```

- Wartung standardmäßig **aus**. Bypass über `?dev=924e0bc62ecd30fe04e018c829c2303d` (persistiert in Session, aktiviert volle Fehleranzeige).

---

## 5. Authentifizierung, Session & Mandantenfähigkeit

### Login-Flow (`public/api/login.php`)

- **Methode:** POST (form-encoded). **Kein Auth nötig**, setzt Session.
- **Eingaben:** `member` (memberId, aus dem Login-Modal) **oder** `user` (Telefonnummer), plus `pin`.
- **Kern-Logik:**
  ```php
  if ($member) { WHERE memberId = ? AND active = 1 }
  elseif ($user) { WHERE phone = ? AND active = 1 }
  // Passwortprüfung:
  if ($pass == date('dmy', strtotime($row['birthday']))) { … erfolg … }
  ```
- **⚠ „PIN" = Geburtstag im Format `DDMMYY`** (`date('dmy')`). Die `password_verify($pass, $row['pin'])`-Zeile ist auskommentiert; die echte `pin`-Spalte wird **nicht** für Auth genutzt. Das ist ein schwaches, im Klartext ableitbares Auth-Schema — bei der Migration nahezu sicher zu ersetzen.
- **Bei Erfolg:**
  ```php
  $_SESSION['loggedin']     = true;
  $_SESSION['justLoggedIn'] = true;
  $_SESSION['member']       = $row;   // KOMPLETTE club_members-Zeile in der Session
  ```

### Session-Keys

| Key | Gesetzt in | Bedeutung |
|---|---|---|
| `loggedin` | login.php | `true` nach Login |
| `justLoggedIn` | login.php | One-Shot-Flag für Post-Login-UX (Event-Modal) |
| `member` | login.php | volle `club_members`-Zeile (memberId, clubId, roleIds, …) |
| `requestedPage` | index.php | Deep-Link, der nach Login angesprungen wird |
| `dev` | index.php | Dev-Bypass + volle Fehleranzeige |
| `eventModalSeen` | start.php | welche Event-Erinnerungen schon gezeigt wurden |

**Rollen-Modell:** `$_SESSION['member']['roleIds'] == 1` ⇒ **Admin**. `roleIds` ist ein **komma-separierter String** von Rollen-IDs (z. B. `"1"` oder `"1,2"`). Achtung Inkonsistenz: teils als Skalar `== 1` behandelt (Item, Push, Transaction, die meisten Pages), teils als CSV per `explode`/`FIND_IN_SET` (Member, log.php). Admin-Gate ist praktisch überall „roleIds gleich exakt 1".

### Logout (`app/session.php`)

Route `/logout` → `session_destroy()` + `unset($_SESSION)` + `Location: /`.

### Mandantenfähigkeit (Multi-Tenant)

Beim ausgeloggten Request wird der Club aufgelöst, um den passenden Login-Screen zu wählen:

```php
if (strlen($param[1]) === 64 || $_SERVER['SERVER_NAME'] !== 'clubtresor.jakaric.de') {
    SELECT M.memberId, M.lastName, M.firstName
    FROM club C JOIN club_members M USING(clubId)
    WHERE (C.clubHash = ? OR JSON_UNQUOTE(JSON_EXTRACT(C.params, '$.domain')) = ?)
      AND M.active = 1
    ORDER BY M.firstName, M.lastName;
    // bind: $param[1] (64-Zeichen-Hash), $_SERVER['SERVER_NAME']
}
```

Tenant-Auflösung über **entweder**:
- einen **64-Zeichen-`clubHash`** im URL-Segment (`/login/<64-hex>`), **oder**
- **Domain-Matching**: `club.params.$.domain` == `$_SERVER['SERVER_NAME']`.

Werden Mitglieder gefunden → `loginClub.php` (Mitglieder-Kachel-Auswahl). Sonst → `login.php` (Telefon + PIN). Alle laufenden Requests sind über `$_SESSION['member']['clubId']` einem Club zugeordnet.

> **⚠ Migrations-Achtung:** Einige Queries (z. B. Saldo-UNIONs in `Transaction`, `getEventMembers`) filtern **nicht** konsequent nach `clubId`. Vor echtem Mehr-Mandanten-Betrieb auf Cross-Tenant-Leaks prüfen.

---

## 6. Datenbank-Schema (vollständig rekonstruiert)

> Es existiert **kein** `.sql`-File. Das folgende Schema ist aus allen SQL-Statements im Code abgeleitet. Charset überall `utf8mb4`, Engine InnoDB. Nur `club_push_subscriptions` hat ein wörtliches `CREATE TABLE` im Code (in `Push.php`) — alle anderen sind Best-Effort-Rekonstruktionen; unsichere Typen sind kommentiert.

### ER-Übersicht (Live-Schema)

```
club (clubId) 1───∞ club_members
club (clubId) 1───∞ club_itemGroup
club (clubId) 1───∞ club_transactions
club (clubId) 1───∞ club_log                       [logisch]
club (clubId) 1───∞ club_push_subscriptions        [logisch]

club_itemGroup (itemGroupId) 1───∞ club_items
club_itemGroup.groupDebit ──▶ club_members.memberId   (Fallback-Debit-Konto)
club_items.debit          ──▶ club_members.memberId   (Item-spezifisches Debit-Konto)

club_transactions.credit     ──▶ club_members.memberId  (Zahler; NULL = Club)
club_transactions.debit      ──▶ club_members.memberId  (Empfänger; NULL = Club)
club_transactions.created_by ──▶ club_members.memberId
club_transactions.deleted_by ──▶ club_members.memberId
club_transactions.params.item.itemId ⇢ club_items.itemId  (Soft-Ref via JSON)

club_members.roleIds ⇢ club_roles.roleId   (CSV-Soft-Ref, KEIN echter FK)
club_members.memberId ◀── club_log.memberId
club_members.memberId ◀── club_push_subscriptions.memberId
```

### 6.1 `club` — Mandant

```sql
CREATE TABLE club (
  clubId    INT UNSIGNED NOT NULL AUTO_INCREMENT,
  name      VARCHAR(255) NOT NULL,
  clubHash  CHAR(64) DEFAULT NULL,   -- SHA-256-hex Login-/Cron-Token (mit 64-Zeichen-String verglichen)
  params    JSON DEFAULT NULL,       -- {domain, startNoItems{type,text,image}, startHasItems{...}}
  PRIMARY KEY (clubId),
  UNIQUE KEY uniq_clubHash (clubHash)  -- Eindeutigkeit angenommen
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

`params.domain` steuert Domain-basiertes Tenant-Matching; `params.startNoItems` / `startHasItems` steuern die Startseiten-Infoboxen.

### 6.2 `club_members` — Mitglied **und** Ledger-Konto

```sql
CREATE TABLE club_members (
  memberId      INT UNSIGNED NOT NULL AUTO_INCREMENT,
  clubId        INT UNSIGNED NOT NULL,
  roleIds       VARCHAR(64) DEFAULT NULL,       -- CSV von Rollen-IDs, Admin = enthält 1
  pin           INT DEFAULT NULL,               -- Typ unsicher; als int gebunden. Aktuell NICHT für Auth genutzt
  playerNumber  INT DEFAULT NULL,
  lastName      VARCHAR(100) DEFAULT NULL,
  firstName     VARCHAR(100) NOT NULL,
  nickName      VARCHAR(100) DEFAULT NULL,
  birthday      DATE DEFAULT NULL,              -- ist zugleich das Login-Passwort (Format dmy)
  phone         VARCHAR(40) DEFAULT NULL,       -- alternativer Login-Identifier
  mail          VARCHAR(190) DEFAULT NULL,
  active        TINYINT(1) NOT NULL DEFAULT 1,  -- soft-active
  membershipFee TINYINT(1) NOT NULL DEFAULT 0,  -- zahlungspflichtig / Event-Berechtigung
  params        JSON DEFAULT NULL,              -- {pushPrefs:{booking,event,newevent}}
  created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  deleted_at    DATETIME DEFAULT NULL,          -- soft-delete
  PRIMARY KEY (memberId),
  KEY idx_club (clubId),
  KEY idx_phone (phone)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

Wichtige Rollen dieser Tabelle: dient zusätzlich als **Konto** im Ledger (`credit`/`debit`/`created_by`/`deleted_by`/`groupDebit`/`item.debit` referenzieren `memberId`). `membershipFee = 1` steuert sowohl die Beitrags-Cron als auch die Event-Berechtigung. Anzeigename bevorzugt: `COALESCE(NULLIF(nickName,''), firstName)`.

### 6.3 `club_roles`

```sql
CREATE TABLE club_roles (
  roleId INT UNSIGNED NOT NULL AUTO_INCREMENT,
  name   VARCHAR(100) NOT NULL,
  PRIMARY KEY (roleId)
  -- roleId ist KEIN normales FK-Ziel: club_members.roleIds ist eine CSV dieser IDs.
  -- Seed vermutet: (1, 'Admin')
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 6.4 `club_itemGroup` — Artikelgruppe

```sql
CREATE TABLE club_itemGroup (
  itemGroupId INT UNSIGNED NOT NULL AUTO_INCREMENT,
  clubId      INT UNSIGNED NOT NULL,
  groupName   VARCHAR(150) NOT NULL,
  groupDebit  INT UNSIGNED DEFAULT NULL,   -- FK → club_members.memberId (Fallback-Debit-Konto)
  dutyDebit   INT NOT NULL DEFAULT 0,      -- steuert „fester Debit" (siehe settings.php)
  active      TINYINT(1) NOT NULL DEFAULT 1,
  deleted_at  DATETIME DEFAULT NULL,
  PRIMARY KEY (itemGroupId),
  KEY idx_club (clubId)
  -- itemGroupId = 8 ist die reservierte „Events"-Gruppe pro Club (Magic-Konstante!)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

> **Mixed-Case-Tabellenname `club_itemGroup`** wird wörtlich verwendet — auf case-sensitivem Linux-MySQL (`lower_case_table_names=0`) exakt so anlegen.

### 6.5 `club_items` — Artikel **oder** Event (Gruppe 8)

```sql
CREATE TABLE club_items (
  itemId      INT UNSIGNED NOT NULL AUTO_INCREMENT,
  itemGroupId INT UNSIGNED NOT NULL,
  debit       INT UNSIGNED DEFAULT NULL,     -- FK → club_members.memberId (Item-Debit-Override)
  `name`      VARCHAR(150) NOT NULL,         -- backtick-quoted im Code
  amount      DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  active      TINYINT(1) NOT NULL DEFAULT 1,
  valid_from  DATE DEFAULT NULL,
  valid_to    DATE DEFAULT NULL,             -- Event-Datum/Deadline bei Gruppe 8
  params      JSON DEFAULT NULL,             -- {exclude_members:[memberId,...]}
  deleted_at  DATETIME DEFAULT NULL,
  PRIMARY KEY (itemId),
  KEY idx_group (itemGroupId)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

Gültigkeits-Fenster: `NOW() BETWEEN IFNULL(valid_from,'1000-01-01') AND IFNULL(valid_to,'9999-12-31')`. `params.exclude_members` (int-Array) schließt Mitglieder aus (Sichtbarkeit + Event-Nenner).

### 6.6 `club_transactions` — **Kern-Ledger (doppelte Buchführung)**

```sql
CREATE TABLE club_transactions (
  transactionId  INT UNSIGNED NOT NULL AUTO_INCREMENT,
  clubId         INT UNSIGNED NOT NULL,
  credit         INT UNSIGNED DEFAULT NULL,  -- FK → club_members.memberId (Zahler/belasteter Deckel; NULL = Club)
  debit          INT UNSIGNED DEFAULT NULL,  -- FK → club_members.memberId (Empfänger; NULL = Club)
  amount         DECIMAL(10,2) NOT NULL,     -- positiv; Vorzeichen wird in Queries angewandt
  params         JSON DEFAULT NULL,          -- {item:{itemId,itemName}} | {transactionType,note}
  transaction_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,  -- effektives (rückdatierbares) Buchungsdatum
  created_by     INT UNSIGNED DEFAULT NULL,  -- FK → club_members.memberId (Akteur)
  created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, -- Audit-Insert-Zeit (12h/7d-Undo-Fenster)
  deleted_by     INT UNSIGNED DEFAULT NULL,  -- FK → club_members.memberId
  deleted_at     DATETIME DEFAULT NULL,      -- soft-delete (jede Saldo-Query filtert IS NULL)
  PRIMARY KEY (transactionId),
  KEY idx_club (clubId), KEY idx_credit (credit), KEY idx_debit (debit),
  KEY idx_txat (transaction_at), KEY idx_deleted (deleted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

`params`-Varianten:
- Artikelbuchung: `{"item":{"itemId":..,"itemName":".."}}`
- Manuelle Zahlung: `{"transactionType":"cash|paypal|bank|sale","note":".."}`
- Beitrags-Cron: `{"transactionType":"membership","note":"Mannschaftsbeitrag YYYY/MM"}`

**Unterschied `created_at` vs. `transaction_at`:** `created_at` = Audit-Zeit (treibt die 12h/7d-Undo-Fenster), `transaction_at` = effektives/rückdatierbares Buchungsdatum (treibt 24h/180d-Reporting).

### 6.7 `club_log` — Zugriffslog

```sql
CREATE TABLE club_log (
  logId      INT UNSIGNED NOT NULL AUTO_INCREMENT,
  memberId   INT UNSIGNED DEFAULT NULL,   -- NULL für Gäste
  clubId     INT UNSIGNED DEFAULT NULL,
  sessionId  VARCHAR(128) DEFAULT NULL,
  ip         VARCHAR(45)  DEFAULT NULL,
  path       TEXT,                         -- json_encode($param)
  params     TEXT,                         -- json_encode($_REQUEST)
  user_agent TEXT,                         -- json_encode(UA-String)
  log_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (logId),
  KEY idx_club (clubId), KEY idx_member (memberId), KEY idx_logat (log_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 6.8 `club_push_subscriptions` — **exakte DDL aus `Push.php`**

```sql
CREATE TABLE IF NOT EXISTS club_push_subscriptions (
  subscriptionId INT AUTO_INCREMENT PRIMARY KEY,
  clubId         INT NOT NULL,               -- FK → club.clubId (logisch)
  memberId       INT NOT NULL,               -- FK → club_members.memberId (logisch)
  endpoint       TEXT NOT NULL,
  endpoint_hash  CHAR(64) NOT NULL,          -- sha256(endpoint); Dedupe-Key
  p256dh         VARCHAR(255) NOT NULL,      -- Subscriber Public Key (b64url)
  auth           VARCHAR(255) NOT NULL,      -- Subscriber Auth Secret (b64url)
  userAgent      VARCHAR(255) DEFAULT NULL,
  created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uniq_endpoint (endpoint_hash),
  KEY idx_member (memberId)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

Upsert über `endpoint_hash`. Kategorie-Präferenzen liegen **nicht** hier, sondern in `club_members.params.pushPrefs`.

### 6.9 Legacy-Tabellen (NICHT migrieren, nur auskommentierter Code)

`club_cashiers`, `club_cashItems`, `club_cashTransactions_v2` erscheinen **ausschließlich** in einem großen auskommentierten Block in `public/api/db.php` — ein älteres Kassen-Ledger-Design, das die aktuelle App **nicht** nutzt (ersetzt durch `club_transactions`). Der im ursprünglichen Auftrag genannte View `club_cashtransactions_v` existiert **nirgends** im Code (weder `CREATE VIEW` noch Referenz); `_v2` ist eine physische Tabelle, keine View. **Empfehlung:** Kassen-Tabellen/-View **nicht** übernehmen, außer die Kassen-Funktion soll wiederbelebt werden.

### Modellierungs-Cautions

1. **`roleIds` ist ein CSV-String, kein Integer-FK.** Normalisierung zu einer Join-Tabelle muss die Kommaliste parsen; Admin = Wert `1` enthalten.
2. **`credit`/`debit`/`created_by`/`deleted_by`/`groupDebit`/`item.debit` sind alle FKs auf `club_members.memberId` und **nullable** (NULL = Club/Haus-Konto).** Keine `NOT NULL`-FKs anlegen.
3. **JSON-Spalten:** `club.params`, `club_members.params`, `club_items.params`, `club_transactions.params` (per `JSON_EXTRACT`/`JSON_CONTAINS`/`JSON_OBJECT`).
4. **Soft-Delete überall:** `deleted_at` auf members/itemGroup/items/transactions; `active` auf members/itemGroup/items. Listen- und Saldo-Queries filtern durchgängig `deleted_at IS NULL` / `active = 1`.
5. **Magic-Konstanten:** `itemGroupId = 8` (Events), `memberId = 10002` (in `getEventSum` & `tester.php` hartcodiert).

---

## 7. Domänen- & Geschäftslogik (Kern)

### 7.1 Ledger-Vorzeichen-Konvention (kritisch, nicht-offensichtlich)

Salden werden durch UNION zweier Sichten je Transaktion berechnet:

```sql
SELECT clubId, debit  AS account, SUM(amount)    AS balance ... GROUP BY account  -- Debit-Seite: +amount
UNION
SELECT clubId, credit AS account, SUM(amount*-1) AS balance ... GROUP BY account  -- Credit-Seite: -amount
```

Für ein Konto gilt: **als `debit` → +amount; als `credit` → −amount.** Ein Mitglied, das einen Artikel „kauft", ist der **`credit`** (Saldo wird negativer); das empfangende Konto ist der `debit`. Das ist **invers zur umgangssprachlichen Benennung**.

> **⚠ Bewusste Inversion (durch Nutzer bestätigt):** Die Farb-/Icon-Zuordnung auf der Historien-Seite ist absichtlich invers zur Standard-Buchhaltungsbenennung. `.tx-amount.credit` → grün/success, `.tx-amount.debit` → rot/danger. Anzeige-Beträge werden als `amount * -1` gezeigt. **Diese exakte visuelle Zuordnung bei der Migration erhalten.**

### 7.2 Artikelkauf (Self-Service & Admin)

- **Debit-Auflösung:** `IF(item.debit, item.debit, group.groupDebit)` — Item-Debit überschreibt Gruppen-Debit; NULL = Club.
- Preis kommt **immer aus der DB** (`club_items.amount`); der Client kann keinen Preis setzen.
- Buchung setzt `credit = konsumierendes Mitglied`, `debit = aufgelöstes Debit-Konto`, `params.item = {itemId, itemName}`.
- **Storno = Soft-Delete** (`deleted_at`/`deleted_by`), niemals Hard-Delete.
- **Undo-Fenster:** Mitglied darf **eigene** Buchung nur binnen **12 h** stornieren; Admin binnen **7 Tagen** (für beliebiges Mitglied).

### 7.3 Events (Artikelgruppe 8)

- Events sind `club_items` in der reservierten Gruppe `itemGroupId = 8`.
- Berechtigt sind aktive Mitglieder mit `membershipFee = 1`, die nicht in `params.exclude_members` stehen.
- Beteiligung: Fortschritt = `bezahlteMitglieder / berechtigteMitglieder`; Statistikfenster für Listen/Summen `180 DAY`.
- Beim Beitrag: `addItemTransactionByMember` bucht wie ein Artikelkauf; danach Push an Admins (Kategorie `event`). Neues Event → Push an alle (`newevent`).
- **⚠ Magic:** `getEventSum()` zählt „userEvents" über hartcodiertes `credit = 10002` (statt Session-memberId) — Semantik vor Migration verifizieren.

### 7.4 Beitrags-Cron (Mitgliedsbeitrag)

Der echte Cron (`public/api/cron/<md5("1")>/cron.php`) bucht bei `?action=membershipFee` einen **2,50 €** „Mannschaftsbeitrag YYYY/MM" als `credit`-Transaktion für jedes aktive `membershipFee=1`-Mitglied des per `clubHash` bestimmten Clubs. **Keine** Session/Rollen-Prüfung — nur der md5-Ordner + `clubHash` als Obscurity-Gate. Von externem Scheduler aufzurufen.

### 7.5 Zeitfenster & Magic Values (Sammlung)

| Wert | Bedeutung |
|---|---|
| `roleIds == 1` | Admin |
| `itemGroupId = 8` | Events-Gruppe |
| `memberId = 10002` | hartcodiertes Konto (getEventSum) / Zugang (tester.php) |
| `12 HOUR` | Mitglied-Storno-Fenster (eigene Artikelbuchung) |
| `7 DAY` | Admin-Storno-Fenster (Artikelbuchung) |
| `24 HOUR` | „24h Deckel"-Reporting |
| `180 DAY` | Event-Statistik-Fenster |
| `2.50` | Mitgliedsbeitrag pro Cron-Lauf |

---

## 8. Klassen-Referenz (`classes/`)

Alle im Namespace `Clubtresor`. Persistenz über eine einzige MySQLi-Verbindung (`Db`); die meisten Klassen `extend Db` und nutzen `_query()`. Identität/Mandant kommen fast überall aus `$_SESSION['member']` (`clubId`, `memberId`, `roleIds`).

### 8.1 `Db` — Verbindung + Query-Helper

- `public mysqli $conn` (öffentlich, teils direkt genutzt).
- `__construct()` lädt `.env`, prüft die 4 DB-Vars, öffnet `mysqli`, setzt `utf8mb4`. Bei Connect-Fehler: `die(json {success:false, message:'Datenbankverbindung fehlgeschlagen'})`.
- `_query(string $query, $params = false)` — **Return-Vertrag (wichtig):**
  - SELECT **mit** Zeilen → `array` von Assoc-Rows.
  - Non-SELECT (INSERT/UPDATE/DELETE) → `mysqli_stmt`.
  - SELECT mit **0 Zeilen** → `false` (nicht `[]`!).
  - Bind-Typen via `gettype`: int/bool→`i`, double→`d`, sonst→`s`.
  - `bind_param`-Exception wird **still verschluckt** (unbenutztes `$error`).
- **⚠** Jede instanziierte Subklasse öffnet eine **eigene** DB-Verbindung.

### 8.2 `Helper` (namespaced) — Formatierung

- `currencyEuro($float, $colored=false)` → `"1.234,56€"`, optional in `text-success`/`text-danger` (0 gilt als grün).
- `dateTimeLocal(int|string)` → `Y-m-d H:i` (für `datetime-local`).
- `shortName($firstName,$lastName)` → `"Max M."`; Fallback-String `'Club'`, wenn Namen fehlen (System-/Club-Konto).

> Achtung: Es gibt **zwei** Helper — die namespaced `Clubtresor\Helper` (hier) und eine globale `class helper` in `app/helper.php` (`currencyEuro`, `format_euro`, `getPlaceholders` mit `{{type@key}}`-Templating, `comma2dot`, `sqlDate`, `diffForHumans` = deutsche Relativzeit). API-Seiten nutzen die namespaced Variante.

### 8.3 `Item` — Artikel, Gruppen, Events

Admin-Gate: `checkPermission()` = `roleIds == 1`. Zentrale Methoden:

- `getItems()` — buchbare Artikel des Mitglieds (aktiv, im Gültigkeitsfenster, nicht in `exclude_members`, **ohne Gruppe 8**). Debit-Auflösung `IF(debit, debit, groupDebit)`.
- `getItemsByGroup($id)` / `getItemGroups()` — Admin-Listen inkl. inaktiv/gelöscht.
- `getEventItems()` — Events (Gruppe 8) mit Aggregaten `payedMembers`, `eventMembers`, `userTransactionAt/Amount` (180d-Fenster).
- `getEventSum()` — eine Zeile: `events` vs. `userEvents` (⚠ `credit = 10002` hartcodiert).
- `getEventMembers($itemId)` / `getEventParticipationStats()` — Teilnahme-Details/Statistik. (In `getEventParticipationStats` zählt auch `exclude_members` als „beteiligt/verbucht".)
- `getEventsByAdmin()` / `saveEventByAdmin($itemId,$params)` / `addEventByAdmin($params)` — Event-CRUD (Gruppe-8-Guard, `exclude_members` als int-Array normalisiert, Komma-Dezimal `str_replace(',', '.')`).
- `updateItemGroup(...)` / `addItemGroup(...)` / `updateItem(...)` / `addItem(...)` / `softDeleteItem($id)` — Sortiment-CRUD (Soft-Delete). **⚠ `addItem` prüft die Gruppen-Zugehörigkeit zum Club nicht** (Cross-Tenant-Insert-Risiko).

### 8.4 `Member` — Einzel-Mitglied ⚠ DEFEKT

Ruft im Konstruktor `$db->_querySelect(...)` auf — **diese Methode existiert auf `Db` nicht** (nur `_query`). Die Klasse wirft daher `Error: Call to undefined method`. **Effektiv toter/defekter Code**; bei Migration reparieren oder entfernen. Behandelt `roleIds` als CSV (`explode`), `shortName` ohne abschließenden Punkt (abweichend von `Helper`).

### 8.5 `Members` — Mitglieder-Liste + Rollen

- `getMembers($filter=false)` — Mitglieder des Clubs; `$filter['active']===true` beschränkt auf aktive. Liefert u. a. `pin`, `playerNumber` (sensibel!). Sortierung `COALESCE(NULLIF(nickName,''), firstName), lastName`.
- `getRoles()` — `SELECT roleId, name FROM club_roles` (global, ohne clubId-Scope), robust mit try/catch → `[]`.

### 8.6 `Push` — Web-Push (siehe auch §11)

Dependency-freie Implementierung (RFC 8291/8292/8188), braucht nur `openssl` + `curl`. Kategorien-Enum `CATEGORIES = ['booking','event','newevent']`. Kernmethoden: `saveSubscription`, `deleteSubscription`, `hasSubscription`, `getPrefs`/`setPrefs` (schreiben `club_members.params.pushPrefs`), `notifyAdmins`/`notifyAll`/`notifySelf`/`notifyHash`, `getSubscribedMemberIds`, `generateVapidKeys` (einmalige Key-Erzeugung), `createTable`. Präferenz-Modell ist **Opt-out** (unbekannt = erlaubt). 404/410 vom Push-Service → Abo automatisch prunen.

### 8.7 `Transaction` — Ledger

Kernmethoden (Vorzeichen-Konvention siehe §7.1):

- **Salden:** `getBalanceByClub`, `getBalanceByMember`, `getBalanceMemberByClub` (Rangliste, **ohne Admins**, `active=1`, `balance DESC`), `getBalancePeriodByMember($hours)`, `getItemAmountPeriodByMember/ByClub`.
- **Buchen:** `addTransactionByMember`, `addItemTransactionByMember($itemId)` (Self-Service-Kauf), `addItemTransactionByAdmin($itemId,$credit)` (für anderes Mitglied), `addTransactionByAdmin(...)` (freie Buchung, **explizites Admin-Gate** `roleIds != 1 → false`, rückdatierbar).
- **Storno (Soft-Delete):** `deleteItemTransactionByMember` (12h, nur eigene), `deleteItemTransactionByAdmin` (7d), `deleteTransactionById` (Admin: alles im Club; sonst nur `credit=self`), `removeDeleteTransactionById` (Un-Storno, gleiche Rechte).
- **Detail/Historie:** `getTransactionById` (mit Namen aller 4 Personenreferenzen), `getHistoryByMember` (UNION ALL mit Vorzeichen-Flip aus Sicht des Mitglieds), `getHistoryByClub` (club-weit; die gespiegelte UNION-Hälfte ist auskommentiert → jede Transaktion erscheint einmal).

> **⚠ Inkonsistentes Admin-Gating:** `addTransactionByAdmin`/`deleteTransactionById` prüfen `roleIds` in der Methode; `addItemTransactionByAdmin`/`deleteItemTransactionByAdmin` prüfen **nur** Session-Präsenz und verlassen sich auf Route-Level-Auth.

---

## 9. Seiten-/View-Referenz (`pages/`)

Jede Seite ist View **und** teilweise Controller. Gemeinsame Shell: `segments/header.php` (öffnet HTML, Theme-Bootstrap, lädt Bootstrap+`theme.css?v=8`+Manifest), `segments/footer.php` (lädt `app.js`, Bootstrap-JS, `pushAuto.php`), `segments/navbar.php` (fixierte Bottom-Tab-Bar), `segments/pushAuto.php` (stilles Push-Abo).

**Navbar:** Für alle: **Deckel** (`/`), **Historie** (`/history`), **`{firstName}`** (`/member`). Admins: zusätzlich Admin-Grid-Popup zu `consumptions, log, events, members, histories, transaction, startpage, notifications, settings` + Theme-Toggle. Nicht-Admins: Theme-Toggle-Tab.

### Seiten-Beziehungs-Übersicht

| Bereich | Mitglieder-View | Admin-View | Schreibt über |
|---|---|---|---|
| Deckel / Buchungen | `start.php` (Home) | `consumptions.php` (Matrix) | `/api/item.php` |
| Ledger/Historie | `history.php` (eigene) | `histories.php` (alle + Storno) | `/api/histories.php` |
| Manuelle Zahlungen | — | `transaction.php` | `/api/transaction.php` |
| Rangliste | `clubtable.php` | (`tester.php`, dev-only) | read-only |
| Events | `event.php` (beitragen) | `events.php` (verwalten) | `/api/item.php`, Event-Forms |
| Personen | `member.php` (self) | `members.php` (alle) | `/api/memberUpdate.php`, `/api/membersUpdate.php` |
| Sortiment | (in start/consumptions gerendert) | `settings.php` | POST self, `Item`-Klasse |
| Startseiten-Inhalt | (von `start.php` konsumiert) | `startpage.php` | `/api/startpageUpdate.php`, `…DeleteImage.php` |
| Push | (auto via `pushAuto.php`) | `notifications.php` | `/api/push.php` |
| Audit | — | `log.php` | read-only |
| Auth | `login.php` / `loginClub.php` | — | `/api/login.php` |

### 9.1 Login-Screens (`login.php`, `loginClub.php`)

Eigenständige HTML-Dokumente (nur ausgeloggt). `login.php`: Telefon (`user`) + PIN (`[0-9]{4,6}`). `loginClub.php`: Live-Suchfeld + **Kachel-Grid** der Mitglieder (Avatar aus Initialen, `av-0..7` nach Index); Tap öffnet Modal mit vorbelegtem `memberId`, PIN-Feld `[0-9]{6}` „Geburtstag als PIN (TTMMJJ)". Beide POSTen an `/api/login.php`.

### 9.2 Home „Deckel" — `start.php` (Default-Route)

Persönlicher Deckel. Lädt `Item::getItems()`, `getEventSum()`, `getEventItems()`, Salden, sowie `club.params.startNoItems/startHasItems`. Zeigt: konfigurierbare Infobox (default/text/image), Event-CTA-Banner bei offenen Events, große **Artikel-Buttons** (links buchen mit Live-Tally der letzten 24h + „with ❤ by {payer}"-Badge bei festem `debit`; rechts löschen), **Saldo-Leiste** („24h Deckel" + „Gesamtsaldo"), Beteiligungs-Zeile, **Zahlungs-Sektion** (WERO-Deeplink, IBAN-Copy, PayPal.me — ⚠ **hartcodierte** Zahlungsempfänger-Daten), Event-Erinnerungs-Modal (einmal pro offener Sammlung, Reset bei `justLoggedIn`, Tracking via `eventModalSeen`). Buchen/Löschen über `/api/item.php`; Mitglied-Löschfenster 12h.

### 9.3 Eigene Historie — `history.php`

Lädt `getHistoryByMember()` + `getBalanceByMember()`. Transaktionen nach **Tages-Trennern** mit laufendem Tages-Saldo. Jede Karte: Richtungs-Punkt (grün `+` / rot `−`), Typ-Icon (`cash/paypal/bank/sale/membership`), Klartext-Zeile per `match($txType)`, Notiz/Artikelname, vorzeichenbehafteter Betrag & Zeit. Stornierte Zeilen durchgestrichen/blass. **Read-only.** (⚠ Farb-/Icon-Inversion, siehe §7.1.)

### 9.4 Admin-Buchungen — `transaction.php` & `histories.php`

**`transaction.php` („Zahlungen", Admin):** Club-Zeile mit Club-Saldo, Mitglieder-Filter, pro Mitglied eine Karte (Avatar, Name, Saldo) mit 4 Aktions-Buttons (An-/Verkauf, cash, paypal, bank). Modals: Richtung (bezahlt an / erhält von bzw. kauft von / verkauft an), Gegenkonto (Club oder Mitglied), Betrag, Datum, Notiz. POST an `/api/transaction.php` → `addTransactionByAdmin` → Live-Saldo-Update (`applyBalances`).

**`histories.php` („Historien", Admin):** club-weite Historie (`getHistoryByClub`) + Storno-Tool. Suche + Mitglieder-Select (mit `__club__`-Sentinel für NULL). Tages-Gruppierung, klickbare Partei-Chips (setzen Filter), Deep-Link `?member={id}` (aus Push). Karte-Klick → **Storno-Modal** (`getTransaction` lädt Detail-HTML; Button toggelt „Storno" ↔ „Storno entfernen"). Rechte: Admin storniert alles im Club, Nicht-Admin nur Eigenes.

### 9.5 Rangliste — `clubtable.php` & `tester.php`

**`clubtable.php` („Club-Tabelle", alle):** `getBalanceMemberByClub()` + Club-Saldo. Mitglieder in **5 Liga-Stufen** nach Saldo: Champions League (≥20), Oberes Mittelfeld (5–20), Gesichertes Mittelfeld (0–5), Abstiegszone (−20–0), Finanzielle Relegation (<−20). Read-only.

**`tester.php` („Beitragsliga"):** gleiche Idee, aber nur `memberId == 10002` (sonst „Access denied"). Dev/Preview — bei Migration entfernbar oder in `clubtable` falten.

### 9.6 Events — `event.php` & `events.php`

**`event.php` (Mitglied):** POST `submitEventPayment` → `addItemTransactionByMember($itemId)` (PRG-Redirect), danach Push an Admins („… hat … zu „{event}" beigetragen 🙏", `event`). Zeigt Gradient-Event-Karten (amber→rot bzw. grün wenn erledigt), optionales Hintergrundbild, Deadline (`diffForHumans`), **Fortschrittsbalken**, Statistik-Zeile und **„{amount} beitragen 💪"**-Button bzw. „✅ Du bist dabei"-Badge.

**`events.php` (Admin):** POST-Formen `event[itemId][…]` → `saveEventByAdmin` (Update), `newEvent[…]` → `addEventByAdmin` (Insert Gruppe 8; bei aktiv → Push „Neues Event 🎉" an alle). „Neues Event anlegen"-Accordion (Name, valid_from/to, Betrag, aktiv, Overlay-Farbe, Bild, Text, **exclude-members**-Checkliste). Teilnahme-Statistik-Accordion. Pro-Event-Accordions mit „Teilnehmer verwalten" (Mitglied klicken → Confirm-Modal → `/api/item.php {itemId,memberId,itemAction}` Admin-Add/Remove) + inline Edit-Form.

### 9.7 Mitglieder — `member.php` (self) & `members.php` (Admin)

**`member.php`:** eigenes Profil (Nachname, Vorname, Spitzname, Geburtstag, Mobil, E-Mail). Save-Button erscheint nur bei Änderung (JS-Diff). Logout-Link. POST `/api/memberUpdate.php`.

**`members.php` (Admin):** klappbare Aktiv-/Inaktiv-Sektionen, pro Mitglied Karte (Avatar admin=rot/inaktiv=grau, Rollen-Chips, Status-Icons Push/Beitrag/Aktiv, Edit-Stift mit `data-*`). FAB **+** öffnet Create-Modal. Edit/Create-Modal: Namen, Geburtstag, Telefon, Mail, Spielernummer, **Rollen-Switches** (pro `club_roles`-Zeile, `roleIds` als Komma-Join, leer = NULL), Mitgliedsbeitrag & Aktiv. POST `/api/membersUpdate.php` (`editMember`/`createMember`). Pflicht: firstName + birthday.

### 9.8 Sortiment — `settings.php` („🍺 Sortiment", Admin)

CRUD für Gruppen & Artikel. POST-Aktionen: `newItemGroup`, `newItem`/`_addArticle`, `deleteItem` (Soft-Delete), `editGroup` (inkl. `groupDebit`, `dutyDebit`), Bulk-Updates. Zeigt pro Gruppe einen dunklen Header (Aktiv-Switch, Name, Gruppen-Debit-Select wenn `dutyDebit != 1`, Edit, +) über weißer Artikelliste (Aktiv, Name, Preis, Item-Debit-Select wenn `dutyDebit == 1`, Löschen). **⚠ „Fester Debit"-Inversion:** Switch **an** ⇒ `dutyDebit = 0` (Gruppe steuert Debit), **aus** ⇒ `dutyDebit = 1` (Item wählt selbst). Diese Inversion erhalten. Debit `NULL` = Club. Löschen ist soft (Historie bleibt).

### 9.9 Buchungsmatrix — `consumptions.php` (Admin)

Artikel×Mitglied-Gitter. Period-Filter (`consumption_from/to` in Session, `reset_period` → rollende 24h). Rows = Mitglieder, Columns = Artikel; Header-Zeile 2 = Club-Summen je Artikel. Jede Zelle = grüner Count-Button (`add`) + roter `−` (`delete`). Sticky-Header per JS. Aktionen über `/api/item.php` (admin-scoped, `addItemTransactionByAdmin`/`deleteItemTransactionByAdmin`, 7-Tage-Löschfenster).

### 9.10 Startseiten-Editor — `startpage.php` (Admin)

Konfiguriert die Infoboxen von `start.php`. Zwei Config-Karten („Wenn nichts zu buchen ist" / „Wenn etwas zu buchen ist"), je Typ-Radio (default/text/image), Textarea, **Bild-Bibliothek** (`public/images/startpage/`) mit Upload/Preview/Löschen/Lightbox. Multipart-POST `/api/startpageUpdate.php` (persistiert in `club.params`), Löschen `/api/startpageDeleteImage.php`.

### 9.11 Push-Konsole — `notifications.php` (Admin)

4 Karten: Master-Toggle „Push auf diesem Gerät", **Präferenz-Switches** (booking/event/newevent), „Test senden", Typed-Test (Typ + Ziel-Gerät). Alles client-seitig gegen `/api/push.php` (`subscribe`/`unsubscribe`/`devices`/`test`/`testType`/`getPrefs`/`setPrefs`). `VAPID_PUBLIC_KEY` aus Env injiziert.

### 9.12 Zugriffslog — `log.php` (Admin)

Inline-Query (nicht via Klasse): bis 200 Zeilen aus `club_log` LEFT JOIN `club_members`, gefiltert nach `clubId` + optional `?member`, `?date`, „Admin ausblenden" (`hide_admin`, default an, per `FIND_IN_SET`). Filter-Bar + Tabelle (Relativ-/Absolutzeit, Mitglied-Chip/„Gast", dekodierter Path, vereinfachter UA, Info-Bottom-Sheet mit vollen Details).

### 9.13 Toter Legacy-Partial — `admin.php`

Erwartet Globals `$cashItems`/`$members` aus altem `club_cashItems`-Schema (auskommentiert). Nicht über Router erreichbar. **Bei Migration verwerfen** (historischer Ursprung von `consumptions.php`).

---

## 10. API-Endpunkte (`public/api/`)

Muster: `Content-Type: application/json` → `sessionboot.php` → Auth-Guard → Arbeit → `echo json_encode(...)`. Guards antworten `403 Forbidden` oder `{success:false}`. Antworten sind `{success: bool, …}`.

| Endpunkt | Methode / Body | Auth | Zweck & Kern |
|---|---|---|---|
| `login.php` | POST form | keine (setzt Session) | Login (PIN = Geburtstag `dmy`), schreibt Session + `club_log` |
| `item.php` | POST JSON `{itemId, itemAction:add\|delete, memberId?}` | eingeloggt (memberId nur wenn Admin) | Artikel buchen/stornieren; Member 12h / Admin 7d; danach Push an Admins außer Akteur (`booking`, URL `/histories?member=…`). Antwort Member: `{amount, itemsTotal, saldoTotal}`, Admin: `{amount, clubAmount}` |
| `transaction.php` | POST JSON | **Admin** (403 sonst) | `getTransaction` (rendert Modal-HTML), `deleteTransaction`, `removeDeleteTransaction` |
| `membersUpdate.php` | POST JSON | **Admin** | `editMember` (UPDATE, `roleIds=NULLIF(?, '')`), `createMember` (INSERT, gibt `memberId`), Legacy-Einzelfeld-Updates |
| `memberUpdate.php` | POST form | eingeloggt (eigenes Mitglied) | Self-Profil-Update (`club_members` where memberId=own) |
| `push.php` | POST JSON `{action,…}` | eingeloggt | `subscribe/unsubscribe/status/test/devices/testType/getPrefs/setPrefs` (siehe §11) |
| `startpageUpdate.php` | POST multipart | **Admin** (sonst Redirect `/`) | Startseiten-Config in `club.params`, Bild-Upload (MIME-geprüft) → `public/images/startpage/img_<clubId>_<time>.<ext>`; Redirect `/startpage?saved=1` |
| `startpageDeleteImage.php` | POST JSON `{file}` | **Admin** | `basename()`-sanitized `unlink()` |
| `histories.php` | — | — | **Stub/leer** (nur auskommentiertes TODO). Historie rendert `pages/history.php` |
| `db.php` (api) | Include | — | Shared Preloader: lädt `$club`, `$member`, `$members`; enthält großen auskommentierten Legacy-`cashItems`-Block |
| `cron.php` | — | — | **leer** (TODO) |
| `cron/<md5("1")>/cron.php` | GET `?clubHash=…&action=membershipFee` | **keine** (nur Ordner-Obscurity + clubHash) | bucht 2,50 € Mannschaftsbeitrag je `membershipFee=1`-Mitglied |
| `restore-events.php` (in public/) | GET/POST | **Admin** | ⚠ Wartungstool (restore/purge/reconstruct Events + Buchungen) — **entfernen für Produktion** |

---

## 11. PWA & Web-Push

### 11.1 PWA-Setup

**`manifest.json`:**
```json
{ "name":"Club-Tresor", "short_name":"Club-Tresor", "start_url":"/index.html",
  "display":"standalone", "background_color":"#ffffff", "theme_color":"#007bff",
  "icons":[ {"src":"/images/icon-192x192.png","sizes":"192x192","type":"image/png"},
            {"src":"/images/icon-512x512.png","sizes":"512x512","type":"image/png"} ] }
```
> ⚠ `start_url:/index.html` existiert physisch nicht — hängt am Rewrite auf `index.php`. `theme_color:#007bff` ist veraltet (echte Nav-Farbe `#1a1a2e`); es gibt **kein** `<meta name="theme-color">`. Keine `apple-touch-icon`/maskable-Icons. Bei Migration korrigieren.

**Service-Worker (`service-worker.js`):** `CACHE_NAME='pwa-login-cache-v1.9.15'` (manuelles Cache-Busting). Precache: Bootstrap CSS/JS, Icon-Fonts, `app.js`, `favicon.ico`, PWA-Icons. **Cache-first, network-fallback**; kein Runtime-Caching, keine Offline-Fallback-Seite. `theme.css` ist **nicht** precached (offline ungestylt). Auf `controllerchange` einmaliger Reload.

**SW-Push-Handler:** `push` liest `event.data.json()` → zeigt Notification (Icon `/images/icon-192x192.png`, Badge `/images/badge-96x96.png`, `vibrate:[80,40,80]`, `data.url` default `/history`). `notificationclick` navigiert ein bestehendes Fenster zu `data.url` (Fallback neues Fenster).

### 11.2 Web-Push (hand-implementiert, keine Library)

**Env:** `VAPID_PUBLIC_KEY` (b64url 65-Byte P-256-Punkt, auch an Client), `VAPID_PRIVATE_KEY` (base64 PEM, signiert ES256-JWT), `VAPID_SUBJECT` (JWT `sub`, default `mailto:admin@example.com`). Einmalige Erzeugung via `Push::generateVapidKeys()`.

**Abo-Flow:** zwei Client-Einstiege, beide POST `/api/push.php`:
- **Stilles Auto-Abo** (`segments/pushAuto.php`, auf jeder eingeloggten Seite, nur wenn `VAPID_PUBLIC_KEY` gesetzt): SW ready → falls kein Abo & Permission `default` → nativer Prompt → `pushManager.subscribe({userVisibleOnly:true, applicationServerKey})` → POST `{action:'subscribe', subscription: sub.toJSON()}`.
- **Explizit** (`notifications.php`, Admin): Toggle subscribe/unsubscribe + Geräte-Picker + Tests.

`sub.toJSON()` = `{endpoint, keys:{p256dh, auth}}`. Server: `saveSubscription($endpoint,$p256dh,$auth,$ua)`, Identität aus Session. Abo-ID = `sha256(endpoint)` (unique je Gerät).

**Server-Send (`Push::send()`):** RFC 8291 aes128gcm — ephemere AS-Keypair je Nachricht, ECDH (`openssl_pkey_derive`), HKDF-SHA256 (ikm/cek/nonce), AES-128-GCM, RFC-8188-Body (`salt|rs|idlen|asPublic|cipher|tag`). VAPID-JWT ES256 (DER→raw Signatur). Curl-POST mit Headern `Content-Encoding: aes128gcm`, `TTL:86400`, `Urgency:normal`, `Authorization: vapid t=<jwt>,k=<VAPID_PUBLIC_KEY>`. HTTP **404/410** → Abo prunen.

**Payload-Vertrag:** `{ "title":"…", "body":"…", "data":{ "url":"/histories?member=42", "tag":"booking" } }`.

**Server-Trigger:** `api/item.php` → `notifyAdmins` (`booking`), `event.php` → `notifyAdmins` (`event`), `events.php` → `notifyAll` (`newevent`), `push.php` → `notifySelf`/`notifyHash` (Tests). Kategorie-Präferenzen (`booking/event/newevent`) in `club_members.params.pushPrefs`, Opt-out-Modell.

**Assets:** `icon-192x192.png` (Notification-Icon), `badge-96x96.png` (Android-Badge), `icon-512x512.png` (Splash).

---

## 12. Theming & Frontend

**Dark/Light** über `data-theme`-Attribut auf `<html>`, persistiert in `localStorage['ct-theme']`. FOUC-Bootstrap-Inline-Script im `<head>` (Reihenfolge: stored → OS `prefers-color-scheme` → light). Toggle in `navbar.php` (`#themeToggle`), sofort ohne Reload.

**CSS-Custom-Properties** (`theme.css`, `--ct-*`): u. a. `--ct-bg-page/surface/nav`, `--ct-text/-muted`, `--ct-border`, `--ct-accent (#5b9bd5/#6ab0e8)`, `--ct-success`, `--ct-danger`. Dark-Block setzt zusätzlich `color-scheme: dark`. Der Großteil der Datei sind `[data-theme="dark"]`-Overrides über vendored Bootstrap, stark mit `!important`.

> ⚠ Bewusste Inversion (bestätigt): `.tx-amount.credit` → success/grün, `.tx-amount.debit` → danger/rot.

**Cache-Busting** ist manuell und uneinheitlich: `theme.css?v=8` (App) vs. `?v=7` (Login), `app.js?6679` (Footer) vs. ohne (Login), SW `v1.9.15`. Bei Migration vereinheitlichen (idealerweise Content-Hashing).

**Client-JS (`public/js/app.js`, einzige eigene JS-Datei):** SW-Registrierung; Clipboard/GiroCode-Helper; `numberToTally`, `formatEuro` (`Intl.NumberFormat de-DE/EUR`); `applyBalances({club, members:{id:balance}})` (Live-Saldo-Update). Fetch-Verdrahtung für Login, Member-Update, Item-Buttons (`/api/item.php`), Transaktions-Forms (`/api/transaction.php`), Historie-Modal (`/api/histories.php`). Alles Vanilla, feature-gated per Element-ID. Rest von `public/js/` ist vendored Bootstrap 5.3.

---

## 13. Konfiguration & Umgebungsvariablen

**Aktuell in `.env` (Werte redigiert):** `DB_HOST`, `DB_USER`, `DB_PASS`, `DB_NAME` — alle **Pflicht** (`Dotenv->required`), App bricht sonst ab.

**Im Code referenziert, aber in `.env` FEHLEND** (Push daher aktuell effektiv deaktiviert, bis gesetzt):
- `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT`.

**Composer:** nur `vlucas/phpdotenv v5.6.1` (+ Transitive `graham-campbell/result-type`, `phpoption/phpoption`, `symfony/polyfill-ctype|mbstring|php80`). Keine Dev-Deps.

**Extern:** Browser-Push-Services (FCM/Mozilla/WNS) via HTTPS/cURL aus `Push::send()`; externer Scheduler für die Cron-URL. **DocumentRoot = `public/`.** Apache `mod_rewrite` erforderlich.

**`.gitignore`:** `vendor/`, `node_modules/`, `.env`, `.vscode/`, `.claude/settings.local.json`, `public/images/startpage`.

---

## 14. Bekannte Probleme, toter Code & Sicherheits-Hinweise

**Sicherheit / Auth:**
- **PIN = Geburtstag (`DDMMYY`), Klartext-Vergleich.** Trivial ableitbar. `password_verify` + echte `pin`-Spalte sind auskommentiert. → In der Ziel-App durch echte Auth ersetzen.
- **Session-Cookie** ohne `secure`/`httponly`/`samesite`. → härten.
- **Cron-Endpunkt unauthentifiziert** außer md5("1")-Ordner + `clubHash` (Obscurity). → echte Auth/Secret.
- **`club.params`/Sortiment-Endpunkte** teils ohne konsequenten `clubId`-Guard (z. B. `Item::addItem`, Saldo-UNIONs, `getEventMembers`) → **Cross-Tenant-Risiko** bei echtem Multi-Tenant.
- **`.env`** enthält Live-DB-Credentials (nicht committen).

**Toter / temporärer Code (in Produktion entfernen):**
- `public/app/session.php` — `var_dump($_SESSION)` (Debug-Dump).
- `public/restore-events.php` — Admin-Wartungstool („nach Gebrauch löschen").
- `public/api/cron.php` und `public/api/histories.php` — leere Stubs.
- `pages/admin.php` — toter Legacy-Partial.
- Legacy-Cash-Klasse/-Tabellen (`cashItems`, `club_cashiers`, `club_cashItems`, `club_cashTransactions_v2`) — nur auskommentiert.
- `classes/Member.php` — **defekt** (`_querySelect` existiert nicht) → reparieren oder entfernen.
- `pages/tester.php` — Dev-Preview (nur `10002`).

**Konsistenz-Fallen:**
- `roleIds` doppelt behandelt (Skalar `== 1` vs. CSV `explode`/`FIND_IN_SET`).
- `_query`-Return-Polymorphie (array / `false` / `mysqli_stmt`) — jede Call-Site berücksichtigt das.
- Zwei `Helper` (global `helper` vs. `Clubtresor\Helper`).
- Jede `Db`-Subklasse öffnet eigene DB-Verbindung; `bind_param`-Fehler still verschluckt.
- Hartcodierte Zahlungsempfänger (WERO/IBAN/PayPal) in `start.php`.

**Bewusste, zu erhaltende „Merkwürdigkeiten":**
- Ledger-Vorzeichen + Historien-Farb-/Icon-Inversion (§7.1).
- „Fester Debit"-Inversion in `settings.php` (§9.8).
- `itemGroupId = 8` (Events), `memberId = 10002`.

---

## 15. Migrations-Checkliste & Empfehlungen

Unabhängig vom Ziel-Stack lässt sich die Integration in 6 Blöcke gliedern. Reihenfolge = empfohlene Umsetzung.

### A. Datenmodell in die zentrale DB überführen
- [ ] Tabellen 1–8 aus §6 anlegen (Namen ggf. mit einheitlichem Präfix statt `club_*`, falls die Ziel-App schon Präfixe nutzt). Mixed-Case (`club_itemGroup`) beachten.
- [ ] Falls die Ziel-App bereits „Mitglieder"/„Vereine" kennt: `club` ↔ Verein und `club_members` ↔ Personen **mappen statt duplizieren**. `club_members.memberId` wird von sehr vielen Spalten referenziert (credit/debit/created_by/…) — ein sauberes ID-Mapping ist der kritischste Schritt.
- [ ] `roleIds` (CSV) in das Rollen-/Rechte-System der Ziel-App überführen; Admin = enthält `1`.
- [ ] JSON-Spalten (`params`) übernehmen oder in echte Spalten/Relationen auflösen (`pushPrefs`, `exclude_members`, `domain`, Startseiten-Config, `item`/`transactionType`/`note`).
- [ ] Daten-Dump aus der Live-DB ziehen (nur Tabellen 1–8), Legacy-Cash-Tabellen weglassen.

### B. Kern-Businesslogik portieren (verlustfrei!)
- [ ] Ledger-Salden **exakt** wie §7.1 (debit `+amount`, credit `−amount`, `deleted_at IS NULL`).
- [ ] Artikelkauf/Storno inkl. Debit-Auflösung `IF(item.debit, groupDebit)` und Undo-Fenster 12h/7d.
- [ ] Event-Logik (Gruppe 8, `membershipFee=1`-Berechtigung, `exclude_members`, 180d-Fenster).
- [ ] Beitrags-Cron (2,50 €) als geplanten Job der Ziel-App.
- [ ] Magic-Werte parametrisieren (`10002`, Gruppe 8, Beitragshöhe, Zeitfenster) statt hartcodieren.

### C. Views neu bauen (Design-System der Ziel-App)
- [ ] Seiten aus §9 auf die UI-Konventionen der Ziel-App übertragen. Prioritär: **start (Deckel)**, **history/histories**, **transaction**, **consumptions**, **events/event**, **members**, **settings**. `clubtable`/`tester`/`admin` optional.
- [ ] Historien-Farb-/Icon-Inversion und „Fester Debit"-Inversion **bewusst** reproduzieren.

### D. Auth & Session an die Ziel-App andocken
- [ ] Login der Ziel-App verwenden; **PIN=Geburtstag ersetzen**. Falls Bestands-Logins migriert werden: Zwangs-Passwort-Reset.
- [ ] Rollen/Rechte auf das Modell der Ziel-App abbilden. Cross-Tenant-Guards überall ergänzen.

### E. PWA & Push
- [ ] Entweder `classes/Push.php` weitgehend übernehmen (nur `openssl`+`curl`, 3 VAPID-Env-Vars) **oder** eine Library nutzen — dann Payload-Vertrag `{title, body, data:{url, tag}}` und SW-Handler kompatibel halten.
- [ ] `club_push_subscriptions` + `pushPrefs` migrieren. Manifest/Icons/`theme-color`/`start_url` korrigieren. Cache-Busting vereinheitlichen.

### F. Aufräumen / Härten
- [ ] Toten/Debug-Code (§14) **nicht** mitnehmen.
- [ ] Session-Cookie härten, Cron authentifizieren, Secrets aus der Ziel-App-Config beziehen (nicht `.env` committen).

### Konkrete Transfer-Optionen „von hier ins neue Projekt"
1. **Dieses Dokument** ist der Kern der Übergabe — es beschreibt alles Nötige stack-unabhängig.
2. **Repo bleibt Referenz:** `https://github.com/okram0815/Clubtresor.git` — für exakte SQL-Formulierungen (Ledger, Historie) und die Push-Krypto den Originalcode zitieren.
3. **Daten:** separaten `mysqldump` der Live-Tabellen 1–8 anfertigen (enthält Credentials/PII → sicher übertragen, nicht ins Repo).
4. **Empfohlene Reihenfolge im Zielprojekt:** A → B → D → C → E → F.

---

*Ende der Migrations-Dokumentation. Bei Detailfragen zu einzelnen Methoden/Queries: jeweilige Datei im Repo öffnen — dieses Dokument nennt überall die Fundstellen (Klasse/Seite/Endpoint).*
