"""Der Scanner-Rahmen braucht eine <div>-Hülle im Dialog (Ticket #197).

Quasar macht den Inhalt eines Dialogs über genau zwei CSS-Regeln bedienbar und
groß — und beide treffen ausschließlich ein direktes ``div``:

    .q-dialog__inner            { }        /* Klasse `no-pointer-events` */
    .q-dialog__inner > div      { pointer-events: all; … }
    .q-dialog__inner--maximized > div { height: 100%; width: 100%; … }

Ein ``<iframe>`` als direktes Kind trifft keine davon. Er bleibt damit auf
``pointer-events: none``, jeder Tipp fällt auf den Backdrop durch, und weil der
Dialog ``persistent`` ist, spielt Quasar dort seine Wackel-Animation ab
(QDialog.js: ``onBackdropPress`` → ``shake()`` → ``q-animate--scale``).

Auf dem Gerät sieht das aus, als reagiere kein einziger Knopf und das Bild
„zucke" nur — exakt so gemeldet in #197.

Gemessen im echten Dialog, mit echten Touch-Events:

    mit Hülle:   rahmen pointer-events = all   → jeder Knopf trifft, 0 Wackler
    ohne Hülle:  rahmen pointer-events = none  → nichts erreichbar

Besonders tückisch war, dass es trotzdem *richtig aussah*: Der Rahmen trug
``width: 100vw; height: 100vh`` und ersetzte damit zufällig die fehlende
Größenregel — zwei Fehler, die sich optisch aufhoben. Deshalb prüft dieser Test
die Struktur und nicht das Aussehen.
"""
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_DIALOG = _ROOT / "frontend/src/components/BelegScannenDialog.vue"


def _template() -> str:
    quelle = _DIALOG.read_text(encoding="utf-8")
    treffer = re.search(r"<template>(.*?)</template>", quelle, re.S)
    assert treffer, "kein <template> in BelegScannenDialog.vue"
    # Kommentare raus — sie erwähnen iframe und q-dialog im Fließtext.
    return re.sub(r"<!--.*?-->", "", treffer.group(1), flags=re.S)


def test_dialog_enthaelt_den_rahmen():
    assert "<iframe" in _template()


def test_rahmen_ist_nicht_direktes_kind_des_dialogs():
    """Der Kern: zwischen <q-dialog> und <iframe> muss etwas stehen.

    Steht der Rahmen direkt im Dialog, ist er auf dem Gerät unbedienbar — ohne
    Fehlermeldung, ohne Konsolenausgabe, ohne dass es im Layout auffiele.
    """
    t = _template()
    direkt = re.search(r"<q-dialog\b[^>]*>\s*<iframe\b", t, re.S)
    assert direkt is None, (
        "Der <iframe> steht direkt im <q-dialog>. Quasars Regel "
        "`.q-dialog__inner > div` greift dann nicht, der Rahmen bleibt auf "
        "pointer-events: none und nimmt keine Eingabe an (s. #197).")


def test_huelle_ist_ein_div():
    """`> div` heißt div — ein <section>, <main> oder <span> täte es nicht."""
    t = _template()
    huelle = re.search(r"<q-dialog\b[^>]*>\s*<(\w[\w-]*)", t, re.S)
    assert huelle, "Dialog-Inhalt nicht gefunden"
    assert huelle.group(1) == "div", (
        f"Dialog-Inhalt ist <{huelle.group(1)}>, Quasar bedient aber nur <div>.")


def test_rahmen_liegt_in_der_huelle():
    """Die Hülle muss den Rahmen auch tatsächlich umschließen."""
    t = _template()
    assert re.search(r"<div\b[^>]*>\s*<iframe\b", t, re.S), \
        "Der <iframe> steht nicht in einem <div>."


def test_rahmen_setzt_keine_viewport_groesse_mehr():
    """100vw/100vh würde die fehlende Quasar-Regel wieder verdecken.

    Genau das hat den Fehler beim ersten Mal unsichtbar gemacht: Der Rahmen sah
    richtig aus, obwohl die Regel nie griff. Die Größe soll von Quasar kommen —
    das ist am Handy zusätzlich korrekter, weil Quasar 100dvh benutzt und damit
    die Browserleiste berücksichtigt.
    """
    quelle = _DIALOG.read_text(encoding="utf-8")
    stil = re.search(r"<style[^>]*>(.*?)</style>", quelle, re.S)
    assert stil, "kein <style> in BelegScannenDialog.vue"
    rahmen = re.search(r"\.beleg-scanner-rahmen\s*\{(.*?)\}", stil.group(1), re.S)
    assert rahmen, "keine Regel für .beleg-scanner-rahmen"
    assert "100vh" not in rahmen.group(1) and "100vw" not in rahmen.group(1), (
        "Der Rahmen setzt wieder eine Viewport-Größe und verdeckt damit, ob "
        "Quasars Regel greift.")
