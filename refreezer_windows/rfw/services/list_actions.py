"""Play/open actions on what the track list shows and has selected. Tk-free.

``selected()`` returns the selected items (the track list view supplies it).
"""

from ..deezer.api import Playlist, Track
from ..win.desktop import open_in_deezer


class ListActions:
    def __init__(self, tracklist, selected, playback, browser, open_url=open_in_deezer):
        self.tracklist, self._selected = tracklist, selected
        self.playback, self.browser, self._open_url = playback, browser, open_url

    def selected_tracks(self):
        return [it for it in self._selected() if isinstance(it, Track)]

    def activate(self):
        """Double-click / Enter: preview a track, open anything else."""
        sel = self._selected()
        if not sel:
            return
        if isinstance(sel[0], Track):
            self.preview(sel[0])
        else:
            self.browser.open_item(sel[0])

    def preview(self, track):
        self.playback.play(track)

    def play_selected(self):
        """▶ Preview: 30 s preview of the first selected track."""
        tracks = self.selected_tracks()
        if tracks:
            self.preview(tracks[0])

    def play_selected_full(self):
        """▶ Play: stream the selected playlist, or the list from the selected track, or all of it."""
        sel = self._selected()
        if sel and isinstance(sel[0], Playlist):
            self.play_playlist(sel[0])
        elif sel and isinstance(sel[0], Track):
            self.play_from(sel[0])
        elif self.tracklist.kind == "tracks":
            self.playback.play_queue(self.tracklist.items)

    def play_from(self, track, shuffle=None):
        """Stream the shown track list, starting at ``track``."""
        self.playback.play_list_from(self.tracklist.items, track, shuffle)

    def play_playlist(self, playlist, shuffle=False):
        """Stream a playlist, reusing its tracks when they are already shown."""
        self.playback.play_playlist(playlist, shuffle, loaded=self.tracklist.tracks_of(playlist))

    def play_playlist_mix(self, playlist):
        """Endless recommendations seeded by the playlist's songs."""
        self.playback.play_playlist_mix(playlist, loaded=self.tracklist.tracks_of(playlist))

    def open_selected(self):
        sel = self._selected()
        if sel:
            self._open_url(sel[0].url)
