# Command reference

Commands below assume anistream is installed and `mpv` and `ani-cli-rs` are available on `PATH` (or in ani-cli-rs's supported install directory). Use `anistream --help` or `anistream COMMAND --help` for the parser's current help text.

## Launch the interactive menu

```sh
anistream
```

The main menu contains **Continue watching**, **Planning**, **Search AniList**, **Search all catalogs**, and **Settings**. The program asks for your AniList username on first launch. Reading public lists only needs the username; updating progress requires sync setup and a token.

Menus use `fzf` when installed and enabled. With fzf, type to filter, Enter to select, and Esc to go back. Otherwise, use the displayed number, enter text to filter, `b` to go back, or `q` to quit.

After playback, the app offers next episode, replay, pick an episode, mark as watched, or go back.

## Play an anime

```sh
anistream play "frieren"
anistream play "frieren" -e 3
anistream play "dandadan" --episode 5
```

`play` searches the configured raw catalogs first, including entries not on your AniList list. It uses embedded AniList IDs when present, and otherwise title plus season/stage matching. A manual picker is shown only when automatic matching cannot safely choose. When the result cannot be matched to the correct list entry, it can still play but won't sync progress to the wrong entry.

Without `-e/--episode`, it starts at the next episode if a safe AniList-list match exists; otherwise it uses the app's catalog-playback flow. Use a positive episode number for `-e`.

## Search all catalogs

```sh
anistream search "frieren"
anistream search "jojo 2nd stage"
```

Searches each provider in the configured `providers` list, independent of list membership. Search results are matched against AniList metadata to choose the correct season when possible. This command enters the playback flow for the chosen result.

## Diagnose a match without playing

```sh
anistream probe "frieren" -e 3
anistream probe "dandadan"
```

Starts from an anime that AniList can resolve (from your lists or AniList search), then checks both `sub` and `dub` across configured providers. It reports the AniList title and ID, the catalog match, whether links were returned, the host of the first stream, and whether subtitle tracks were exposed. It does not play video or record progress. For a title that AniList cannot find, use `search` or `play` instead.

## Diagnostics and account setup

```sh
anistream doctor
anistream auth
anistream config
anistream config username YOUR_ANILIST_USERNAME
anistream config quality 720p
anistream --version
```

- `doctor` checks Python, mpv, configured `ani-cli-rs` catalogs, fzf, AniList API reachability, username, and token validity if configured.
- `auth` walks through optional AniList API token setup.
- `config` displays settings; `config KEY` prints a value; `config KEY VALUE` changes and saves it.

## Global options

Global flags are placed **before** the command in normal argparse usage:

```sh
anistream --mode dub play "frieren"
anistream --player sixel
anistream --no-sync play "frieren"
anistream --config ./anistream-test.json doctor
anistream --debug probe "frieren" -e 3
```

| Option | Effect |
| --- | --- |
| `--mode sub|dub` | Select preferred audio mode for this run. Configured fallback may try the other mode. |
| `--player window|sixel` | Use a normal mpv window or render video in a sixel-capable terminal. |
| `--no-sync` | Disable AniList updates for this run. |
| `--config PATH` | Use a specific JSON config file. |
| `--debug` | Show internal matching logs, external `ani-cli-rs` commands, and mpv diagnostics. |
| `--version` | Print the installed version. |
| `-h`, `--help` | Print help. |

## Terminal output

Routine diagnostic lines are hidden during normal menu navigation. mpv stdout/stderr are redirected away from the terminal in window mode; in sixel mode, stdout remains connected for the video while stderr is suppressed. `--debug` restores diagnostic output for troubleshooting and disables mpv's default `--really-quiet` option.
