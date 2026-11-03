# Architecture and playback flow

## Main components

- `anistream/cli.py` — command-line parser, command dispatch, `doctor`, and direct catalog search / probe flows.
- `anistream/app.py` — interactive menu, AniList list browsing, episode selection, playback decisions, and sync decisions.
- `anistream/matching.py` — title normalization, season/stage matching, AniList ID extraction, and grouping provider results.
- `anistream/engine.py` — `ani-cli-rs` invocation, catalog search, provider-specific link resolution, and ordering fallback candidates.
- `anistream/player.py` — mpv arguments, subtitle/request headers, playback launch, and reading the watch-progress result.
- `anistream/progress.lua` — small mpv script that writes playback position/percent to a temporary JSON file at shutdown.
- `anistream/anilist.py` and `anistream/sync.py` — AniList API operations, sync planning, backend calls, and offline update queue behavior.
- `anistream/config.py` — defaults, paths, JSON config, and persistent cache/queue.
- `anistream/ui.py` — fzf and numbered input menus.

## Catalog selection

1. Search each configured `ani-cli-rs` provider using the typed query and normalized/base-title variants.
2. Group duplicate results and preserve provider + catalog ID so resolving links uses the provider that returned the match.
3. Prefer an embedded AniList ID when present. When the catalog has no such ID, use strict normalized-title and season/stage matching against AniList titles and the original search query.
4. Show a manual picker only when the title cannot be confidently disambiguated.
5. Resolve links for the chosen catalog ID via that same provider. Keep usable links from multiple providers so playback can fall through if a source cannot resolve or closes immediately.

A catalog result that is not safely linked to the user's AniList entry may still play. It must not update progress for a different entry or season.

## Playback and logs

mpv receives the stream URL, referer/user-agent/other headers supported by the stream metadata, subtitle URLs exposed by the catalog, the progress script, and optional user-specified `mpv_args`. Routine diagnostic messages are hidden during normal UI use. Window mode redirects both mpv stdout and stderr away from the terminal; sixel mode keeps stdout attached because it carries the video and suppresses stderr. `--debug` restores diagnostic output and omits the default `--really-quiet` flag for troubleshooting.

The progress script reports position, duration, whether video started, and whether playback reached EOF. The Python app interprets this result and decides if progress should be sent, queued, or left unchanged.

## Progress sync

- At or above `threshold` (default 85%), or when mpv reports EOF, the app records the episode.
- Between `ask_below` (default 30%) and `threshold`, the app asks first.
- Below `ask_below`, it does not record.
- When the progress report is missing or the user seeks beyond the expected next episode, the app asks rather than guessing.
- AniList progress is not intentionally decreased. Updates are planned against current entry data, and failed updates are queued for a later invocation.
- `--no-sync` disables the sync backend for the current run. Unknown or mismatched catalog entries can play without being linked to the wrong list entry.

## External processes

The app invokes `ani-cli-rs` with captured stdout/stderr so command output can be parsed as JSON and does not spill into menus. `mpv` is attached to the terminal for playback, but uses quiet mode by default. `fzf` is started only for interactive selection if it is installed and enabled.

## Packaging

`pyproject.toml` declares a dependency-free Python package and the `anistream` console entry point. `progress.lua` is included as package data. `anistream.cmd` and `anistream.sh` are convenience launchers for running the module from a source checkout.
