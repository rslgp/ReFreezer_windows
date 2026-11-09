"""What the right-hand list shows, without Tk: kind, items, title and where they came from."""

from ..deezer.api import Album, Artist, Track

HEART = "♥"

# Column headings per list kind: (col1, col2, col3, col4)
HEADINGS = {
    "tracks": ("Title", "Artist", "Album", "Time"),
    "albums": ("Album", "Artist", "Tracks", ""),
    "artists": ("Artist", "Fans", "", ""),
    "playlists": ("Playlist", "Owner", "Tracks", ""),
}


def fmt_duration(seconds):
    return f"{seconds // 60}:{seconds % 60:02d}" if seconds else ""


class TrackList:
    def __init__(self, session):
        self.session = session
        # kind in HEADINGS; source is ("none",), ("favorites",), ("search",) or (kind, item)
        self.kind, self.title, self.items, self.source = "tracks", "", [], ("none",)
        self._on_shown, self._on_changed = [], []

    def subscribe(self, on_shown, on_changed):
        """``on_shown()`` after ``show`` (new list); ``on_changed()`` when rows need a redraw."""
        self._on_shown.append(on_shown)
        self._on_changed.append(on_changed)

    def show(self, kind, title, items, source=("none",)):
        self.kind, self.title, self.items, self.source = kind, title, list(items), source
        for fn in self._on_shown:
            fn()

    def changed(self):
        """Favorites (or the items) changed: redraw the rows."""
        for fn in self._on_changed:
            fn()

    def drop_ids(self, ids):
        """Remove tracks with these ids (removed from favorites / from the shown playlist)."""
        self.items = [t for t in self.items if t.id not in ids]
        self.changed()

    def row(self, it):
        if isinstance(it, Track):
            fav = HEART if it.id in self.session.favorite_ids else ""
            title = f"{it.title}  [E]" if it.explicit else it.title
            return (fav, title, it.artist, it.album, fmt_duration(it.duration))
        if isinstance(it, Album):
            return ("", it.title, it.artist, it.tracks or "", "")
        if isinstance(it, Artist):
            return ("", it.name, f"{it.fans:,}" if it.fans else "", "", "")
        return ("", it.title, it.owner, it.tracks or "", "")

    def rows(self, needle=""):
        """(index, row) of the items whose title/artist/album contain ``needle``."""
        needle = needle.strip().casefold()
        for i, it in enumerate(self.items):
            row = self.row(it)
            if needle and not any(needle in str(v).casefold() for v in row[1:4]):
                continue
            yield i, row

    def tracks(self):
        return [t for t in self.items if isinstance(t, Track)]

    def tracks_of(self, playlist):
        """The shown items when they are this playlist's tracks, else None (load them)."""
        if self.source[0] == "playlist" and self.source[1].id == playlist.id:
            return self.items
        return None
