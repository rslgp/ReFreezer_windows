"""Where the ARL comes from. Never from a command-line argument (it would land in
shell history and the process list)."""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ARL_FILE = PROJECT_ROOT / "arl.txt"
ENV_VAR = "DEEZER_ARL"


def read_arl_file(path):
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except OSError:
        return None
    # Accept a bare value or a line like "arl=...", ignore comments
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("arl="):
            line = line[4:]
        return line.strip().strip('"') or None
    return None


def find_arl(arl_file=None):
    """ARL from DEEZER_ARL, then the given file, then arl.txt in the project root."""
    value = os.environ.get(ENV_VAR, "").strip()
    if value:
        return value
    return read_arl_file(arl_file or DEFAULT_ARL_FILE)


def save_arl(arl, path=DEFAULT_ARL_FILE):
    Path(path).write_text(arl.strip() + "\n", encoding="utf-8")
