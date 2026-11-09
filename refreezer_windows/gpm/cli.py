import argparse
import getpass
import sys

from . import core
from .arl import find_arl
from .deezer_client import STATUS_PRIVATE, STATUS_PUBLIC, DeezerClient, DeezerError
from .lastfm import LastfmClient, LastfmError, find_api_key


def _progress(done, total, label):
    print(f"\r{label}: {done}/{total}   ", end="", file=sys.stderr, flush=True)
    if done >= total:
        print(file=sys.stderr)


def _load(args):
    lf = None
    if args.source == "lastfm":
        key = find_api_key(args.lastfm_key_file) or getpass.getpass("Last.fm API key (hidden): ")
        lf = LastfmClient(key)
    arl = find_arl(args.arl_file) or getpass.getpass("Deezer ARL cookie (hidden): ")
    client = DeezerClient(arl, lang=args.lang).login()
    print(f"Logged in as {client.user_name} (id {client.user_id})", file=sys.stderr)
    tracks = core.fetch_favorites(client, progress=_progress)
    genres_by_track, pending = core.build_genre_map(
        client, tracks, source=args.source, lastfm_client=lf, top_n=args.tags,
        min_count=args.min_count, deezer_fallback=not args.no_deezer_fallback,
        progress=_progress, album_cache_path=args.cache, workers=args.workers,
    )
    if pending:
        print(f"Warning: {pending} Last.fm lookups failed; their tracks fall back for now. "
              "Run the same command again to continue (finished lookups are cached).", file=sys.stderr)
    return client, tracks, genres_by_track


def cmd_genres(args):
    _, tracks, genres_by_track = _load(args)
    print(f"{len(tracks)} favorite tracks, genre source: {args.source}")
    for genre, items in core.group_by_genre(tracks, genres_by_track).items():
        print(f"{len(items):6d}  {genre}")


def cmd_tracks(args):
    """Genre per track, tab-separated, for inspection or a spreadsheet."""
    _, tracks, genres_by_track = _load(args)
    print("genres\tartist\ttitle")
    for t in tracks:
        print(f"{' | '.join(core.track_genres(t, genres_by_track))}\t{t.artist}\t{t.title}")


def cmd_create(args):
    client, tracks, genres_by_track = _load(args)
    selected = core.select_tracks(tracks, genres_by_track, args.genre)
    if not selected:
        known = ", ".join(core.group_by_genre(tracks, genres_by_track))
        print(f"No favorites match {args.genre}. Genres found: {known}", file=sys.stderr)
        return 1
    title = args.name or core.default_title(args.genre)
    print(f"{len(selected)} tracks match {args.genre} -> '{title}'")
    if args.dry_run:
        for t in selected:
            print(f"  {t.artist} - {t.title}")
        return 0
    pid = core.create_genre_playlist(
        client, title, selected,
        description=f"Generated from Favorites by genre: {', '.join(args.genre)}",
        status=STATUS_PUBLIC if args.public else STATUS_PRIVATE,
        progress=_progress,
    )
    print(f"Created: {core.playlist_url(pid)}")
    return 0


def cmd_gui(_args):
    from .gui import main
    main()


def build_parser():
    p = argparse.ArgumentParser(prog="gpm", description="Create a Deezer playlist from your Favorites filtered by genre.")
    p.add_argument("--arl-file", help="file holding the ARL cookie (default: arl.txt in project root; env DEEZER_ARL wins)")
    p.add_argument("--lang", default="en", help="language for genre names (default: en)")
    p.add_argument("--cache", help="album-genre cache JSON (default: %%LOCALAPPDATA%%\\genre_playlist_maker\\album_genres.json)")
    p.add_argument("--source", choices=core.SOURCES, default="lastfm",
                   help="genre per track from Last.fm tags (default) or Deezer album genres")
    p.add_argument("--lastfm-key-file", help="file holding the Last.fm API key (default: lastfm_api_key.txt; env LASTFM_API_KEY wins)")
    p.add_argument("--tags", type=int, default=1, help="Last.fm genres kept per track (default: 1 = primary genre only)")
    p.add_argument("--min-count", type=int, default=10, help="ignore Last.fm tags weighted below this (0-100, default 10)")
    p.add_argument("--no-deezer-fallback", action="store_true", help="tracks without Last.fm genre stay Unknown")
    p.add_argument("--workers", type=int, default=6,
                   help="parallel Last.fm requests (default 6; total rate stays capped at 5/s)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("genres", help="list genres in your Favorites with track counts").set_defaults(func=cmd_genres)
    sub.add_parser("tracks", help="print the genre of every favorite track (TSV)").set_defaults(func=cmd_tracks)

    c = sub.add_parser("create", help="create a playlist from Favorites of the given genre(s)")
    c.add_argument("-g", "--genre", action="append", required=True, help="genre name; repeat for several (union)")
    c.add_argument("-n", "--name", help="playlist title (default: 'Favorites - <genres>')")
    c.add_argument("--public", action="store_true", help="make the playlist public (default: private)")
    c.add_argument("--dry-run", action="store_true", help="list matching tracks, create nothing")
    c.set_defaults(func=cmd_create)

    sub.add_parser("gui", help="open the Windows GUI").set_defaults(func=cmd_gui)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args) or 0
    except (DeezerError, LastfmError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
