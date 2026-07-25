"""Drift-Test der Berechtigungs-Matrix (PERMISSION_GROUPS in backend/api/users.py).

Die Matrix ist eine handgepflegte Liste und die EINZIGE Stelle, über die ein Recht
in der UI vergeben werden kann (Funktionen-Matrix und Benutzer-Berechtigungen laden
beide /api/users/permission-groups). Ein neuer Permission-Key, der dort nicht
auftaucht, existiert im Backend, ist aber nirgends zuweisbar – ein Fehler, der
sonst erst beim Anwender auffällt.

Reine Python-Tests, keine DB nötig.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # Repo-Root für backend.*

from backend.api.users import PERMISSION_GROUPS, permission_groups_payload  # noqa: E402
from app.models.permission import Permission  # noqa: E402


# Keys, die bewusst NICHT in der globalen Matrix stehen. Wer hier etwas einträgt,
# soll begründen können, warum das Recht anders vergeben wird.
NICHT_IN_MATRIX = {
    # Sockelrecht bzw. objektbezogen über ticket_bereich_berechtigungen vergeben
    # (siehe BERECHTIGUNGEN.md, "Was NICHT über dieses System läuft").
    Permission.TICKETS_EDIT,
    Permission.TICKETS_ASSIGN,
    Permission.TICKETS_CLOSE,
    Permission.TICKETS_DELETE,
    Permission.TICKETS_INTERN_READ,
    # Legacy, laut permission.py nur noch für die Migration vorhanden.
    Permission.TICKETS_READ,
    Permission.TICKETS_CREATE,
    # BEKANNTE LÜCKE (Altbestand, nicht durch diesen Branch entstanden): das Recht
    # ist real und wird geprüft, lässt sich aber nur per SQL vergeben. Gehört in
    # eine eigene Gruppe „Termine", sobald jemand sie anlegt.
    Permission.TERMINE_VERWALTEN,
}


def _keys_in_matrix() -> set[str]:
    return {key for g in PERMISSION_GROUPS for key, _ in g['permissions']}


def test_jeder_permission_key_ist_zuweisbar():
    fehlend = set(Permission.all()) - _keys_in_matrix() - NICHT_IN_MATRIX
    assert not fehlend, (
        "Permission-Key(s) ohne Eintrag in PERMISSION_GROUPS – im Backend vorhanden, "
        f"aber in der UI nicht vergebbar: {sorted(fehlend)}"
    )


def test_matrix_enthaelt_nur_existierende_keys():
    """Tippfehler oder umbenannte Konstanten fallen sonst nicht auf."""
    unbekannt = _keys_in_matrix() - set(Permission.all())
    assert not unbekannt, f"Unbekannte Keys in PERMISSION_GROUPS: {sorted(unbekannt)}"


def test_rechnungs_rechte_sind_vergebbar():
    """Der Bereich Rechnungen ist ohne diese drei Keys nicht bedienbar."""
    keys = _keys_in_matrix()
    for key in (Permission.RECHNUNGEN_EINREICHEN, Permission.RECHNUNGEN_FREIGEBEN,
                Permission.RECHNUNGEN_VERWALTEN):
        assert key in keys, f"{key} fehlt in der Berechtigungs-Matrix"


def test_keine_doppelten_keys():
    """Ein doppelt gelisteter Key gäbe zwei Checkboxen für dasselbe Recht."""
    alle = [key for g in PERMISSION_GROUPS for key, _ in g['permissions']]
    doppelt = {k for k in alle if alle.count(k) > 1}
    assert not doppelt, f"Mehrfach gelistete Keys: {sorted(doppelt)}"


@pytest.mark.parametrize("gruppe", PERMISSION_GROUPS, ids=lambda g: g['label'])
def test_gruppen_sind_vollstaendig_beschriftet(gruppe):
    assert gruppe['label'] and gruppe['icon']
    assert gruppe['permissions'], "Gruppe ohne Rechte wäre eine leere Überschrift"
    for key, label in gruppe['permissions']:
        assert key and label, f"Eintrag ohne Key oder Label in {gruppe['label']}"


def test_payload_struktur_fuer_die_ui():
    """Das Frontend erwartet je Gruppe label/icon und je Recht key/label."""
    payload = permission_groups_payload()
    assert len(payload) == len(PERMISSION_GROUPS)
    for gruppe in payload:
        assert set(gruppe) == {'label', 'icon', 'permissions'}
        for eintrag in gruppe['permissions']:
            assert set(eintrag) == {'key', 'label'}
