"""Client-IP hinter dem Reverse-Proxy.

Die IP speist Login-Bremse, Magic-Link-Rate-Limit und Zugriffsprotokolle; sie
darf also nicht vom Client selbst bestimmt werden. Proxy-Header werden deshalb
nur ausgewertet, wenn die Verbindung von einem vertrauenswürdigen Proxy kommt
(VTB_TRUSTED_PROXIES). Wer direkt am Backend-Port anklopft, bekommt seine
Socket-IP, egal welche Header er mitschickt.
"""
import ipaddress

from fastapi import Request

from .config import settings


def _netze(eintraege: list[str]) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    return [ipaddress.ip_network(e, strict=False) for e in eintraege]


def _vertrauenswuerdig(peer: str | None, netze) -> bool:
    # Leere Liste = jedem Absender trauen (Stand vor VTB_TRUSTED_PROXIES; ohne
    # Konfiguration soll kein Deploy plötzlich nur noch die Proxy-IP loggen).
    if not netze:
        return True
    if not peer:
        return False
    try:
        adresse = ipaddress.ip_address(peer)
    except ValueError:
        return False
    return any(adresse in netz for netz in netze)


def client_ip(request: Request, trusted_proxies: list[str] | None = None) -> str | None:
    """Client-IP der Anfrage.

    Nginx Proxy Manager überschreibt X-Real-IP immer mit $remote_addr; das ist
    die erste Wahl. X-Forwarded-For kann der Client vorbelegen, der Proxy hängt
    die echte IP nur hinten an — als Fallback zählt daher der LETZTE Eintrag,
    nie der erste.
    """
    if trusted_proxies is None:
        trusted_proxies = settings.TRUSTED_PROXIES
    peer = request.client.host if request.client else None
    if not _vertrauenswuerdig(peer, _netze(trusted_proxies)):
        return peer
    real_ip = (request.headers.get("x-real-ip") or "").strip()
    if real_ip:
        return real_ip
    fwd = [t.strip() for t in (request.headers.get("x-forwarded-for") or "").split(",")]
    fwd = [t for t in fwd if t]
    if fwd:
        return fwd[-1]
    return peer
