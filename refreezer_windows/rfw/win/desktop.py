"""Hand-offs to the Windows shell: the Deezer app, the browser, Explorer."""

import os
import webbrowser
from pathlib import Path


def open_in_deezer(url):
    """Desktop app via the deezer:// protocol when installed, else the browser."""
    try:
        os.startfile(url.replace("https://", "deezer://"))
    except OSError:
        webbrowser.open(url)


def open_folder(folder):
    """Create ``folder`` if needed and show it in Explorer; raises on failure."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    os.startfile(folder)
