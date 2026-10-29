#!/usr/bin/env bash
# Python-Abhängigkeiten auf feste Versionen sperren (requirements.lock /
# requirements-dev.lock im Repo-Root).
#
# Eingaben sind die bisherigen requirements.txt mit ihren Untergrenzen – dort
# trägt man neue direkte Abhängigkeiten ein. Die Locks halten den *ganzen* Baum
# mit Version und Hash fest; Image (backend/Dockerfile) und venv installieren
# ausschließlich daraus. Damit läuft in Produktion genau das, wogegen getestet
# wurde, und ein Bau ohne Docker-Cache zieht nicht still neue Major-Stände.
#
#   tools/abhaengigkeiten_sperren.sh            # bestehende Pins behalten, nur Neues auflösen
#   tools/abhaengigkeiten_sperren.sh --upgrade  # alles auf den neuesten erlaubten Stand
#
# Danach das venv angleichen und testen:
#   uv pip sync --python venv/bin/python requirements-dev.lock
#   ./venv/bin/python -m pytest vtb_verein/tests/ -q
#
# Braucht uv (https://docs.astral.sh/uv/) nur lokal; im Image genügt pip.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

# Python-Version des Images (backend/Dockerfile: python:3.12-slim) – nicht die
# des lokalen Interpreters, sonst passen Marker und Wheels nicht.
PY=3.12

uv pip compile "$@" --python-version "$PY" --generate-hashes --quiet \
    --custom-compile-command "tools/abhaengigkeiten_sperren.sh" \
    vtb_verein/requirements.txt backend/requirements.txt \
    -o requirements.lock

# Dev-Lock mit dem Prod-Lock als Constraint: Was in beiden vorkommt, hat in den
# Tests dieselbe Version wie im Image.
uv pip compile "$@" --python-version "$PY" --generate-hashes --quiet \
    --custom-compile-command "tools/abhaengigkeiten_sperren.sh" \
    vtb_verein/requirements_dev.txt backend/requirements.txt \
    -c requirements.lock \
    -o requirements-dev.lock
