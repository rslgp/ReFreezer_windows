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
  seed and press Enter to replay the same order).
- **🌊 Flow** (menu: Flow, Motivation, Party, Chill, Melancholy, You & me, Focus) streams your
  Deezer Flow like refreezer's `playFromSmartTrackList`, and keeps refilling with the same variant. **♥ Like** / **👎 Dislike** act on the
  playing song (dislike also skips it).
- **Settings > Global hotkeys**: like/dislike the playing song while the window is unfocused or
  minimized (default `ctrl+alt+L` / `ctrl+alt+D`). Saved in `%APPDATA%\refreezer_windows\settings.json`.

## Run

Double-click `run_gui.bat`, or from PowerShell in this folder:

```powershell
python -m rfw
```

Treat the ARL like a password. If it leaks, log out of Deezer on all devices to rotate it.

## Tests

```powershell
python -m unittest discover -s tests -t .
```
