# Changelog

## 0.1.8
- Fixed: a subtitled AniList title (e.g. "JoJo's Bizarre Adventure: Steel Ball Run") no longer accepts the parent franchise entry ("JoJo's Bizarre Adventure (2012)") as a match. The "source shortened the title" rule let the franchise pass as its own sequel, so Continue watching could open the wrong anime. The catalog entry must now carry at least one subtitle word.
- Fixed: Continue watching only tried ONE provider when catalogs named the same season differently (anikoto "2nd - 3rd STAGE" vs anikoto2 "2nd Stage"). Those entries were never grouped, so the provider without a stream (ACL-3001) ended playback and earlier episodes failed. Season-marker grouping is now symmetric and every exact-matching provider is kept as a fallback.
- Changed: mpv now starts with a large read-ahead buffer, pauses (instead of closing) when the buffer runs dry, and reconnects dropped HTTP connections. Turn it off with `anistream config mpv_buffer false`; your own `mpv_args` still override these defaults.
- Fixed: a stream that died partway (HLS segments missing) was reported by mpv as a normal end-of-file and the episode could be auto-marked as watched. Now only an ending near the real end counts; an early end shows a warning and offers to resume from where it stopped.
- Added: with `--debug`, mpv's full log is written to `mpv.log` in the anistream config folder (the terminal output was being wiped by the menu). mpv also retries failed HLS segments a few times.
- Added: when the HLS source skips a stretch of video (segments that time out), mpv now seeks back and re-requests it (up to 3 tries per gap; `anistream config mpv_heal false` turns it off). Remaining skipped time is reported after playback. HTTP requests that hang are cut after 15 s and retried, and the HLS demuxer retries a segment up to 40 times before skipping it.
- Fixed: the source rate-limits with HTTP 429 (Too Many Requests), which is what made segments fail. mpv now waits and retries on 429 with a growing delay, reads ahead 45 s instead of 300 s (a big read-ahead pulls segments in a burst and triggers the limit), and the skipped-segment retry waits 4 s before re-requesting.

## 0.1.7
- Hide internal diagnostic/log messages during normal UI navigation; show them with `--debug`.
- Redirect mpv stdout/stderr away from terminal in window mode; in sixel mode preserve stdout for video and suppress stderr. `--debug` restores normal mpv output.
- Suppress incidental fzf stderr chatter unless debugging.

## 0.1.6
- Suppressed routine mpv terminal output with `--really-quiet` by default, preventing player logs from appearing around the menu or above sixel video. Extra mpv arguments can still explicitly adjust mpv logging.
- Added a full documentation set covering commands, config keys and file paths, internal architecture, and troubleshooting.
- Updated package version to 0.1.6.

## 0.1.5

- **Automatic anime selection:** uses the catalog's embedded AniList ID when available, otherwise the same strict title + season/stage matching as `fetch_anime.py`. Continue watching and direct `play`/`search` no longer require choosing among duplicate provider results when a confident match exists.
- **Broader source fallback:** list-based playback now tries streams from all configured `ani-cli-rs` catalogs instead of returning the first provider's links only. If a source link launches and closes immediately, the next link/catalog is tried before falling back to sub/dub.
- **Subtitle-aware fallback:** in sub mode, links exposing subtitle tracks are attempted before links without external subtitle tracks. The latter are still allowed in case they are hard-subbed.
- Added `prefer_subtitles` config option and toggle in Settings.
- Kept the scope streaming-safe: `ani-cli`, `ani-tupi`, and GoAnime in the reference project are download/self-playing pipelines, so they are not falsely presented as stream URL providers.

## 0.1.4

- Fixed Continue watching to search the raw `ani-cli-rs` catalogs first, just like `anistream play`.
- Exact title+season matches continue from AniList progress and sync normally.
- If only another season from the same franchise is available, it can be selected explicitly for playback without syncing progress to the wrong AniList entry.



## 0.1.3
- **Fixed provider routing:** episode links now resolve through the same `ani-cli-rs` provider that returned the catalog ID; previously the search could succeed in one provider but links were requested from the default provider.
- **Added raw catalog search:** `anistream search "frieren"` searches every configured ani-cli-rs provider, including titles not present on your AniList lists. Queries that name a season also retry the base franchise title. Shared alternate titles can no longer merge distinct seasons into one result.
- **Changed direct playback:** `anistream play "frieren"` searches raw catalog results first and lets you choose the actual title/season, rather than letting AniList's search ranking force a potentially unreleased season.
- Added **Search all catalogs** to the home menu and as a recovery option when list-based playback cannot resolve a stream.
- Raw catalog playback bypasses AniList's release-date restriction. Progress is synced only when the selected catalog result safely matches a title/season on your AniList list; otherwise it plays without sync.

## 0.1.2
- **Fixed: preserve the title/query typed in `anistream play` and `anistream probe`.** It is now the first `ani-cli-rs` search, with AniList title candidates as fallbacks. Explicit-name commands refresh their cached catalog match so an old ID cannot silently win.
- Catalog entries that reuse the same AniList ID are no longer accepted when their names explicitly identify a different season/stage.
- Search candidates now include up to five AniList synonyms instead of only two.
- Added regression tests for alias queries, stale matches, and duplicate AniList IDs across stages.

## 0.1.1
- **Fixed: only the first matching catalog was ever used.** When anikoto had the anime but no stream (`ACL-3001`), anistream gave up
  instead of asking anikoto2 (it only retried the other version in the same catalog). It now tries every catalog in order; the first one
  that has the entry **and** a working stream wins, and the message lists what each catalog said. Found on a real Windows run.
- The resolved show is remembered **per catalog** (`state.json`). A "no stream yet" answer keeps it; any other error drops it.
- New command **`anistream probe "name" [-e N]`**: for sub and dub and every catalog, shows what matched and whether a stream exists,
  without playing or recording anything.
- Looks for `ani-cli-rs` in its default install folder (`%USERPROFILE%\.local\bin`) when it is not on PATH; output is forced to UTF-8 so ▶ and ✓
  never crash a legacy console.
- 107 tests (was 98), including an end-to-end test of exactly this failure.

## 0.1.0
- First version: lists, search, mpv playback (window or sixel), optional AniList sync, chibi backend, `doctor`, `auth`, `config`.
