"""Gemeinsame Bausteine der Mitglieder-Importe (SPG-Verein, LINEAR).

Hier stehen nur *reine* Funktionen: Feldbereinigung, Datums- und Zahlenparsen,
Namensnormalisierung, Dekodierung. Der Schreibpfad bleibt bewusst in den
jeweiligen Services — er ist beim SPG-Import produktiv erprobt (610 Mitglieder)
und hat keine Testabdeckung, die einen Umbau tragen würde.

Die Formate unterscheiden sich weniger in der Syntax als in der Semantik: SPG
führt Abteilungen als nummerierte Feldgruppen, LINEAR als Kreuz-Spalten. Genau
deshalb zwei schmale Parser statt eines gemeinsamen Mappers.
"""
from datetime import datetime

# Datumsformate beider Quellen. LINEAR hängt an jedes Datum eine Uhrzeit
# („13.01.2005 00:00"), SPG nicht — die Liste deckt beide ab, damit ein Format
# nicht am jeweils anderen Importer vorbeiläuft.
_DATUM_FORMATE = ('%d.%m.%Y', '%Y-%m-%d', '%d.%m.%Y %H:%M', '%d.%m.%Y %H:%M:%S')

# Reihenfolge der Kodierungsversuche. SPG exportiert cp1252, LINEAR UTF-8 —
# beim falschen Griff landen „StaatsangehÃ¶rigkeit" und „FuÃball" dauerhaft in
# der DB. utf-8-sig zuerst, weil ein BOM sonst im ersten Spaltennamen klebt.
KODIERUNGEN = ('utf-8-sig', 'utf-8', 'cp1252')


def clean(v):
    """Feldwert trimmen und von einfachen Anführungszeichen befreien."""
    if v is None:
        return ''
    v = v.strip()
    if len(v) >= 2 and v[0] == "'" and v[-1] == "'":
        v = v[1:-1]
    return v.strip()


def to_iso(d):
    """Datum in ISO-Form — None, wenn leer oder unlesbar (nie geraten)."""
    d = clean(d)
    if not d:
        return None
    for fmt in _DATUM_FORMATE:
        try:
            return datetime.strptime(d, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def to_nr(s):
    s = clean(s)
    try:
        return int(s)
    except ValueError:
        return None


def norm_abt(s):
    """Vergleichsform eines Abteilungsnamens (Groß/Klein, Leerzeichen, ß egal)."""
    s = (s or '').lower().replace('ß', 'ss')
    return ''.join(c for c in s if c.isalnum())


def decode_csv(data: bytes, kodierungen=KODIERUNGEN) -> str:
    """Rohdaten dekodieren — die erste Kodierung gewinnt, die aufgeht.

    Wirft UnicodeDecodeError, wenn keine passt; der Aufrufer meldet das als
    Formatfehler, statt kaputte Umlaute zu importieren.
    """
    for kodierung in kodierungen:
        try:
            return data.decode(kodierung)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError(
        kodierungen[-1], data, 0, 1,
        'Datei ist in keiner der erwarteten Kodierungen lesbar '
        f'({", ".join(kodierungen)})')
