#!/usr/bin/env python3
"""
Proof-of-Concept für die TTLock-Cloud-Anbindung (Zutrittskontrolle / Schließsystem).

Read-only-Wegwerf-Skript: KEIN DB-Zugriff, KEINE schreibenden Schloss-Operationen.
Es verifiziert nur die drei Risiken aus ZUTRITTSKONTROLLE_PLAN.md (Phase 1):

  1. OAuth2-Login + Request-Signatur funktionieren gegen den EU-Endpoint.
  2. Inventar (Schlösser/Gateways) ist abrufbar.
  3. Zutrittslogs (lockRecord/list) und IC-Cards (identityCard/list) sind abrufbar.

Zugangsdaten kommen aus .env (siehe .env.example, Abschnitt TTLock):
  TTLOCK_CLIENT_ID, TTLOCK_CLIENT_SECRET, TTLOCK_USERNAME, TTLOCK_PASSWORD
  TTLOCK_ENDPOINT (optional, default EU)

Beispiele:
  ./venv/bin/python tools/ttlock_poc.py                 # Login + Inventar + 30 Tage Logs
  ./venv/bin/python tools/ttlock_poc.py --days 7        # nur 7 Tage Logs
  ./venv/bin/python tools/ttlock_poc.py --lock-id 12345 # nur ein Schloss
  ./venv/bin/python tools/ttlock_poc.py --raw           # Roh-JSON statt Tabellen
"""
import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, '.env'))
except Exception:
    pass

DEFAULT_ENDPOINT = 'https://euapi.ttlock.com'  # API-Host (euopen.* ist nur das Dev-Portal)

# recordType → lesbare Öffnungs-/Verriegelungsmethode.
# Vollständig aus der TTLock-Doc (euopen.ttlock.com/doc/api/v3/lockRecord/list, 2026-06).
RECORD_TYPES = {
    1: 'App',
    2: 'Parklücke berührt',
    3: 'Gateway (remote)',
    4: 'Passcode',
    5: 'Parksperre hoch',
    6: 'Parksperre runter',
    7: 'IC-Karte',
    8: 'Fingerprint',
    9: 'Armband',
    10: 'mech. Schlüssel',
    11: 'Bluetooth-Verriegeln',
    12: 'Gateway (remote)',
    29: 'Unerwartet entriegelt',
    30: 'Türmagnet zu',
    31: 'Türmagnet auf',
    32: 'Von innen geöffnet',
    33: 'Verriegelt (Fingerprint)',
    34: 'Verriegelt (Passcode)',
    35: 'Verriegelt (IC-Karte)',
    36: 'Verriegelt (mech. Schlüssel)',
    37: 'Fernbedienung',
    44: 'Sabotage-Alarm',
    45: 'Auto-Lock',
    46: 'Entriegeln (Unlock-Key)',
    47: 'Verriegeln (Lock-Key)',
    48: 'Mehrf. Falsch-Passcode',
}


class TTLockError(RuntimeError):
    pass


class TTLockClient:
    """Dünner, signierter HTTP-Client – exakt wie im Plan skizziert (rein API)."""

    def __init__(self, endpoint, client_id, client_secret):
        self.endpoint = endpoint.rstrip('/')
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = None
        self.uid = None
        self.session = requests.Session()

    @staticmethod
    def _now_ms():
        return int(time.time() * 1000)

    def login(self, username, password):
        """OAuth2 password-grant; password muss als MD5 (lowercase hex) gehen."""
        pw_md5 = hashlib.md5(password.encode('utf-8')).hexdigest()
        data = {
            'clientId': self.client_id,
            'clientSecret': self.client_secret,
            'username': username,
            'password': pw_md5,
            'grant_type': 'password',
        }
        resp = self.session.post(f'{self.endpoint}/oauth2/token', data=data, timeout=20)
        resp.raise_for_status()
        body = resp.json()
        if 'access_token' not in body:
            raise TTLockError(f'Login fehlgeschlagen: {body}')
        self.access_token = body['access_token']
        self.uid = body.get('uid')
        return body

    def _get(self, path, **params):
        """GET mit Pflicht-Signatur (clientId + accessToken + date)."""
        params.update({
            'clientId': self.client_id,
            'accessToken': self.access_token,
            'date': self._now_ms(),
        })
        resp = self.session.get(f'{self.endpoint}/{path.lstrip("/")}', params=params, timeout=20)
        resp.raise_for_status()
        body = resp.json()
        # TTLock-Fehler-Envelope: errcode != 0 ist ein Fehler (auch bei HTTP 200).
        if isinstance(body, dict) and body.get('errcode', 0):
            raise TTLockError(f'{path}: errcode={body["errcode"]} {body.get("errmsg")} '
                              f'({body.get("description", "")})')
        return body

    # --- Inventar -----------------------------------------------------------
    def lock_list(self, page_no=1, page_size=100):
        return self._get('v3/lock/list', pageNo=page_no, pageSize=page_size)

    def gateways_by_lock(self, lock_id):
        return self._get('v3/gateway/listByLock', lockId=lock_id)

    # --- IC-Cards (Chips) ---------------------------------------------------
    def ic_cards(self, lock_id, page_no=1, page_size=100):
        return self._get('v3/identityCard/list', lockId=lock_id,
                         pageNo=page_no, pageSize=page_size)

    # --- Zutrittslogs -------------------------------------------------------
    def lock_records(self, lock_id, start_ms, end_ms, page_no=1, page_size=100):
        return self._get('v3/lockRecord/list', lockId=lock_id,
                         startDate=start_ms, endDate=end_ms,
                         pageNo=page_no, pageSize=page_size)


