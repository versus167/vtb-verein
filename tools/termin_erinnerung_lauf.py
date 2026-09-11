#!/usr/bin/env python3
"""
Termin-Erinnerungen (#95-Nachgang) – für Sidecar/Cron (Default „einmal täglich").

Erinnert kurz vor einem Termin die, von denen noch keine Meldung vorliegt – Kader
wie eingeladene Gäste, jeder einzeln und nur zu seinen eigenen offenen Terminen.
Wer zu-, ab- oder „vielleicht" gesagt hat, hört nichts.

Der Vorlauf (zwei Stufen, Vorgabe 3 und 1 Tag) steht in der App unter
Termine → Erinnerungen, nicht im Code: Wie viel Vorlauf eine Mannschaft braucht,
weiß der Verein. Stufe 0 schaltet eine Stufe ab, der Schalter den ganzen Lauf.
Dazu die Spieltags-Stufe am Termintag selbst – nur zu Spielen und nur, solange
der Anpfiff noch bevorsteht.

Schreibt nur in die eigene DB (eine Protokollzeile je Termin und Stufe, damit
dieselbe Erinnerung nicht bei jedem Lauf erneut rausgeht) und verschickt
Benachrichtigungen über den Kanal, den der Empfänger eingestellt hat.

Die DB kommt aus VTB_DATABASE_URL (Env/.env).

`--wenn-faellig` ist der Sidecar-Modus: Der Container tickt in kurzen Abständen,
gelaufen wird aber nur, wenn seit dem letzten Lauf genug Zeit vergangen ist
(`TERMIN_ERINNERUNG_INTERVAL_HOURS`, Vorgabe 24). Ohne das löste jeder Deploy einen
zusätzlichen Lauf aus, weil die Schleife im Container mit dem Lauf beginnt und
erst danach schläft.

WANN am Tag gelaufen wird, sagt die Uhrzeit aus denselben Einstellungen
(Vorgabe 7 Uhr): Vor ihr läuft nichts, und der Abstand zählt ab ihr — sonst bliebe
ein nach einer Störung verspäteter Lauf für immer zur falschen Zeit stehen
(s. lauf_takt). Genau getroffen wird sie nie, der Lauf startet beim ersten Tick
danach (`TERMIN_ERINNERUNG_TICK_MINUTES`, Vorgabe 30).

Ohne `--wenn-faellig` läuft er sofort — Uhrzeit und Abstand gelten dann nicht.
Ein solcher Lauf von Hand verschiebt den täglichen aber nicht.

Beispiele:
  ./venv/bin/python tools/termin_erinnerung_lauf.py
  ./venv/bin/python tools/termin_erinnerung_lauf.py --trocken
"""
import argparse
import os
import sys
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'vtb_verein'))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, '.env'))
except Exception:
    pass

from app.db.datastore import VereinsDB
from app.services import lauf_takt
from app.services import termin_erinnerung_service as erinnerung
from app.services.termin_notification_service import format_wandzeit, termin_titel


def _trockenlauf(db, log) -> None:
    """Zeigen, was fällig wäre – ohne Versand und ohne Protokollzeile."""
    einst = erinnerung.einstellungen(db)
    if not einst.aktiv:
        log("✓ Termin-Erinnerungen sind abgeschaltet (Termine → Erinnerungen).")
        return
    stufen = [f'{s} Tag(e) vorher' for s in erinnerung.stufen(einst)]
    if einst.spieltag_aktiv:
        stufen.append('am Spieltag (nur Spiele, vor dem Anpfiff)')
    log(f"✓ Stufen: {', '.join(stufen) or '– keine –'}")

    termine = erinnerung.anstehende_termine(db, einst)
    faellig = erinnerung.faellige(
        termine, db.access_log_repository.letzte_je_detail(erinnerung.EVENT_ERINNERUNG),
        einst)
    log(f"✓ {len(termine)} anstehende(r) Termin(e), {len(faellig)} mit fälliger Stufe:")
    for termin, stufe, vorlauf in faellig:
        offene = db.termin_zusagen.list_offene_user_ids(termin.id)
        label = ('Spieltag' if stufe == erinnerung.STUFE_SPIELTAG
                 else f'{stufe}-Tage-Stufe')
        log(f"  #{termin.id} [{label}, {erinnerung.wann_text(vorlauf)}] "
            f"{termin_titel(termin)} am {format_wandzeit(termin.beginn)} "
            f"({termin.mannschaft_name}): {len(offene)} ohne Meldung")


def _intervall_stunden() -> int:
    """Abstand zweier Läufe in Stunden – dieselbe Env-Variable, die der Sidecar für
    seinen Takt liest. Unsinnige Werte fallen auf die Vorgabe zurück, damit ein
    Tippfehler in der `.env` nicht den ganzen Lauf abschaltet."""
    try:
        stunden = int(os.environ.get('TERMIN_ERINNERUNG_INTERVAL_HOURS', '24'))
    except ValueError:
        return 24
    return stunden if stunden >= 1 else 24


def main() -> int:
    ap = argparse.ArgumentParser(description="Erinnerung an fehlende Termin-Meldungen")
    ap.add_argument('--database-url', default=os.environ.get('VTB_DATABASE_URL'))
    ap.add_argument('--trocken', action='store_true',
                    help='nur anzeigen, was fällig wäre – nichts verschicken')
    ap.add_argument('--quiet', action='store_true', help='nur Fehler ausgeben')
    ap.add_argument('--wenn-faellig', action='store_true', dest='wenn_faellig',
                    help=f'nur laufen, wenn seit dem letzten Lauf '
                         f'{_intervall_stunden()} h vergangen sind und die in der App '
                         f'eingestellte Uhrzeit erreicht ist (Sidecar-Modus)')
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
        if args.wenn_faellig:
            # Nichts zu tun heißt: still enden. Sonst stünden im Container-Log ein
            # paar hundert Zeilen „noch nicht fällig" am Tag.
            stunden = _intervall_stunden()
            # Ortszeit, nicht UTC: Die Wunschstunde meint die Uhr an der Wand.
            # `astimezone()` ohne Argument nimmt die Zone des Containers (TZ).
            stunde = erinnerung.einstellungen(db).lauf_stunde
            if not lauf_takt.ist_faellig(lauf_takt.letzter_lauf(db, 'termin_erinnerung_lauf'),
                                         datetime.now().astimezone(),
                                         timedelta(hours=stunden), stunde):
                return 0
            log(f"▶ Termin-Erinnerungen fällig (Takt: alle {stunden} h ab {stunde}:00).")
        res = erinnerung.erinnern(db)
        log(f"✓ {res['erinnert']} von {res['anstehend']} anstehenden Termin(en) erinnert, "
            f"{res['empfaenger']} Empfänger erreicht.")
        # Erst hier vermerken: Ein Lauf, der unterwegs abstürzt, gilt als nicht
        # gelaufen und wird beim nächsten Tick wiederholt.
        lauf_takt.vermerken(db, 'termin_erinnerung_lauf')
    except Exception as e:                      # noqa: BLE001 – Lauf soll sprechen, nicht crashen
        print(f"FEHLER: {e}", file=sys.stderr)
        return 1
    finally:
        db.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
