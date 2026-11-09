"""ReFreezer for Windows: Deezer library browser/manager over the ARL cookie,
ported from refreezer (Flutter) to Python + Tk."""

from .downloader import DownloadError, Downloader

__version__ = "0.1.0"
__all__ = ["Downloader", "DownloadError", "__version__"]
