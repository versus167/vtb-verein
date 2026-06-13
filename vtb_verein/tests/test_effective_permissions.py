"""
Tests für die effektive Berechtigungs-Berechnung (Funktions-Berechtigungen, Stufe A).

Formel (siehe BERECHTIGUNGEN.md):
    effektiv = (Sockel ∪ Funktionsrechte ∪ individuelle Grants) − individuelle Denies

Getestet wird die pure Mengenlogik compute_effective_permissions sowie die
has_permission-Varianten am User-Modell – ohne Datenbank.
"""
from app.models.permission import (
    Permission,
    BASE_PERMISSIONS,
    EffectivePermissions,
    compute_effective_permissions,
)
from app.models.user import User


def _funktion(perm, abteilung_id=None, funktion_name='Übungsleiter', abteilung_name=None):
    return {
        'permission': perm,
        'abteilung_id': abteilung_id,
        'funktion_name': funktion_name,
        'abteilung_name': abteilung_name,
    }


def _override(perm, effect='grant', abteilung_id=None):
    return {'permission': perm, 'effect': effect, 'abteilung_id': abteilung_id}


def _user(effective: EffectivePermissions, role='mitglied') -> User:
    u = User(
        id=1, username='t', email='t@t', password_hash='x', role=role,
        active=True, last_login=None, version=1,
        created_at='', created_by='', updated_at='', updated_by='',
    )
    u.effective = effective
    u.permissions = effective.keys()
    return u


class TestSockel:
    def test_sockel_ohne_alles(self):
        eff = compute_effective_permissions([], [])
        assert eff.global_perms == set(BASE_PERMISSIONS)
        assert eff.scoped == {}
        assert Permission.TICKETS_ACCESS in eff.keys()

    def test_sockel_herkunft(self):
        eff = compute_effective_permissions([], [])
        assert {'typ': 'sockel'} in eff.sources[Permission.TICKETS_ACCESS]

    def test_deny_schlaegt_sockel(self):
        eff = compute_effective_permissions(
            [], [_override(Permission.TICKETS_ACCESS, effect='deny')]
        )
        assert Permission.TICKETS_ACCESS not in eff.keys()


class TestFunktionsRechte:
    def test_vereinsweite_funktion_wirkt_global(self):
        eff = compute_effective_permissions(
            [_funktion(Permission.PERSONEN_READ, abteilung_id=None)], []
        )
        assert Permission.PERSONEN_READ in eff.global_perms

    def test_abteilungsgebundene_funktion_wirkt_scoped(self):
        eff = compute_effective_permissions(
            [_funktion(Permission.PERSONEN_READ, abteilung_id=3)], []
        )
        assert Permission.PERSONEN_READ not in eff.global_perms
        assert eff.scoped[Permission.PERSONEN_READ] == {3}
        # lenient: Key zählt trotzdem als vorhanden
        assert Permission.PERSONEN_READ in eff.keys()

    def test_kumulierung_mehrerer_funktionen(self):
        """Positive Kumulierung: Union über alle Funktionen."""
        eff = compute_effective_permissions(
            [
                _funktion(Permission.PERSONEN_READ, abteilung_id=3, funktion_name='Abteilungsleiter'),
                _funktion(Permission.PERSONEN_READ, abteilung_id=7, funktion_name='Abteilungsleiter'),
                _funktion(Permission.BEITRAEGE_READ, abteilung_id=None, funktion_name='Kassenwart'),
            ],
            [],
        )
        assert eff.scoped[Permission.PERSONEN_READ] == {3, 7}
        assert Permission.BEITRAEGE_READ in eff.global_perms

    def test_herkunft_mit_abteilung(self):
        eff = compute_effective_permissions(
            [_funktion(Permission.PERSONEN_READ, abteilung_id=3,
                       funktion_name='Abteilungsleiter', abteilung_name='Fußball')],
            [],
        )
        quellen = eff.sources[Permission.PERSONEN_READ]
        assert any(
            q['typ'] == 'funktion' and q['funktion_name'] == 'Abteilungsleiter'
            and q['abteilung_name'] == 'Fußball'
            for q in quellen
        )


