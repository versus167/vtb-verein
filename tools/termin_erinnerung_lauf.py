#!/usr/bin/env python3
"""
Termin-Erinnerungen (#95-Nachgang) – für Sidecar/Cron (Default „einmal täglich").

Erinnert kurz vor einem Termin die, von denen noch keine Meldung vorliegt – Kader
wie eingeladene Gäste, jeder einzeln und nur zu seinen eigenen offenen Terminen.
Wer zu-, ab- oder „vielleicht" gesagt hat, hört nichts.

Der Vorlauf (zwei Stufen, Vorgabe 3 und 1 Tag) steht in der App unter
Termine → Erinnerungen, nicht im Code: Wie viel Vorlauf eine Mannschaft braucht,
weiß der Verein. Stufe 0 schaltet eine Stufe ab, der Schalter den ganzen Lauf.

Schreibt nur in die eigene DB (eine Protokollzeile je Termin und Stufe, damit
dieselbe Erinnerung nicht bei jedem Lauf erneut rausgeht) und verschickt
Benachrichtigungen über den Kanal, den der Empfänger eingestellt hat.

Die DB kommt aus VTB_DATABASE_URL (Env/.env).

Beispiele:
  ./venv/bin/python tools/termin_erinnerung_lauf.py
  ./venv/bin/python tools/termin_erinnerung_lauf.py --trocken
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'vtb_verein'))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, '.env'))
except Exception:
    pass

from app.db.datastore import VereinsDB
from app.services import termin_erinnerung_service as erinnerung
from app.services.termin_notification_service import format_wandzeit, termin_titel


def _trockenlauf(db, log) -> None:
    """Zeigen, was fällig wäre – ohne Versand und ohne Protokollzeile."""
    einst = erinnerung.einstellungen(db)
    if not einst.aktiv:
        log("✓ Termin-Erinnerungen sind abgeschaltet (Termine → Erinnerungen).")
        return
    stufen = erinnerung.stufen(einst)
    log(f"✓ Stufen: {', '.join(f'{s} Tag(e) vorher' for s in stufen)}")

    termine = erinnerung.anstehende_termine(db, einst)
    faellig = erinnerung.faellige(
        termine, db.access_log_repository.letzte_je_detail(erinnerung.EVENT_ERINNERUNG),
        einst)
    log(f"✓ {len(termine)} anstehende(r) Termin(e), {len(faellig)} mit fälliger Stufe:")
    for termin, stufe, vorlauf in faellig:
        offene = db.termin_zusagen.list_offene_user_ids(termin.id)
        log(f"  #{termin.id} [{stufe}-Tage-Stufe, in {vorlauf} Tag(en)] "
            f"{termin_titel(termin)} am {format_wandzeit(termin.beginn)} "
            f"({termin.mannschaft_name}): {len(offene)} ohne Meldung")


def main() -> int:
    ap = argparse.ArgumentParser(description="Erinnerung an fehlende Termin-Meldungen")
    ap.add_argument('--database-url', default=os.environ.get('VTB_DATABASE_URL'))
    ap.add_argument('--trocken', action='store_true',
                    help='nur anzeigen, was fällig wäre – nichts verschicken')
    ap.add_argument('--quiet', action='store_true', help='nur Fehler ausgeben')
    args = ap.parse_args()

    if not args.database_url:
        print("FEHLER: VTB_DATABASE_URL fehlt (Env/.env oder --database-url).", file=sys.stderr)
        return 2

    db = VereinsDB(args.database_url)

    def log(msg):
        if not args.quiet:
            print(msg)

    try:
        if args.trocken:
            _trockenlauf(db, log)
            return 0
        res = erinnerung.erinnern(db)
        log(f"✓ {res['erinnert']} von {res['anstehend']} anstehenden Termin(en) erinnert, "
            f"{res['empfaenger']} Empfänger erreicht.")
    except Exception as e:                      # noqa: BLE001 – Lauf soll sprechen, nicht crashen
        print(f"FEHLER: {e}", file=sys.stderr)
        return 1
    finally:
        db.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
