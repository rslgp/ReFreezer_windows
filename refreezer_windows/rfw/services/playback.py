"""Player controller: 30 s previews, the full-track stream queue, Flow, playlist mixes and
auto-advance.

Tk-free. Every method runs on the Tk thread (MCI devices belong to the thread that opened
them); network waits go through ``tasks.run``, whose ``on_ok`` comes back on that thread.
``view`` is the player bar: ``set_now(text)``, ``get_shuffle()``/``set_shuffle(on)``,
``get_seed()``/``set_seed(text)``.
"""

from ..core.mix import PlaylistMix
from ..core.playqueue import PlayQueue, new_seed
from ..core.session import need_login
from ..deezer.api import FLOW_TYPES, Track
from ..media.player import PlayerError, PreviewPlayer
from ..media.stream_cache import StreamCache

# Endless queues (Flow, playlist mix) refill when this many tracks or fewer are left
FLOW_REFILL_AT = 2


class PlaybackController:
    def __init__(self, session, tasks, ui, view=None, player=None, stream=None):
        """``view`` may be attached later by the composition root (the bar needs this controller)."""
        self.session, self.tasks, self.ui, self.view = session, tasks, ui, view
        self.player = player or PreviewPlayer()
        self.stream = stream or StreamCache(lambda: session.downloader)
        self.playq = None
        # Bumped whenever the playing track changes: drops late fetch results after a skip
        self._play_gen = 0
        # Endless queue (Flow or playlist mix): flow_mode is on while ``_refill_fn`` (a blocking
        # call returning more tracks) tops the queue up as it runs low
        self.flow_mode = False
        self.flow_type = None
        self._refill_fn = None
        self._endless_name = "Flow"
        self._flow_loading = False

    # ---- preview ------------------------------------------------------------

    def play(self, track):
        """30 s preview of ``track``; ends any stream queue."""
        api, player = self.session.api, self.player
        self._end_queue()

        def work():
            return player.fetch(api.preview_url(track), track.id)

        def done(path):
            try:
                player.play(path, track)
                self.view.set_now(f"♪ {track.artist} - {track.title} (30 s preview)")
                self.ui.status("")
            except PlayerError as e:
                self.ui.error("Playback error", str(e))

        self.tasks.run(work, done, f"Loading preview: {track.title}")

    def stop(self):
        self._end_queue()
        self.player.stop()
        self.view.set_now("")

    def current_track(self):
        """The playing (or buffering) track, None when idle."""
        if self.player.current is not None:
            return self.player.current
        return self.playq.current if self.playq is not None else None

    def skip_if_current(self, track):
        """Move on when ``track`` is still the one playing (after a dislike)."""
        if self.current_track() is track:
            if self.playq is not None:
                self.queue_next()
            else:
                self.stop()

    def tick(self):
        """Poll-loop hook: a finished track advances the stream queue (or clears the line)."""
        if self.player.current is not None and self.player.state() not in ("playing", "paused"):
            self.player.stop()
            if self.playq is not None:
                self.queue_next()
            else:
                self.view.set_now("")

    def toggle_pause(self):
        try:
            state = self.player.state()
            if state == "playing":
                self.player.pause()
            elif state == "paused":
                self.player.resume()
        except PlayerError as e:
            self.ui.status(f"Error: {e}")

    # ---- full-track stream queue -----------------------------------------------

    def _end_queue(self):
        self.playq = None
        self.flow_mode, self._refill_fn = False, None
        self._play_gen += 1

    def _seed(self):
        """Seed from the Seed box; a bad value is replaced by a fresh one."""
        try:
            return int(self.view.get_seed().strip())
        except ValueError:
            seed = new_seed()
            self.view.set_seed(str(seed))
            return seed

    def play_queue(self, tracks, start=None, shuffle=None):
        """Stream ``tracks`` in full; ``start`` is the track index to play first."""
        tracks = [t for t in tracks if isinstance(t, Track)]
        if need_login(self.session, self.ui) or not tracks:
            return
        if shuffle is not None:
            self.view.set_shuffle(shuffle)
        self.flow_mode, self._refill_fn = False, None
        self.playq = PlayQueue(tracks, start, shuffle=self.view.get_shuffle(), seed=self._seed())
        self._stream_current()

    def play_playlist(self, playlist, shuffle=False, loaded=None):
        """Stream a playlist; ``loaded`` is its track list when already on screen."""
        if need_login(self.session, self.ui):
            return
        if loaded is not None:
            self.play_queue(loaded, shuffle=shuffle)
            return
        api = self.session.api
        self.tasks.run(lambda: api.playlist_tracks(playlist.id, self.tasks.progress),
                       lambda tracks: self.play_queue(tracks, shuffle=shuffle), f"Loading {playlist.title}...")

    def play_list_from(self, tracks, track, shuffle=None):
        """Stream ``tracks`` (the shown list), starting at ``track``."""
        tracks = [t for t in tracks if isinstance(t, Track)]
        self.play_queue(tracks, tracks.index(track) if track in tracks else None, shuffle)

    def _now_label(self, track, icon="♪"):
        return f"{icon} {track.artist} - {track.title}  [{self.playq.position_label()}]"

    def _stream_current(self):
        pq = self.playq
        track = pq.current
        self._play_gen += 1
        gen = self._play_gen
        self.player.stop()
        self.view.set_now(self._now_label(track, "⏳"))
        fut = self.stream.fetch(track)

        def work():
            try:
                return fut.result()
            except Exception as e:  # skip this track instead of stopping the queue
                return e

        def done(res):
            if gen != self._play_gen or self.playq is not pq:
                return  # user moved on while this was buffering
            if isinstance(res, Exception):
                self.ui.status(f"Skipped {track.title}: {res}")
                self.queue_next()
                return
            try:
                self.player.play(res, track)
            except PlayerError as e:
                self.ui.status(f"Skipped {track.title}: {e}")
                self.queue_next()
                return
            self.view.set_now(self._now_label(track))
            self.ui.status("")
            self._after_reorder()

        self.tasks.run(work, done, f"Buffering: {track.title}")

    def _after_reorder(self):
        """Prefetch the next track and free the cache of the rest."""
        nxt = self.playq.peek_next()
        if nxt is not None:
            self.stream.fetch(nxt)
        self.stream.prune({self.playq.current.id, nxt.id if nxt else None})
        self._flow_refill()

    def queue_next(self):
        if self.playq is not None and self.playq.next() is not None:
            self._stream_current()
        elif self.flow_mode and self.playq is not None:
            self._flow_refill(then=self.queue_next)  # Flow never ends: fetch more, go on
        else:
            self.stop()

    def queue_prev(self):
        if self.playq is not None:
            self.playq.prev()
            self._stream_current()

    # ---- queue panel actions (``order_pos`` as listed by PlayQueue.entries) ----------------

    def jump_to(self, order_pos):
        """Play the queued track at ``order_pos`` now."""
        if self.playq is not None:
            self.playq.jump(order_pos)
            self._stream_current()

    def play_next(self, order_pos):
        """Queue the track at ``order_pos`` right after the playing one."""
        if self.playq is not None:
            self.playq.play_next(order_pos)
            self._after_reorder()

    def remove_from_queue(self, order_pos):
        """Drop a queued track; removing the playing one skips to the next first."""
        pq = self.playq
        if pq is None:
            return
        if order_pos != pq.pos:
            if pq.remove(order_pos):
                self._after_reorder()
            return
        if pq.peek_next() is None:
            self.stop()
            return
        pq.next()
        pq.remove(order_pos)
        self._stream_current()

    # ---- shuffle / seed -----------------------------------------------------------

    def on_shuffle_toggle(self):
        if self.playq is not None:
            self.playq.seed = self._seed()
            self.playq.set_shuffle(self.view.get_shuffle())
            self._reordered()

    def reroll(self):
        """New random seed; turns shuffle on and reshuffles what is left of the queue."""
        self.view.set_seed(str(new_seed()))
        self.apply_seed()

    def apply_seed(self):
        seed = self._seed()
        self.view.set_shuffle(True)
        if self.playq is not None:
            self.playq.reroll(seed)
            self._reordered()
        self.ui.status(f"Shuffle seed {seed}")

    def _reordered(self):
        self.view.set_now(self._now_label(self.playq.current))
        self._after_reorder()

    # ---- Flow / smart track lists ---------------------------------------------------

    def play_flow(self, flow_type=None):
        self.play_from_smart_track_list("flow", flow_type)

    def play_from_smart_track_list(self, stl_id, flow_type=None):
        """Port of refreezer's playFromSmartTrackList: 'flow' streams the user's Flow
        (variant ``flow_type``) and refills itself; any other id plays that smart track list."""
        if need_login(self.session, self.ui):
            return
        api = self.session.api
        is_flow = stl_id == "flow"
        name = next((label for label, t in FLOW_TYPES if t == flow_type), "Flow") if is_flow else "Smart track list"

        def work():
            if is_flow:  # Flow songs cannot be read through the smart track list call
                return name, api.flow(flow_type)
            return api.smart_track_list(stl_id)

        def done(res):
            title, tracks = res
            if not tracks:
                self.ui.status(f"{title} returned no tracks, try again in a moment")
                return
            self.view.set_shuffle(False)
            self.play_queue(tracks, shuffle=False)
            if is_flow:
                self._make_endless(name, lambda: api.flow(flow_type))
            self.flow_type = flow_type
            self.ui.status(f"Playing {title}")

        self.tasks.run(work, done, f"Loading {name}...")

    def play_playlist_mix(self, playlist, loaded=None):
        """Endless recommendation queue seeded by the playlist's songs; the Seed box picks
        which songs seed it. ``loaded`` is the playlist's track list when already on screen."""
        if need_login(self.session, self.ui):
            return
        api, seed = self.session.api, self._seed()
        name = f"Mix: {playlist.title}"

        def work():
            tracks = loaded if loaded is not None else api.playlist_tracks(playlist.id, self.tasks.progress)
            mix = PlaylistMix(tracks, seed)
            return mix, mix.next_batch(api.track_mix)

        def done(res):
            mix, tracks = res
            if not tracks:
                self.ui.status(f"{name}: no recommendations found")
                return
            self.view.set_shuffle(False)
            self.play_queue(tracks, shuffle=False)
            self._make_endless(name, lambda: mix.next_batch(api.track_mix))
            self.ui.status(f"Playing {name} (seed {seed})")

        self.tasks.run(work, done, f"Building {name}...")

    def _make_endless(self, name, refill_fn):
        self.flow_mode, self._refill_fn, self._endless_name = True, refill_fn, name

    def _flow_refill(self, then=None):
        """Append a batch to the endless queue when FLOW_REFILL_AT or fewer tracks are left;
        ``then`` runs if it added any."""
        pq = self.playq
        if not self.flow_mode or pq is None or self._refill_fn is None:
            return
        if then is None and (self._flow_loading or pq.remaining() > FLOW_REFILL_AT):
            return
        self._flow_loading = True
        refill, name = self._refill_fn, self._endless_name

        def work():
            try:
                return refill()
            except Exception:
                return []

        def done(tracks):
            self._flow_loading = False
            if self.playq is not pq:
                return
            before = len(pq.tracks)
            pq.extend(tracks)
            if len(pq.tracks) == before:
                if then is not None:  # nothing new and nothing left: stop, don't loop
                    self.ui.status(f"{name}: no new tracks")
                    self.stop()
                return
            if then is not None:
                then()
            else:
                nxt = pq.peek_next()
                if nxt is not None:
                    self.stream.fetch(nxt)

        self.tasks.run(work, done)

    def shutdown(self):
        """App exit: stop playback, cancel prefetches, delete cached streams."""
        self.stop()
        self.stream.shutdown()