class TestOverrides:
    def test_grant_wirkt_global(self):
        eff = compute_effective_permissions([], [_override(Permission.BERICHTE_READ)])
        assert Permission.BERICHTE_READ in eff.global_perms

    def test_deny_entfernt_geerbtes_recht(self):
        eff = compute_effective_permissions(
            [_funktion(Permission.PERSONEN_READ)],
            [_override(Permission.PERSONEN_READ, effect='deny')],
        )
        assert Permission.PERSONEN_READ not in eff.keys()

    def test_deny_entfernt_auch_scoped(self):
        """Totales Deny räumt global UND alle Abteilungs-Scopes ab."""
        eff = compute_effective_permissions(
            [
                _funktion(Permission.PERSONEN_READ, abteilung_id=3),
                _funktion(Permission.PERSONEN_READ, abteilung_id=None),
            ],
            [_override(Permission.PERSONEN_READ, effect='deny')],
        )
        assert Permission.PERSONEN_READ not in eff.keys()

    def test_deny_schlaegt_grant(self):
        """Deny gewinnt auch gegen einen gleichzeitigen Grant (Reihenfolge egal)."""
        eff = compute_effective_permissions(
            [],
            [
                _override(Permission.PERSONEN_READ, effect='deny'),
                _override(Permission.PERSONEN_READ, effect='grant'),
            ],
        )
        assert Permission.PERSONEN_READ not in eff.keys()

    def test_scoped_deny_entfernt_nur_den_scope(self):
        eff = compute_effective_permissions(
            [
                _funktion(Permission.PERSONEN_READ, abteilung_id=3),
                _funktion(Permission.PERSONEN_READ, abteilung_id=7),
            ],
            [_override(Permission.PERSONEN_READ, effect='deny', abteilung_id=3)],
        )
        assert eff.scoped[Permission.PERSONEN_READ] == {7}

    def test_sticky_deny_ohne_geerbtes_recht_bleibt_sichtbar(self):
        """Deny ohne aktuelles Erbe: wirkt nicht, bleibt aber in sources (Stickyness)."""
        eff = compute_effective_permissions(
            [], [_override(Permission.PERSONEN_WRITE, effect='deny')]
        )
        assert Permission.PERSONEN_WRITE not in eff.keys()
        assert any(
            q['typ'] == 'override' and q['effect'] == 'deny'
            for q in eff.sources[Permission.PERSONEN_WRITE]
        )


class TestUserModell:
    def test_admin_hat_alles(self):
        u = _user(compute_effective_permissions([], []), role='admin')
        assert u.has_permission(Permission.SYSTEM_CONFIG)
        assert u.has_permission_global(Permission.SYSTEM_CONFIG)
        assert u.has_permission_for_abteilung(Permission.SYSTEM_CONFIG, 99)

    def test_lenient_scoped_erfuellt_has_permission(self):
        u = _user(compute_effective_permissions(
            [_funktion(Permission.PERSONEN_READ, abteilung_id=3)], []
        ))
        assert u.has_permission(Permission.PERSONEN_READ)
        assert not u.has_permission_global(Permission.PERSONEN_READ)

    def test_scoped_abteilungs_pruefung(self):
        u = _user(compute_effective_permissions(
            [_funktion(Permission.PERSONEN_READ, abteilung_id=3)], []
        ))
        assert u.has_permission_for_abteilung(Permission.PERSONEN_READ, 3)
        assert not u.has_permission_for_abteilung(Permission.PERSONEN_READ, 7)
        assert u.allowed_abteilungen(Permission.PERSONEN_READ) == {3}

    def test_global_recht_bedeutet_alle_abteilungen(self):
        u = _user(compute_effective_permissions(
            [_funktion(Permission.PERSONEN_READ, abteilung_id=None)], []
        ))
        assert u.allowed_abteilungen(Permission.PERSONEN_READ) is None
        assert u.has_permission_for_abteilung(Permission.PERSONEN_READ, 42)

    def test_kein_recht_leere_abteilungsmenge(self):
        u = _user(compute_effective_permissions([], []))
        assert u.allowed_abteilungen(Permission.PERSONEN_READ) == set()
