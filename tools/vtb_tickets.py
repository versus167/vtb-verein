#!/usr/bin/env python3
"""VTB-Tickets-Brücke: holt Tickets des Bereichs "VTB-App" aus der laufenden
App über die HTTP-API in Claude Code und schreibt Status/Kommentare zurück.

Nur Python-Standardbibliothek – keine Abhängigkeiten nötig.

Konfiguration (Vorrang: echte Umgebungsvariablen > tools/tickets.local.env):
    VTB_TICKETS_URL      Basis-URL der App, z.B. https://verein.example.de
    VTB_TICKETS_USER     Benutzername (Service-User mit Bearbeiten-Recht im Bereich)
    VTB_TICKETS_PASS     Passwort
    VTB_TICKETS_BEREICH  Bereichsname (Default: "VTB-App")

Beispiele:
    python3 tools/vtb_tickets.py pull               # offene Tickets -> tickets/vtb-app.md
    python3 tools/vtb_tickets.py pull --all         # inkl. erledigt/abgelehnt
    python3 tools/vtb_tickets.py show 42
    python3 tools/vtb_tickets.py comment 42 "Gefixt in $(git rev-parse --short HEAD)" --intern
    python3 tools/vtb_tickets.py status 42 erledigt
    python3 tools/vtb_tickets.py resolve 42 -m "Behoben in abc1234"   # Kommentar + erledigt
    python3 tools/vtb_tickets.py create "Titel" -b "Beschreibung" -p niedrig
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Opener mit Cookie-Jar: seit v2026.06.22.40 (Ticket #48) transportiert die App
# das Session-JWT in einem HttpOnly-Cookie. Der Jar nimmt das Set-Cookie vom Login
# automatisch auf und schickt es bei Folge-Requests mit. Der Bearer-Header bleibt
# als Fallback für ältere Server-Stände (die das Token noch im Body liefern).
_COOKIE_JAR = http.cookiejar.CookieJar()
_OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_COOKIE_JAR))

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / "tools" / "tickets.local.env"
OUT_FILE = ROOT / "tickets" / "vtb-app.md"

GUELTIGE_STATUS = [
    "offen", "in_pruefung", "eingeplant", "rueckfrage", "erledigt", "abgelehnt",
]
ABGESCHLOSSEN = {"erledigt", "abgelehnt"}
PRIO_RANG = {"sicherheit": 0, "hoch": 1, "normal": 2, "niedrig": 3}


# --------------------------------------------------------------------------- #
# Konfiguration
# --------------------------------------------------------------------------- #
def _load_env_file(path: Path) -> dict[str, str]:
    werte: dict[str, str] = {}
    if not path.exists():
        return werte
    for zeile in path.read_text(encoding="utf-8").splitlines():
        zeile = zeile.strip()
        if not zeile or zeile.startswith("#") or "=" not in zeile:
            continue
        key, _, val = zeile.partition("=")
        werte[key.strip()] = val.strip().strip('"').strip("'")
    return werte


def get_config() -> dict[str, str]:
    datei = _load_env_file(ENV_FILE)

    def hol(key: str, default: str | None = None) -> str | None:
        return os.environ.get(key) or datei.get(key) or default

    url = hol("VTB_TICKETS_URL")
    user = hol("VTB_TICKETS_USER")
    passwort = hol("VTB_TICKETS_PASS")
    bereich = hol("VTB_TICKETS_BEREICH", "VTB-App")

    fehlend = [k for k, v in
               {"VTB_TICKETS_URL": url, "VTB_TICKETS_USER": user, "VTB_TICKETS_PASS": passwort}.items()
               if not v]
    if fehlend:
        sys.exit(
            f"Fehlende Konfiguration: {', '.join(fehlend)}.\n"
            f"Bitte in {ENV_FILE} eintragen (siehe tools/tickets.env.example) "
            f"oder als Umgebungsvariablen setzen."
        )
    return {"url": url.rstrip("/"), "user": user, "pass": passwort, "bereich": bereich}


# --------------------------------------------------------------------------- #
# HTTP-Hilfen
# --------------------------------------------------------------------------- #
class ApiError(RuntimeError):
    pass


def _request(method: str, url: str, *, token: str | None = None,
             json_body: dict | None = None, form_body: dict | None = None,
             raw: bool = False) -> object:
    headers = {"Accept": "*/*" if raw else "application/json"}
    data = None
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif form_body is not None:
        data = urllib.parse.urlencode(form_body).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with _OPENER.open(req, timeout=60) as resp:
            roh = resp.read()
            if raw:
                return roh
            text = roh.decode("utf-8")
            return json.loads(text) if text else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        try:
            detail = json.loads(detail).get("detail", detail)
        except Exception:
            pass
        raise ApiError(f"HTTP {exc.code} bei {method} {url}: {detail}") from None
    except urllib.error.URLError as exc:
        raise ApiError(f"Verbindung fehlgeschlagen ({url}): {exc.reason}") from None


class Client:
    def __init__(self, cfg: dict[str, str]):
        self.base = cfg["url"] + "/api"
        self.cfg = cfg
        self.token: str | None = None

    def login(self) -> None:
        res = _request("POST", f"{self.base}/auth/login",
                       form_body={"username": self.cfg["user"], "password": self.cfg["pass"]})
        # Neuer Server (v40+) setzt nur das Session-Cookie (im Jar) und liefert kein
        # access_token mehr; älterer Server liefert es weiter im Body → als Bearer nutzen.
        self.token = res.get("access_token") if isinstance(res, dict) else None

    def get(self, pfad: str) -> object:
        return _request("GET", f"{self.base}{pfad}", token=self.token)

    def post(self, pfad: str, body: dict) -> object:
        return _request("POST", f"{self.base}{pfad}", token=self.token, json_body=body)

    def patch(self, pfad: str, body: dict) -> object:
        return _request("PATCH", f"{self.base}{pfad}", token=self.token, json_body=body)

    def anhaenge(self, ticket_id: int) -> list[dict]:
        eintraege = self.get(f"/tickets/{ticket_id}/anhaenge") or []
        return [a for a in eintraege if not a.get("deleted_at")]

    def download(self, stored_name: str) -> bytes:
        return _request("GET", f"{self.base}/uploads/{stored_name}",
                        token=self.token, raw=True)

    def bereich_id(self, name: str) -> int:
        bereiche = self.get("/tickets/bereiche") or []
        exakt = [b for b in bereiche if b["name"].lower() == name.lower()]
        treffer = exakt or [b for b in bereiche if name.lower() in b["name"].lower()]
        if not treffer:
            verfuegbar = ", ".join(b["name"] for b in bereiche) or "(keine)"
            raise ApiError(f"Bereich '{name}' nicht gefunden. Verfügbar: {verfuegbar}")
        if len(treffer) > 1:
            namen = ", ".join(b["name"] for b in treffer)
            raise ApiError(f"Bereich '{name}' ist mehrdeutig: {namen}")
        return treffer[0]["id"]


# --------------------------------------------------------------------------- #
# Formatierung
# --------------------------------------------------------------------------- #
def _prio_sort(t: dict) -> tuple:
    return (PRIO_RANG.get(t.get("prioritaet"), 9), t.get("id") or 0)


def render_markdown(tickets: list[dict], bereich: str, mit_abgeschlossen: bool) -> str:
    zeilen = [f"# Tickets – Bereich „{bereich}“", ""]
    filterhinweis = "alle (inkl. abgeschlossen)" if mit_abgeschlossen else "nur offene"
    zeilen.append(f"_{len(tickets)} Tickets ({filterhinweis})_")
    zeilen.append("")
    for t in tickets:
        kopf = (f"## #{t['id']} · {t['titel']}  "
                f"[{t['status']} / {t.get('prioritaet', '?')}]")
        zeilen.append(kopf)
        meta = [f"gemeldet von {t.get('gemeldet_von_username', '?')}"]
        if t.get("kategorie_id"):
            meta.append(f"Kategorie {t['kategorie_id']}")
        if t.get("faellig_am"):
            meta.append(f"fällig {t['faellig_am']}")
        if t.get("kommentar_count"):
            meta.append(f"{t['kommentar_count']} Kommentar(e)")
        if t.get("anhang_count"):
            meta.append(f"{t['anhang_count']} Anhang/Anhänge")
        zeilen.append("_" + " · ".join(meta) + "_")
        zeilen.append("")
        besch = (t.get("beschreibung") or "").strip()
        zeilen.append(besch if besch else "_(keine Beschreibung)_")
        zeilen.append("")
    return "\n".join(zeilen).rstrip() + "\n"


# --------------------------------------------------------------------------- #
# Befehle
# --------------------------------------------------------------------------- #
def cmd_pull(client: Client, args) -> None:
    bid = client.bereich_id(client.cfg["bereich"])
    tickets = client.get(f"/tickets/?bereich_id={bid}") or []
    if not args.all:
        tickets = [t for t in tickets if t.get("status") not in ABGESCHLOSSEN]
    tickets.sort(key=_prio_sort)

    md = render_markdown(tickets, client.cfg["bereich"], args.all)
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(md, encoding="utf-8")
    print(md)
    print(f"\n→ {len(tickets)} Tickets geschrieben nach {OUT_FILE.relative_to(ROOT)}",
          file=sys.stderr)


def cmd_show(client: Client, args) -> None:
    t = client.get(f"/tickets/{args.id}")
    print(f"#{t['id']} · {t['titel']}  [{t['status']} / {t.get('prioritaet')}]")
    print(f"gemeldet von {t.get('gemeldet_von_username', '?')}"
          f" · Bereich {t.get('bereich_name')} · Version {t.get('version')}")
    print()
    print((t.get("beschreibung") or "(keine Beschreibung)").strip())
    print("\n--- Kommentare ---")
    kommentare = client.get(f"/tickets/{args.id}/kommentare") or []
    if not kommentare:
        print("(keine)")
    for k in kommentare:
        autor = k.get("autor_username") or k.get("autor_id")
        sicht = k.get("sichtbarkeit")
        print(f"\n[{k.get('created_at', '')}] {autor} ({sicht}):")
        print(k.get("inhalt", "").strip())

    anhaenge = client.anhaenge(args.id)
    print("\n--- Anhänge ---")
    if not anhaenge:
        print("(keine)")
    for a in anhaenge:
        print(f"  #{a['id']} {a.get('original_name')} ({a.get('mime_type')}, "
              f"{a.get('dateigroesse')} Bytes)")
    if anhaenge:
        print(f"\nHerunterladen: python3 tools/vtb_tickets.py attach {args.id}")


def cmd_attach(client: Client, args) -> None:
    anhaenge = client.anhaenge(args.id)
    if not anhaenge:
        print(f"Ticket #{args.id}: keine Anhänge.")
        return
    ziel = ROOT / "tickets" / "anhaenge" / str(args.id)
    ziel.mkdir(parents=True, exist_ok=True)
    for a in anhaenge:
        daten = client.download(a["stored_name"])
        basis = os.path.basename(a.get("original_name") or a["stored_name"]).replace("\\", "_")
        pfad = ziel / f"{a['id']}_{basis}"
        pfad.write_bytes(daten)
        print(f"  {pfad.relative_to(ROOT)}  ({a.get('mime_type')}, {len(daten)} Bytes)")
    print(f"→ {len(anhaenge)} Anhang/Anhänge von Ticket #{args.id} gespeichert.")


def cmd_comment(client: Client, args) -> None:
    sicht = "intern" if args.intern else "oeffentlich"
    client.post(f"/tickets/{args.id}/kommentare",
                {"inhalt": args.text, "sichtbarkeit": sicht})
    print(f"Kommentar ({sicht}) an Ticket #{args.id} geschrieben.")


def cmd_status(client: Client, args) -> None:
    if args.status not in GUELTIGE_STATUS:
        sys.exit(f"Ungültiger Status '{args.status}'. Gültig: {', '.join(GUELTIGE_STATUS)}")
    t = client.get(f"/tickets/{args.id}")
    client.patch(f"/tickets/{args.id}/status",
                 {"status": args.status, "expected_version": t["version"]})
    print(f"Ticket #{args.id}: Status → {args.status}")


def cmd_create(client: Client, args) -> None:
    if args.prio not in PRIO_RANG:
        sys.exit(f"Ungültige Priorität '{args.prio}'. Gültig: {', '.join(PRIO_RANG)}")
    ticket = client.post("/tickets/", {
        "titel": args.titel,
        "beschreibung": args.beschreibung or "",
        "prioritaet": args.prio,
        "bereich_id": client.bereich_id(client.cfg["bereich"]),
    })
    print(f"Ticket #{ticket['id']} angelegt: {ticket['titel']} (Prio {ticket['prioritaet']})")


def cmd_resolve(client: Client, args) -> None:
    if args.message:
        sicht = "intern" if args.intern else "oeffentlich"
        client.post(f"/tickets/{args.id}/kommentare",
                    {"inhalt": args.message, "sichtbarkeit": sicht})
        print(f"Kommentar ({sicht}) an Ticket #{args.id} geschrieben.")
    t = client.get(f"/tickets/{args.id}")
    client.patch(f"/tickets/{args.id}/status",
                 {"status": "erledigt", "expected_version": t["version"]})
    print(f"Ticket #{args.id}: Status → erledigt")


# --------------------------------------------------------------------------- #
# Argument-Parsing
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="VTB-Tickets-Brücke (HTTP-API).")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("pull", help="Tickets des Bereichs holen und als Markdown ablegen")
    sp.add_argument("--all", action="store_true", help="inkl. erledigt/abgelehnt")
    sp.set_defaults(func=cmd_pull)

    sp = sub.add_parser("show", help="Einzelnes Ticket mit Kommentaren anzeigen")
    sp.add_argument("id", type=int)
    sp.set_defaults(func=cmd_show)

    sp = sub.add_parser("attach", help="Anhänge eines Tickets herunterladen")
    sp.add_argument("id", type=int)
    sp.set_defaults(func=cmd_attach)

    sp = sub.add_parser("comment", help="Kommentar an ein Ticket schreiben")
    sp.add_argument("id", type=int)
    sp.add_argument("text")
    sp.add_argument("--intern", action="store_true", help="interner Kommentar (Bearbeiter-Recht)")
    sp.set_defaults(func=cmd_comment)

    sp = sub.add_parser("status", help="Status eines Tickets ändern")
    sp.add_argument("id", type=int)
    sp.add_argument("status", help=f"einer von: {', '.join(GUELTIGE_STATUS)}")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("create", help="Neues Ticket im konfigurierten Bereich anlegen")
    sp.add_argument("titel")
    sp.add_argument("-b", "--beschreibung", help="Beschreibung (Markdown/Text)")
    sp.add_argument("-p", "--prio", default="normal",
                    help=f"eine von: {', '.join(PRIO_RANG)} (Default: normal)")
    sp.set_defaults(func=cmd_create)

    sp = sub.add_parser("resolve", help="Optional kommentieren und auf 'erledigt' setzen")
    sp.add_argument("id", type=int)
    sp.add_argument("-m", "--message", help="Kommentar (z.B. Commit-Hash)")
    sp.add_argument("--intern", action="store_true", help="Kommentar intern")
    sp.set_defaults(func=cmd_resolve)

    return p


def main() -> None:
    parser = build_parser()
    # 'pull' wird aus dem /tickets-Slash-Command mit einem (ggf. leeren oder
    # vom Harness mit Fremdtext gefüllten) gequoteten Roh-Blob aufgerufen.
    # Deshalb tolerant parsen: '--all' auch in unbekannten Argumenten erkennen,
    # restlichen Müll ignorieren. Für alle anderen Befehle bleibt es strikt.
    args, extra = parser.parse_known_args()
    if getattr(args, "cmd", None) == "pull":
        if any("--all" in tok.split() for tok in extra):
            args.all = True
    elif extra:
        parser.error(f"unrecognized arguments: {' '.join(extra)}")
    cfg = get_config()
    client = Client(cfg)
    try:
        client.login()
        args.func(client, args)
    except ApiError as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
