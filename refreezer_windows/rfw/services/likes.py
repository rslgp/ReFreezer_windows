"""Like / dislike the playing song (player bar buttons and global hotkeys). Tk-free."""


class LikeService:
    def __init__(self, session, tasks, ui, playback, tracklist):
        self.session, self.tasks, self.ui = session, tasks, ui
        self.playback, self.tracklist = playback, tracklist

    def current_liked(self):
        """Whether the playing song is in Favorites (the poll loop mirrors it on the Like button)."""
        track = self.playback.current_track()
        return track is not None and track.id in self.session.favorite_ids

    def like_current(self):
        """Add the playing song to Favorites."""
        track = self.playback.current_track()
        if track is None or self.session.api is None:
            self.ui.notify("Nothing is playing")
            return
        label = f"{track.artist} - {track.title}"
        if track.id in self.session.favorite_ids:
            self.ui.notify(f"♥ Already in favorites: {label}")
            return
        api = self.session.api

        def done(_):
            self.session.favorite_ids.add(track.id)
            self.tracklist.changed()
            self.ui.notify(f"♥ Liked: {label}")

        self.tasks.run(lambda: api.add_favorites([track.id]), done, "Saving...")

    def dislike_current(self):
        """Mark the playing song as disliked and skip it."""
        track = self.playback.current_track()
        if track is None or self.session.api is None:
            self.ui.notify("Nothing is playing")
            return
        api = self.session.api

        def done(_):
            self.ui.notify(f"👎 Disliked: {track.artist} - {track.title}")
            self.playback.skip_if_current(track)

        self.tasks.run(lambda: api.dislike(track.id), done, "Saving...")
