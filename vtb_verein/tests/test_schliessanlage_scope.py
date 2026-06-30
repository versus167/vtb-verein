"""
Tests für das Abteilungs-Scoping der Schließanlage (Phase 3).

Geprüft:
- darf_schloss: vereinsweite Schlösser (abteilung_id IS NULL) verlangen das vereinsweite
  Recht; abteilungsgebundene Schlösser erfüllt das Recht global ODER für genau die Abteilung.
- visible_schloss_ids: None bei vereinsweitem Recht, leere Menge bei keinem Scope,
  sonst genau die Schlösser der erlaubten Abteilungen (SQL gegen ein Fake-DB-Cursor).
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.core.scope import darf_schloss, visible_schloss_ids  # noqa: E402
from app.models.permission import Permission  # noqa: E402

READ = Permission.SCHLIESSANLAGE_READ


class FakeUser:
    """Minimaler User-Stub mit den drei für das Scoping relevanten Methoden."""
    def __init__(self, *, global_perms=(), scoped=None):
        self._global = set(global_perms)
        self._scoped = scoped or {}      # perm -> set(abteilung_ids)

    def has_permission_global(self, perm):
        return perm in self._global

    def has_permission_for_abteilung(self, perm, abteilung_id):
        return perm in self._global or abteilung_id in self._scoped.get(perm, set())

    def allowed_abteilungen(self, perm):
        if perm in self._global:
            return None
        return set(self._scoped.get(perm, set()))


class FakeSchloss:
    def __init__(self, abteilung_id):
        self.abteilung_id = abteilung_id


# --- darf_schloss -----------------------------------------------------------
def test_darf_schloss_vereinsweit_braucht_globales_recht():
    s = FakeSchloss(abteilung_id=None)
    assert darf_schloss(FakeUser(global_perms={READ}), s, READ) is True
    # nur abteilungsgebunden → kein Zugriff auf ein vereinsweites Schloss
    assert darf_schloss(FakeUser(scoped={READ: {3}}), s, READ) is False


def test_darf_schloss_abteilung_global_oder_passende_abteilung():
    s = FakeSchloss(abteilung_id=3)
    assert darf_schloss(FakeUser(global_perms={READ}), s, READ) is True        # global
    assert darf_schloss(FakeUser(scoped={READ: {3}}), s, READ) is True         # passende Abt.
    assert darf_schloss(FakeUser(scoped={READ: {9}}), s, READ) is False        # andere Abt.
    assert darf_schloss(FakeUser(), s, READ) is False                          # kein Recht


def test_darf_schloss_none_schloss_ist_false():
    assert darf_schloss(FakeUser(global_perms={READ}), None, READ) is False


# --- visible_schloss_ids ----------------------------------------------------
class FakeCursor:
    def __init__(self, rows):
        self._rows, self.executed = rows, None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.executed = (sql, params)

    def fetchall(self):
        return self._rows


class FakeConn:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self):
        return FakeCursor(self._rows)


class FakeDB:
    def __init__(self, rows):
        self.conn = FakeConn(rows)


def test_visible_schloss_ids_global_ist_none():
    user = FakeUser(global_perms={READ})
    assert visible_schloss_ids(user, FakeDB([]), READ) is None


def test_visible_schloss_ids_ohne_scope_ist_leer():
    user = FakeUser()  # weder global noch scoped
    assert visible_schloss_ids(user, FakeDB([]), READ) == set()


def test_visible_schloss_ids_scoped_liefert_schloss_ids_der_abteilungen():
    user = FakeUser(scoped={READ: {3, 7}})
    db = FakeDB([{"id": 11}, {"id": 12}])
    assert visible_schloss_ids(user, db, READ) == {11, 12}
