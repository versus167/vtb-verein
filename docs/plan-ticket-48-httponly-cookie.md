# Plan – Ticket #48, Punkt 4: Server-Session per HttpOnly-Cookie statt Token im localStorage

> Status: **geplant** (Punkte 1–3 von #48 sind bereits umgesetzt: Token-Hash,
> atomares Single-Use, Rate-Limiting). Dieses Dokument beschreibt den noch
> offenen, größten Punkt. Umsetzung erfolgt im Branch `feat/magic-link-haertung`.

## 1. Ziel & Sicherheitsgewinn

Heute liegt das JWT (Access-Token) im `localStorage` und wird per
`Authorization: Bearer …` mitgeschickt. **Jeder XSS-Treffer kann das Token
auslesen** und die Session übernehmen.

Ziel: Das JWT wandert in ein **HttpOnly-Cookie** (für JS unlesbar). Der
Auth-Mechanismus selbst (HS256-JWT mit `sub`+`sid`, serverseitige Session über
`user_sessions`) bleibt – es ändert sich nur der **Transport** (Cookie statt
Header/localStorage) plus der nötige CSRF-Schutz.

## 2. Ausgangslage (Ist)

**Backend**
- `backend/core/deps.py`: `oauth2_scheme = OAuth2PasswordBearer(...)`; `get_current_user`
  und `get_current_session_id` lesen das Token aus dem `Authorization`-Header,
  `decode_token` → `sub`/`sid`; `sid` wird gegen `user_sessions` validiert (Revoke
  möglich, Ticket #24).
- `backend/core/security.py`: `create_access_token(user_id, expires_delta, session_id)`,
  `decode_token`.
- `backend/api/auth.py`: `/login` und `/magic-link/validate` geben `Token`
  (inkl. `access_token`) im **Body** zurück; `/logout` widerruft die Session per `sid`.
- `backend/main.py`: CORS mit `allow_credentials=True`, `FRONTEND_ORIGINS`; in Prod
  wird das gebaute SPA aus `frontend_dist` ausgeliefert (**same-origin**).

**Frontend**
- `frontend/src/stores/auth.js`: `token`/`user` aus `localStorage`;
  `isAuthenticated = !!token`; `_applyToken` setzt `api.defaults.headers.Authorization`.
- `frontend/src/boot/axios.js`: stellt Header aus `localStorage` wieder her;
  401-Interceptor → `logout()` + Redirect.
- `frontend/src/boot/auth.js`: Router-Guard (`requiresAuth`/`permission`) auf Basis
  `isAuthenticated`; beim Start `await auth.loadMe()`.
- `frontend/quasar.config.js`: **Dev-Proxy** `/api → http://localhost:8000`
  (→ Browser sieht alles unter `localhost:9000`, **same-origin**).

## 3. Warum das hier vergleichsweise risikoarm ist

Der Browser spricht in **beiden** Umgebungen mit **einem** Origin:
- **Prod**: Backend liefert SPA + `/api` unter derselben Domain.
- **Dev**: Quasar-Dev-Proxy leitet `/api` an `:8000` (Browser sieht nur `:9000`).

Damit genügt **`SameSite=Strict`** (kein `SameSite=None; Secure`, kein
Cross-Site-Cookie-Theater). CORS/`allow_credentials` bleiben nur als Fallback relevant.

## 4. CSRF-Strategie

Mit Cookies werden Credentials automatisch mitgeschickt → ohne Schutz wäre die App
CSRF-angreifbar. Schutz hier:

- **Primär: `SameSite=Strict`.** Bei *cross-site* initiierten Requests (von
  fremder Seite/Mail) sendet der Browser das Cookie **gar nicht** → klassischer
  CSRF läuft ins Leere. Direkte Navigation (Adressleiste/Bookmark) und same-origin
  XHR der eigenen SPA tragen das Cookie normal.
- **Magic-Link bleibt funktionsfähig:** Der Klick in der Mail ist eine top-level
  Navigation zu unserem Origin; das `validate`-POST kommt aus der SPA (same-origin)
  und *setzt* erst das Cookie. Auch Deep-Links funktionieren, weil das SPA nach dem
  Laden `/me` per same-origin-XHR aufruft (dann wird das Strict-Cookie gesendet).
- **Optional (Defense-in-Depth):** Double-Submit-CSRF-Token (zusätzliches,
  *nicht* HttpOnly Cookie `vtb_csrf` + Header `X-CSRF-Token`, serverseitig
  verglichen). Für den Start **nicht zwingend** dank Strict + same-origin; als
  Härtung dokumentiert, falls später ein Flow auf `Lax` gelockert werden muss.

## 5. Cookie-Attribute

| Attribut   | Wert                         | Begründung |
|------------|------------------------------|------------|
| Name       | `vtb_session`                | trägt das JWT |
| HttpOnly   | `true`                       | für JS unlesbar (Kernziel) |
| SameSite   | `Strict`                     | CSRF-Schutz (s. o.) |
| Secure     | `settings.COOKIE_SECURE`     | Prod `true` (HTTPS), Dev `false` (http) |
| Path       | `/`                          | für SPA-Navigation + `/api` |
| Max-Age    | = Token-Lebensdauer          | 24 h bzw. 30 Tage bei „remember“ |
| Domain     | *nicht gesetzt*              | host-only; dev-proxy-tauglich |

## 6. Änderungen – Backend

1. **`backend/core/config.py`**
   - `COOKIE_SECURE: bool = os.getenv("VTB_COOKIE_SECURE", "true").lower() == "true"`
   - (optional) `COOKIE_NAME`, `COOKIE_SAMESITE` als Konstante/Env.

2. **`backend/core/deps.py`** – Token aus Cookie statt Header lesen
   - `oauth2_scheme` ersetzen durch Auslesen von `request.cookies.get("vtb_session")`
     (FastAPI `Request` injizieren). Fehlt das Cookie → 401.
   - `get_current_user` und `get_current_session_id` auf die gemeinsame Quelle
     umstellen (am besten **eine** Hilfsfunktion, die einmal decodiert).
   - **Übergangsmodus** (optional, eine Version lang): zusätzlich `Authorization`-Header
     akzeptieren, damit offene Sessions nicht hart brechen. Danach Cookie-only.

3. **`backend/api/auth.py`** – Cookie setzen/löschen
   - `/login` und `/magic-link/validate`: `Response` injizieren und
     `response.set_cookie("vtb_session", token, max_age=…, httponly=True,
     secure=settings.COOKIE_SECURE, samesite="strict", path="/")`.
     `max_age` aus `expire` (remember → 30 Tage, sonst `ACCESS_TOKEN_EXPIRE_MINUTES`).
   - **`access_token` nicht mehr im Body zurückgeben** – Response-Model auf
     User-Infos (id/username/role/permissions) reduzieren (z. B. `Token` →
     `SessionUser`). So sieht JS das JWT nie.
   - `/logout`: zusätzlich `response.delete_cookie("vtb_session", path="/")`
     (Session-Revoke per `sid` bleibt).

4. **`backend/main.py`** *(nur falls Übergangsmodus entfällt)*: `OAuth2PasswordBearer`
   wird in Swagger obsolet. Optional ein `APIKeyCookie`-Security-Scheme für die
   OpenAPI-Doku ergänzen (Swagger „Try it out“ nutzt im selben Browser ohnehin das
   gesetzte Cookie). Kein funktionaler Zwang.

## 7. Änderungen – Frontend

1. **`frontend/src/boot/axios.js`**
   - `axios.create({ baseURL: '', withCredentials: true })` (Cookies senden).
   - Header-Wiederherstellung aus `localStorage` **entfernen**.
   - 401-Interceptor bleibt (Store leeren + Redirect login).

2. **`frontend/src/stores/auth.js`**
   - State: `token` raus; nur noch `user` (+ optional `ready`-Flag).
   - `isAuthenticated` = `!!user`.
   - `_applyToken(data)` → `_applyUser(data)`: nur `user` setzen
     (`localStorage('vtb_user')` als reiner UX-Cache, Server bleibt Quelle der Wahrheit),
     **kein** Authorization-Header, **kein** `vtb_token` mehr.
   - `logout()`: nur `user`/`vtb_user` leeren (Cookie löscht der Server bei `logoutServer`).
   - `vtb_token` aus `localStorage` defensiv entfernen (Altlasten-Cleanup).

3. **`frontend/src/boot/auth.js`**
   - Beim Start `await auth.loadMe()` (ruft `/me`, Cookie wird mitgeschickt):
     200 → `user` gesetzt, 401 → ausgeloggt. Guard erst danach „scharf“.
   - Guard/Logik unverändert (basiert auf `isAuthenticated`/`hasPermission`).

4. **`frontend/src/pages/MagicLinkPage.vue` / `LoginPage.vue`**
   - Unverändert in der UI; nur indirekt betroffen (Store setzt jetzt `user` statt `token`).

## 8. Config / Env (neu)

```
VTB_COOKIE_SECURE=true     # Prod (HTTPS). Lokal/Dev: false
```
- Docker/Prod-Env + `.env.example` ergänzen.
- `BASE_URL` (für Magic-Link-URL) bleibt unverändert.

## 9. Rollout / Transition

- Nach Deploy sind alte `localStorage`-Tokens wertlos (Backend liest Cookie):
  beim nächsten Request → 401 → Redirect Login → **einmaliges Neu-Einloggen**.
  Akzeptabel; im Release-Hinweis erwähnen.
- Mit optionalem Übergangsmodus (Header *und* Cookie akzeptieren) entfällt das
  Zwangs-Logout für eine Version.
- **Rollback**: rein Code (kein Schema). Revert des Commits genügt; gesetzte
  Cookies laufen ab bzw. werden beim nächsten Login-Flow überschrieben.

## 10. Edge Cases & Risiken

- **`SameSite=Strict` + Deep-Link aus Mail**: erste top-level Navigation ohne
  Cookie, aber SPA-`/me` (same-origin) holt es nach → ok.
- **Dev-Proxy & Cookies**: `changeOrigin: true` ist gesetzt; da **keine** `Domain`
  am Cookie steht (host-only), scoped der Browser auf `localhost:9000`. Verifizieren,
  dass `Set-Cookie` durch den Proxy unverändert ankommt (ggf. `cookieDomainRewrite`).
- **`Secure` in Dev**: muss `false` sein, sonst wird das Cookie über http verworfen.
- **Mehrere Tabs / Token-Ablauf**: 401-Interceptor greift global → konsistentes Logout.
- **Swagger-Authorize**: Bearer-UI verliert Funktion; via Browser-Cookie aber nutzbar.
- **`get_current_session_id`** muss dieselbe Cookie-Quelle nutzen (sonst Geräteliste/
  Logout-Markierung inkonsistent).

## 11. Test-Checkliste (manuell, im Container)

- [ ] Login (Passwort) → Cookie `vtb_session` gesetzt: `HttpOnly`, `SameSite=Strict`,
      `Secure` (Prod), korrektes `Max-Age`; **kein** `access_token` im Response-Body;
      `localStorage` enthält kein `vtb_token`.
- [ ] Reload (F5) → bleibt eingeloggt (Bootstrap `/me` via Cookie).
- [ ] „30 Tage eingeloggt bleiben“ → längeres `Max-Age`.
- [ ] Magic-Link end-to-end (anfordern → Mail → Klick → Einloggen) → Cookie gesetzt.
- [ ] Logout → Cookie gelöscht **und** Session in `user_sessions` widerrufen;
      Folge-Request → 401 → Login.
- [ ] „Andere Geräte abmelden“ (Ticket #24) wirkt weiterhin (sid-Validierung).
- [ ] JS-Konsole: `document.cookie` zeigt `vtb_session` **nicht** (HttpOnly).
- [ ] Cross-site-CSRF-Probe (POST von fremdem Origin) → kein Cookie → 401.
- [ ] Permission-Gating (Guard) unverändert; abgelaufenes Token → sauberer Logout.

## 12. Umsetzungsreihenfolge (Schritte)

1. Config: `VTB_COOKIE_SECURE` + Cookie-Konstanten.
2. Backend: `set_cookie`/`delete_cookie` in `/login`,`/magic-link/validate`,`/logout`;
   Response-Model ohne `access_token`.
3. Backend: `deps.py` auf Cookie-Quelle umstellen (optional Übergangsmodus).
4. Frontend: `axios.js` (`withCredentials`, Header raus), `stores/auth.js`
   (token raus, user-basiert), `boot/auth.js` (Bootstrap via `/me`).
5. `.env.example`/Docker-Env + Release-Hinweis (einmaliges Neu-Login).
6. Manuelle Test-Checkliste durchgehen (Container), dann Merge + VERSION-Bump.

---
_Kein DB-Schema betroffen → keine Migration. Reiner Transport-/Frontend-Umbau._
