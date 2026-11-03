# Configuration reference

## Where settings are stored

The configuration is JSON. By default:

- **Windows:** `%APPDATA%\anistream\config.json`
- **macOS:** `~/Library/Application Support/anistream/config.json`
- **Linux and other Unix-like systems:** `${XDG_CONFIG_HOME:-~/.config}/anistream/config.json`

The persistent playback cache and offline sync queue are stored in `state.json` in the same application config directory. The config file contains only settings that differ from built-in defaults. Files are written atomically; on systems that support it, anistream requests private file permissions because the config may contain an AniList token.

Override paths with `ANISTREAM_HOME` (application directory), `ANISTREAM_CONFIG` (config file), or the command-line `--config PATH` option. `ANISTREAM_TOKEN` and `ANISTREAM_USERNAME` override token and username from the file when set.

## Available settings

Use `anistream config` to list effective settings. Use `anistream config KEY` to inspect one value and `anistream config KEY VALUE` to save one. List values can be supplied as JSON arrays.

| Key | Default | Description |
| --- | --- | --- |
| `username` | empty | AniList user whose lists are read. |
| `token` | empty | AniList access token, used only for updates; keep it private. |
| `client_id` | empty | API client ID used by `anistream auth`. |
| `sync` | `anilist` | `anilist`, `chibi`, or `off`. AniList sync needs a token; `chibi` needs the chibi executable and its own login. |
| `threshold` | `85` | At or above this watched percentage, mark the episode watched (or if the player reports EOF). |
| `ask_below` | `30` | Between this value and `threshold`, ask before recording; below this, do not record. |
| `mode` | `sub` | Preferred audio mode: `sub` or `dub`. |
| `mode_fallback` | `true` | Try the alternate audio mode if the preferred mode fails. |
| `prefer_subtitles` | `true` | In sub mode, try sources that expose external subtitle tracks first; sources without tracks remain candidates. |
| `quality` | `best` | Preferred quality such as `best`, `1080p`, or `720p`. A numeric preference is ordering, not a hard requirement. |
| `title_lang` | `english` | Prefer English or romaji display titles. |
| `player_mode` | `window` | `window` for ordinary mpv or `sixel` for terminal video. |
| `fullscreen` | `false` | Request fullscreen for window mode. |
| `mpv` | `mpv` | mpv executable name or path. On Windows sixel mode may choose `mpv.com`. |
| `mpv_args` | `[]` | Extra mpv command-line arguments, as a JSON array. Terminal output is suppressed in normal mode; use `--debug` to see mpv diagnostics. |
| `ani_cli_rs` | `ani-cli-rs` | Executable name or path. |
| `chibi` | `chibi` | Chibi executable name or path. |
| `providers` | `anikoto`, `anikoto2` | Catalog provider names in fallback order. |
| `use_fzf` | `true` | Use fzf for menus when installed and a terminal is interactive. |

## Examples

```sh
anistream config username YOUR_USERNAME
anistream config mode dub
anistream config quality 720p
anistream config providers '["anikoto2", "anikoto"]'
anistream config mpv_args '["--volume=60"]'
```

Temporarily override playback options without saving configuration:

```sh
anistream --mode dub play "frieren"
anistream --player sixel play "frieren"
anistream --no-sync play "frieren"
```

## Token setup and privacy

Reading public AniList lists only needs a username. To write progress, run `anistream auth` and follow the prompts to create/use an AniList API client and paste its token. Do not share your token or config file publicly. Alternatively, keep the token out of the JSON file by setting `ANISTREAM_TOKEN` in the environment.

If sync is disabled with `anistream --no-sync`, no AniList updates are sent for that invocation. `sync = off` disables backend sync in saved settings.
