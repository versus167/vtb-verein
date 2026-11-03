"""Rechteübersicht (GET /users/permission-overview): wer hat welches Recht?

Die Übersicht dreht die Rechteberechnung um. Sie muss genau das zeigen, was die
Berechtigungsseite des einzelnen Users zeigt – sonst wird sie zur Fehlerquelle
statt zur Kontrolle. Hier die reine Zusammenstellung (ohne DB); die
DB-Gleichheit Gesamt- vs. Einzelberechnung prüft
test_rechte_uebersicht_integration.py.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # Repo-Root für backend.*

from backend.api.users import rechte_uebersicht_payload  # noqa: E402
from app.models.permission import Permission, compute_effective_permissions  # noqa: E402

FUSSBALL = 1


def _person(uid, role='mitglied', active=True):
    return {'id': uid, 'username': f'u{uid}', 'name': None, 'role': role, 'active': active}


def _payload(personen, effektiv):
    return rechte_uebersicht_payload(personen, effektiv, {FUSSBALL: 'Fußball'})


def test_funktionsrecht_vereinsweit_und_abteilungsgebunden():
    eff_global = compute_effective_permissions(
        [{'permission': Permission.BEITRAEGE_READ, 'abteilung_id': None,
          'funktion_name': 'Kassenwart'}], [])
    eff_scoped = compute_effective_permissions(
        [{'permission': Permission.BEITRAEGE_READ, 'abteilung_id': FUSSBALL,
          'funktion_name': 'Abteilungsleiter', 'abteilung_name': 'Fußball'}], [])

    inhaber = _payload([_person(1), _person(2)], {1: eff_global, 2: eff_scoped})['inhaber']

    assert inhaber[Permission.BEITRAEGE_READ] == [
        {'user_id': 1, 'scopes': 'global', 'quellen': ['Kassenwart']},
        {'user_id': 2, 'scopes': ['Fußball'], 'quellen': ['Abteilungsleiter (Fußball)']},
    ]


def test_deny_nimmt_aus_der_liste():
    """Ein entzogenes Recht darf in der Übersicht nicht als vorhanden auftauchen."""
    eff = compute_effective_permissions(
        [{'permission': Permission.BEITRAEGE_READ, 'abteilung_id': None,
          'funktion_name': 'Kassenwart'}],
        [{'permission': Permission.BEITRAEGE_READ, 'effect': 'deny', 'abteilung_id': None}])

    inhaber = _payload([_person(1)], {1: eff})['inhaber']

    assert inhaber[Permission.BEITRAEGE_READ] == []


def test_individueller_grant_und_sockel():
    eff = compute_effective_permissions(
        [], [{'permission': Permission.KASSEN_VERWALTEN, 'effect': 'grant', 'abteilung_id': None}])

    inhaber = _payload([_person(1)], {1: eff})['inhaber']

    assert inhaber[Permission.KASSEN_VERWALTEN] == [
        {'user_id': 1, 'scopes': 'global', 'quellen': ['individuell']}]
    assert inhaber[Permission.TICKETS_ACCESS] == [
        {'user_id': 1, 'scopes': 'global', 'quellen': ['Sockel']}]


def test_admins_zaehlen_nicht_als_inhaber():
    """Admins haben alles über die Rolle; sie stünden sonst hinter jedem Recht."""
    eff = compute_effective_permissions(
        [], [{'permission': Permission.KASSEN_VERWALTEN, 'effect': 'grant', 'abteilung_id': None}])

    payload = _payload([_person(1, role='admin')], {1: eff})

    assert payload['inhaber'][Permission.KASSEN_VERWALTEN] == []
    assert payload['personen'][0]['role'] == 'admin'  # die UI nennt sie gesondert


def test_jeder_permission_key_hat_eine_liste():
    """Auch Rechte ohne Inhaber stehen drin – die UI zeigt dort 0 statt nichts."""
    inhaber = _payload([], {})['inhaber']

    assert set(Permission.all()) <= set(inhaber)
