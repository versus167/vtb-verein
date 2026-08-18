"""
Prüfung und Normalisierung von E-Mail-Adressen (Aufbau, nicht Erreichbarkeit).

Framework-agnostischer Kern (keine FastAPI-Abhängigkeit): wird vom HTTP-Adapter
`backend/core/validation.py` und dem Frontend-Pendant `frontend/src/utils/email.js`
gespiegelt – dasselbe Muster wie bei der IBAN (`iban.py`). Eine leere Adresse gilt
als „nicht gesetzt" (None) und ist gültig; wo eine Adresse Pflicht ist, prüft das
der Aufrufer (Konten ohne Zugang haben bewusst keine, siehe Schema v96).

Geprüft wird der *Aufbau*, mehr kann eine Eingabeprüfung nicht leisten: ob hinter
der Adresse ein Postfach steht, zeigt erst der Versand (und ein Bounce nicht einmal
der). Der reguläre Ausdruck ist deshalb bewusst pragmatisch statt RFC-5322-komplett –
er fängt Tippfehler wie fehlendes @ oder „…@web" ab, ohne exotische, aber zulässige
Adressen abzulehnen. Quoted-Strings ("a b"@x.de) und Adress-Literale (a@[10.0.0.1])
sind dabei außen vor: Sie sind erlaubt, kommen in einem Verein aber nicht vor und
wären fast immer ein Vertipper.
"""
import re
from typing import Optional

# Obergrenzen nach RFC 5321: 254 Zeichen für den ganzen Pfad, 64 für den lokalen Teil.
MAX_LAENGE = 254
MAX_LOKALTEIL = 64

# Im lokalen Teil zugelassene Zeichen (RFC-5322-„atext" plus Punkt als Trenner).
_LOKALTEIL_RE = re.compile(r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*$")
# Ein Domain-Label: alphanumerisch, Bindestriche nur innen, höchstens 63 Zeichen.
_LABEL_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


def normalize_mailadresse(value: Optional[str]) -> Optional[str]:
    """Außenliegenden Whitespace entfernen; leer → None.

    Die Groß-/Kleinschreibung bleibt bewusst unangetastet: Der Unique-Index auf
    `users.email` und die Magic-Link-Suche vergleichen den Bestand so, wie er
    gespeichert wurde – ein stilles Kleinschreiben würde die Anmeldung bestehender
    Konten verändern statt nur eine Eingabe zu prüfen.
    """
    if value is None:
        return None
    return value.strip() or None


def pruefe_mailadresse(adresse: str) -> Optional[str]:
    """Gibt die Fehlerursache als Klartext zurück – oder None, wenn alles passt.

    Getrennt von `validate_mailadresse`, damit dieselbe Prüfung auch ohne Exception
    nutzbar ist (z. B. für eine Liste auffälliger Bestandsadressen).
    """
    if re.search(r"\s", adresse):
        return "E-Mail-Adresse darf keine Leerzeichen enthalten."
    if len(adresse) > MAX_LAENGE:
        return f"E-Mail-Adresse ist zu lang (höchstens {MAX_LAENGE} Zeichen)."
    if adresse.count("@") != 1:
        return "E-Mail-Adresse braucht genau ein @ (z. B. name@verein.de)."

    lokal, domain = adresse.split("@")
    if not lokal:
        return "Vor dem @ fehlt der Name (z. B. name@verein.de)."
    if len(lokal) > MAX_LOKALTEIL:
        return f"Der Teil vor dem @ ist zu lang (höchstens {MAX_LOKALTEIL} Zeichen)."
    if not _LOKALTEIL_RE.match(lokal):
        return "Der Teil vor dem @ enthält unzulässige Zeichen."

    if not domain:
        return "Nach dem @ fehlt die Domain (z. B. name@verein.de)."
    labels = domain.split(".")
    if len(labels) < 2:
        return "Nach dem @ fehlt die Endung (z. B. @verein.de statt @verein)."
    if any(not _LABEL_RE.match(teil) for teil in labels):
        return "Die Domain nach dem @ ist nicht gültig (z. B. name@verein.de)."
    if not re.fullmatch(r"[A-Za-z]{2,}", labels[-1]):
        return "Die Endung nach dem letzten Punkt muss aus mindestens zwei Buchstaben bestehen."
    return None


def is_valid_mailadresse(value: Optional[str]) -> bool:
    """True, wenn der Aufbau stimmt. Leer/None → False (hier heißt „leer" ungültig;
    ob eine leere Adresse erlaubt ist, entscheidet der Aufrufer)."""
    adresse = normalize_mailadresse(value)
    return adresse is not None and pruefe_mailadresse(adresse) is None


def validate_mailadresse(value: Optional[str], *, pflicht: bool = False) -> Optional[str]:
    """Normalisiert die Adresse und gibt sie zurück.

    Leer/None → None (gültig, solange `pflicht` nicht gesetzt ist).
    Ungültiger Aufbau → ValueError mit sprechender Meldung.
    """
    adresse = normalize_mailadresse(value)
    if adresse is None:
        if pflicht:
            raise ValueError("E-Mail-Adresse ist erforderlich.")
        return None
    fehler = pruefe_mailadresse(adresse)
    if fehler:
        raise ValueError(fehler)
    return adresse