def ms_to_str(ms):
    if not ms:
        return '-'
    try:
        return datetime.fromtimestamp(ms / 1000).strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, OSError, TypeError):
        return str(ms)


def dump(label, obj):
    print(f'\n=== {label} ===')
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description='TTLock-PoC (read-only)')
    ap.add_argument('--days', type=int, default=30, help='Zeitfenster für Logs in Tagen (default 30)')
    ap.add_argument('--lock-id', type=int, default=None, help='nur dieses Schloss abfragen')
    ap.add_argument('--max-logs', type=int, default=20, help='max. Log-Einträge je Schloss (default 20)')
    ap.add_argument('--raw', action='store_true', help='Roh-JSON ausgeben statt Tabellen')
    args = ap.parse_args()

    cfg = {
        'endpoint': os.getenv('TTLOCK_ENDPOINT', DEFAULT_ENDPOINT),
        'client_id': os.getenv('TTLOCK_CLIENT_ID'),
        'client_secret': os.getenv('TTLOCK_CLIENT_SECRET'),
        'username': os.getenv('TTLOCK_USERNAME'),
        'password': os.getenv('TTLOCK_PASSWORD'),
    }
    missing = [k for k in ('client_id', 'client_secret', 'username', 'password') if not cfg[k]]
    if missing:
        print('FEHLER: Es fehlen TTLock-Zugangsdaten in .env: '
              + ', '.join('TTLOCK_' + k.upper() for k in missing), file=sys.stderr)
        print('Siehe .env.example (Abschnitt TTLock).', file=sys.stderr)
        return 2

    client = TTLockClient(cfg['endpoint'], cfg['client_id'], cfg['client_secret'])

    print(f'→ Login bei {cfg["endpoint"]} als {cfg["username"]} …')
    try:
        token = client.login(cfg['username'], cfg['password'])
    except (requests.RequestException, TTLockError) as e:
        print(f'FEHLER beim Login: {e}', file=sys.stderr)
        return 1
    print(f'✓ Login ok (uid={client.uid}, token läuft in '
          f'{token.get("expires_in", "?")}s ab)')

    # --- Schlösser ----------------------------------------------------------
    try:
        locks_resp = client.lock_list()
    except (requests.RequestException, TTLockError) as e:
        print(f'FEHLER bei lock/list: {e}', file=sys.stderr)
        return 1

    locks = locks_resp.get('list', [])
    if args.lock_id:
        locks = [l for l in locks if l.get('lockId') == args.lock_id]

    if args.raw:
        dump('lock/list', locks_resp)
    print(f'\n✓ {len(locks)} Schloss/Schlösser '
          f'(gesamt {locks_resp.get("total", len(locks))}):')
    for l in locks:
        print(f'  • lockId={l.get("lockId")}  {l.get("lockAlias") or l.get("lockName")}')

    end_ms = int(time.time() * 1000)
    start_ms = int((datetime.now() - timedelta(days=args.days)).timestamp() * 1000)

    for l in locks:
        lock_id = l.get('lockId')
        alias = l.get('lockAlias') or l.get('lockName') or lock_id
        print(f'\n──────── Schloss „{alias}" (lockId={lock_id}) ────────')

        # Gateways
        try:
            gws = client.gateways_by_lock(lock_id).get('list', [])
            if args.raw:
                dump('gateways', gws)
            print(f'Gateways: {len(gws)}'
                  + (''.join(f'\n  • {g.get("gatewayName")} '
                             f'(online={g.get("isOnline")})' for g in gws) if gws else ''))
        except (requests.RequestException, TTLockError) as e:
            print(f'  ! Gateways nicht abrufbar: {e}')

        # IC-Cards
        try:
            cards = client.ic_cards(lock_id).get('list', [])
            if args.raw:
                dump('identityCard/list', cards)
            print(f'IC-Cards: {len(cards)}')
            for c in cards[:args.max_logs]:
                print(f'  • cardId={c.get("cardId")} nr={c.get("cardNumber")} '
                      f'„{c.get("cardName")}" gültig {ms_to_str(c.get("startDate"))} '
                      f'– {ms_to_str(c.get("endDate"))}')
        except (requests.RequestException, TTLockError) as e:
            print(f'  ! IC-Cards nicht abrufbar: {e}')

        # Zutrittslogs
        try:
            recs_resp = client.lock_records(lock_id, start_ms, end_ms,
                                            page_size=min(100, args.max_logs))
            recs = recs_resp.get('list', [])
            if args.raw:
                dump('lockRecord/list', recs_resp)
            print(f'Zutrittslogs (letzte {args.days} Tage): '
                  f'{recs_resp.get("total", len(recs))} gesamt, zeige bis {args.max_logs}:')
            for r in recs[:args.max_logs]:
                methode = RECORD_TYPES.get(r.get('recordType'), f'?{r.get("recordType")}')
                ok = '✓' if r.get('success') == 1 else '✗'
                print(f'  {ok} {ms_to_str(r.get("lockDate"))}  {methode:<14} '
                      f'cred={r.get("keyboardPwd")}  user={r.get("username")}')
        except (requests.RequestException, TTLockError) as e:
            print(f'  ! Logs nicht abrufbar: {e}')

    print('\n✓ PoC durchgelaufen.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
