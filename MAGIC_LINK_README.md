# Magic-Link-Authentifizierung - Setup & Testing

## Übersicht

Dieses Feature implementiert:
- **Password-Login** mit Remember-Me-Funktion
- **Magic-Link-Login** per E-Mail (7 Tage Gültigkeit)
- **Rollenbezogene Session-Timeouts**

## Setup

### 1. E-Mail-Konfiguration

Kopiere `.env.example` nach `.env` und konfiguriere SMTP:

```bash
cp .env.example .env
```

#### Option A: Gmail (einfach, kostenlos, 500 Mails/Tag)

1. Google-Account öffnen: https://myaccount.google.com/apppasswords
2. App-Passwort erstellen für "Mail"
3. In `.env` eintragen:

```env
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USE_TLS=true
SMTP_USERNAME=deine-gmail@gmail.com
SMTP_PASSWORD=abcd efgh ijkl mnop
MAIL_FROM=Vereinsverwaltung <deine-gmail@gmail.com>
BASE_URL=http://localhost:8080
```

#### Option B: Vereins-Mailprovider (Strato, 1&1, etc.)

```env
SMTP_SERVER=smtp.strato.de
SMTP_PORT=465
SMTP_USE_TLS=false
SMTP_USERNAME=vorstand@verein.de
SMTP_PASSWORD=dein-passwort
MAIL_FROM=VTB Verein <vorstand@verein.de>
BASE_URL=https://verein.vtb.de
```

### 2. Anwendung starten

```bash
git checkout feature/magic-link-authentication
python vtb_verein/main.py
```

Datenbank wird automatisch von Version 3 → 4 migriert.

## Testing

### 1. Password-Login mit Remember-Me

1. Navigiere zu http://localhost:8080/login
2. Tab "Passwort" wählen
3. Login: `admin` / `admin123`
4. Checkbox "Angemeldet bleiben" aktivieren
5. Anmelden klicken

**Erwartetes Verhalten:**
- Login erfolgreich
- Session bleibt 30 Tage aktiv (Admin-Role)
- Browser-Neustart: Immer noch eingeloggt

### 2. Magic-Link anfordern

1. Navigiere zu http://localhost:8080/login
2. Tab "Login-Link" wählen
3. E-Mail-Adresse eingeben: `admin@verein.local`
4. "Login-Link anfordern" klicken

**Erwartetes Verhalten:**
- Erfolgsmeldung: "Login-Link wurde an ... gesendet"
- E-Mail wird versendet (prüfe Posteingang)
- Konsole zeigt: "✅ E-Mail erfolgreich gesendet an ..."

### 3. Magic-Link verwenden

1. E-Mail öffnen
2. Button "Jetzt einloggen" klicken ODER Link kopieren
3. Seite `/auth/magic-link?token=...` wird geladen

**Erwartetes Verhalten:**
- Spinner während Validierung
- Erfolgsmeldung: "✅ Erfolgreich eingeloggt als admin"
- Automatische Weiterleitung nach 2 Sekunden
- Session mit Remember-Me aktiv (Magic-Link impliziert längere Session)

### 4. Token-Einmaligkeit testen

1. Verwende denselben Magic-Link nochmal

**Erwartetes Verhalten:**
- Fehlermeldung: "❌ Login fehlgeschlagen"
- Hinweis: "Der Link wurde bereits verwendet"
- Button "Neuen Link anfordern"

## Session-Timeouts

### Mit Remember-Me
- **Admin/User**: 30 Tage
- **Special** (Abteilungsleiter): 14 Tage
- **Readonly**: 7 Tage

### Ohne Remember-Me
- **Alle Rollen**: 24 Stunden

## Datenbank

### Neue Tabellen

```sql
-- Auth-Tokens
SELECT * FROM auth_tokens;
SELECT * FROM auth_tokens_history;
```

### Token-Cleanup (manuell)

```python
from app.db.datastore import VereinsDB

db = VereinsDB('vereinsdb.sqlite')
deleted = db.auth_token_repository.cleanup_expired_tokens()
print(f"Gelöscht: {deleted} abgelaufene Tokens")
```

## Troubleshooting

### E-Mail wird nicht gesendet

```python
# Test SMTP-Konfiguration
from app.config.email_config import EmailConfig
print(f"Configured: {EmailConfig.is_configured()}")
print(f"Server: {EmailConfig.get_smtp_server()}")
print(f"Username: {EmailConfig.get_smtp_username()}")
```

### Token-Validierung schlägt fehl

```python
# Prüfe Token-Status
from app.db.datastore import VereinsDB

db = VereinsDB('vereinsdb.sqlite')
with db.cursor() as cur:
    cur.execute("SELECT * FROM auth_tokens WHERE token LIKE ?" , ('abc%',))
    print(cur.fetchone())
```

### Migration schlägt fehl

```python
# Prüfe Schema-Version
from app.db.datastore import VereinsDB

db = VereinsDB('vereinsdb.sqlite')
with db.cursor() as cur:
    cur.execute("SELECT * FROM schema_version")
    print(cur.fetchone())
```

Erwartete Version: **4**

## Nächste Schritte

Nach erfolgreichem Test:
1. Merge Pull Request #26
2. Production-Deployment mit echten SMTP-Credentials
3. Optional: Cronjob für automatischen Token-Cleanup
4. Optional: Idle-Timeout-Logik implementieren
