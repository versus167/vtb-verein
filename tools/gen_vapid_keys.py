#!/usr/bin/env python3
"""Erzeugt ein VAPID-Schlüsselpaar für Web-Push (#96) und gibt es als Env-Zeilen aus.

Verwendung:
    ./venv/bin/python tools/gen_vapid_keys.py

Die Ausgabe (VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY) in die .env übernehmen. Der
öffentliche Key (uncompressed EC point, base64url) ist zugleich der
applicationServerKey, den das Frontend beim Subscriben verwendet.
"""
import base64

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid02


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def main() -> None:
    v = Vapid02()
    v.generate_keys()

    public_point = v.public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    private_scalar = v.private_key.private_numbers().private_value.to_bytes(32, "big")

    print("# VAPID-Schlüsselpaar (in .env übernehmen):")
    print("VAPID_PUBLIC_KEY=" + _b64url(public_point))
    print("VAPID_PRIVATE_KEY=" + _b64url(private_scalar))


if __name__ == "__main__":
    main()
