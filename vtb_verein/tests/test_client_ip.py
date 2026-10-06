"""Client-IP hinter dem Reverse-Proxy (backend/core/client_ip.py).

Die IP steuert Login-Bremse, Magic-Link-Rate-Limit und Zugriffsprotokolle. Der
Client darf sie also nicht selbst bestimmen: weder über einen vorbelegten
X-Forwarded-For noch, wenn er den Proxy umgeht und direkt am Backend-Port anklopft.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.core.client_ip import client_ip  # noqa: E402

PROXY = '192.168.1.10'


def _request(peer=PROXY, **headers):
    return SimpleNamespace(
        headers={k.replace('_', '-'): v for k, v in headers.items()},
        client=SimpleNamespace(host=peer) if peer else None,
    )


def test_x_real_ip_gewinnt():
    req = _request(x_real_ip='203.0.113.7', x_forwarded_for='1.2.3.4, 203.0.113.7')
    assert client_ip(req, [PROXY]) == '203.0.113.7'


def test_vorbelegtes_xff_zaehlt_nicht():
    """Der Client schickt „1.2.3.4" mit, der Proxy hängt die echte IP an."""
    req = _request(x_forwarded_for='1.2.3.4, 203.0.113.7')
    assert client_ip(req, [PROXY]) == '203.0.113.7'


def test_ohne_header_socket_ip():
    assert client_ip(_request(), [PROXY]) == PROXY


def test_direkt_am_port_header_ignoriert():
    """Wer den Proxy umgeht, kann keine IP vortäuschen."""
    req = _request(peer='192.168.1.55', x_real_ip='1.2.3.4', x_forwarded_for='1.2.3.4')
    assert client_ip(req, [PROXY]) == '192.168.1.55'


def test_proxy_als_cidr():
    req = _request(peer='172.18.0.3', x_real_ip='203.0.113.7')
    assert client_ip(req, ['172.16.0.0/12']) == '203.0.113.7'


def test_ohne_konfiguration_wird_header_geglaubt():
    """Leere Liste = Stand vor VTB_TRUSTED_PROXIES, damit kein Deploy bricht."""
    req = _request(peer='192.168.1.55', x_real_ip='203.0.113.7')
    assert client_ip(req, []) == '203.0.113.7'


def test_ohne_socket_und_ohne_header():
    assert client_ip(_request(peer=None), []) is None
