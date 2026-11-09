# ReFreezer for Windows

Windows desktop GUI (Python 3 + Tk, standard library only) for your Deezer account over the
`arl` cookie. Ported from refreezer `lib/api/deezer.dart`; the ARL client and the genre
playlist maker are reused from `..\genre_playlist_maker_lastfm` (vendored as `gpm`).

## Features

- Login with ARL (masked; optional *Remember* writes git-ignored `arl.txt`).
- Library tree: Favorites, Playlists (own + followed), Albums, Artists.
- Search: tracks, albums, artists, playlists.
- Track lists with favorite marks, explicit flag, duration and a live filter box.
- Right-click on tracks (multi-select with Ctrl/Shift): play preview, open in Deezer, copy link,
  add/remove favorites, add to a playlist (or a new one), remove from your own playlist.
- Right-click on playlists/albums/artists: open, add to / remove from library, follow/unfollow,
  delete your own playlist (asks first).
- Right-click on a playlist > **Download** (MP3 320 / MP3 128 / FLAC, falls back to the best
  quality the account allows): asks for a folder, saves `<folder>\<playlist>\NN - Artist - Title`
  with ID3 tags, cover and synced `.lrc` lyrics. One download at a time; the same menu then
  offers *Cancel download*. Uses the ARL you logged in with (`arl.txt` / `DEEZER_ARL`).
- **Tools > Genre playlist maker**: the Last.fm/Deezer genre tool, ARL pre-filled.
- Player: the official **30 s previews**, played through Windows MCI (`winmm.dll`).
  *Open in Deezer* hands full playback to the Deezer desktop app (`deezer://`), or the browser.

- **Full-track playback**: right-click a playlist (or Favorites) > *Play* / *Play shuffled*, or a
  track > *Play from here*. Each track is fetched whole (MP3 128) into a temp cache and played;
  the next one is prefetched. Player bar: ⏮ ⏯ ⏭, Shuffle, **🎲 Reroll** (new shuffle seed; type a
  seed and press Enter to replay the same order). Global player keys (see Settings below):
  **ctrl+alt+← previous, ctrl+alt+↓ pause/resume, ctrl+alt+→ next**.
- **Seek bar** under the player buttons: elapsed / total time; click or drag anywhere on it to jump
  in the playing song (a paused song stays paused).
- **Queue kept between runs**: the play queue (order, shuffle seed, the song and the time in it,
  and the Flow / mix it refills from) is saved to `%APPDATA%\refreezer_windows\queue.json` while
  you listen. After you log in again with the same account it comes back paused; press ⏯ (or the
  pause hotkey) to continue where you left. *Stop* clears it.
- **Settings > Mix**: seed songs per refill, recommendations kept per seed song, refill threshold
  (Flow too), seed order (Seed box or playlist order), leave out the playlist's own songs, and
  alternate between seeds or group each seed's songs.
- **🌊 Flow** (menu: Flow, Motivation, Party, Chill, Melancholy, You & me, Focus) streams your
  Deezer Flow like refreezer's `playFromSmartTrackList`, and keeps refilling with the same variant. **♥ Like** / **👎 Dislike** act on the
  playing song (dislike also skips it).
- **Settings > Global hotkeys**: work while the window is unfocused or minimized. Like / dislike the
  playing song (default `ctrl+alt+L` / `ctrl+alt+D`) and previous / pause / next (default
  `ctrl+alt+left` / `ctrl+alt+down` / `ctrl+alt+right`). Each key needs a modifier, because a global
  key is taken from every program; keyboard media keys work alone (`mediaprev`, `mediaplaypause`,
  `medianext`). Saved in `%APPDATA%\refreezer_windows\settings.json`.

## Run

Double-click `run_gui.bat`, or from PowerShell in this folder:

```powershell
python -m rfw
```

Treat the ARL like a password. If it leaks, log out of Deezer on all devices to rotate it.

## Code layout

```
refreezer_windows/
├─ run_gui.bat            double-click launcher (pythonw -m rfw)
├─ rfw/                   the app
│  ├─ app.py              composition root: builds and wires everything, 150 ms poll, main()
│  ├─ deezer/             Deezer: api.py (models, Library: gw/public calls), blowfish(_tables).py
│  ├─ core/               pure state: playqueue, tracklist, session, tasks (pool + Tk-thread queue),
│  │                      mix (playlist mix + its settings), queue_store (queue.json)
│  ├─ media/              audio: downloader (get_url, decrypt, parallel playlist), tagger,
│  │                      stream_cache (full-track cache), player (MCI)
│  ├─ win/                Windows glue: hotkeys (RegisterHotKey, settings, single instance), desktop
│  ├─ services/           Tk-free controllers: account, browse, playback (queue, Flow), likes,
│  │                      downloads, list_actions, hotkey_settings, mix_settings, queue_persist
│  └─ ui/                 Tk views: top_bar, nav_view, track_view, menus, player_bar, tk_ui (toast),
│                         hotkey_dialog, mix_dialog, download_dialogs, queue_view, panels
├─ gpm/                   vendored ARL client + genre playlist maker (Tools menu)
└─ tests/
   ├─ rfw/                app tests, incl. test_layers.py (layer rule below)
   └─ gpm/                genre playlist maker tests
```

Layers import only downwards, enforced by `tests/rfw/test_layers.py`:
`deezer`, `win` (no rfw imports) < `core`, `media` (use `deezer`) < `services` < `ui` < `app.py`.
Only `ui/` and `app.py` import Tk; everything else is unit-tested with fakes.

## Tests

```powershell
python -m unittest discover -s tests -t .
```
