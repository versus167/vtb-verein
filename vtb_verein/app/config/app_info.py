import os
import subprocess
from pathlib import Path

APP_NAME = 'Vereinsverwaltung'
DEFAULT_VERSION = '0.0.1'


def get_app_version() -> str:
    """Liefert die aktuelle Anwendungs-Version.

    Reihenfolge:
    1. ENV-VARIABLE VTB_APP_VERSION
    2. VERSION-Datei im Repo-Root
    3. git describe --tags --always --dirty
    4. DEFAULT_VERSION
    """
    env_version = os.getenv('VTB_APP_VERSION')
    if env_version:
        return env_version.strip()

    repo_root = Path(__file__).resolve().parents[3]
    version_file = repo_root / 'VERSION'
    if version_file.exists():
        try:
            return version_file.read_text(encoding='utf-8').strip()
        except OSError:
            pass

    try:
        version = subprocess.check_output(
            ['git', 'describe', '--tags', '--always', '--dirty'],
            cwd=repo_root,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        ).strip()
        if version:
            return version
    except Exception:
        pass

    return DEFAULT_VERSION
