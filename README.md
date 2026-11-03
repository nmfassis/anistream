# anistream

**English** · [Português](README.pt-BR.md)

Stream the anime on your AniList lists from the terminal, with the next episode one keypress away. Video plays in **mpv**, either in
its own window or **inside the terminal** (sixel, the way the yt-terminal port does it). Syncing watched episodes back to AniList is
**optional**.

> **Version: 0.1.8.** Routine player and internal diagnostic logs are now hidden during normal UI use; window mode output is redirected, while sixel video keeps stdout available. See the [documentation index](docs/README.md) for the full command, configuration, architecture, and troubleshooting guides.

## What it does

- **Your lists, ready to play.** *Continue watching* shows what you are watching with `▶ Ep 3 ready`, or `Ep 5 airs in 2d 4h` when you
  are caught up. *Planning* and an AniList *search* are there too.
- **Automatic catalog matching.** Continue watching and direct searches pick the best safe catalog match using the catalog's embedded AniList ID first, otherwise strict title plus season/stage matching. The manual picker appears only when the title cannot be matched confidently.
- **Plays through mpv without log clutter.** Routine diagnostic logs are hidden by default; window-mode mpv output is redirected, and sixel mode keeps stdout available for video while suppressing stderr. Window mode or `--player sixel` for video inside a sixel-capable terminal (such as Windows Terminal). Request headers (Referer…) and subtitle tracks from the stream are passed to mpv.
- **Right show, right stage.** The catalog entry is chosen by the AniList id the catalog carries when it has one, otherwise by a strict
  check of the words **and** the season/stage numbers ("1st STAGE" ≠ "2nd - 3rd STAGE"). The same rules as
  [anilist-autodl](https://github.com/nmfassis/anilist-autodl).
- **Optional sync, never destructive.** When an episode counts as watched (default 85%), progress goes up on AniList; Planning/Paused →
  Watching on the first episode; → Completed on the last, with start/finish dates only if missing. Progress is never lowered; notes,
  scores and other fields are never touched. If you are offline the update is queued and sent next time.
- **Source fallback.** It tries both configured `ani-cli-rs` catalogs in order, continues to other provider links when a link closes immediately, then falls back to the other audio mode when enabled. In sub mode, sources exposing subtitle tracks are tried before sources that expose none (which may still be hard-subbed).

## Install

**One line** (Git Bash on Windows, or Linux/macOS). It needs Python 3.8+ and sets up the `anistream` command, no pip involved:

```bash
curl -fsSL https://raw.githubusercontent.com/YOUR_GITHUB_USER/anistream/main/install.sh | bash
```

From a clone, `bash install.sh` does the same with the local files; `bash install.sh --uninstall` removes it. Re-running updates in place.

Either way you need **Python 3.8+**, **mpv** and **ani-cli-rs**. **fzf** is optional (nicer menus).

**Windows**

```
winget install Python.Python.3.12
winget install mpv.mpv
winget install fzf                       # optional
```

Install **ani-cli-rs** as described on its [Installation page](https://github.com/vorlie/ani-cli-rs/wiki/Installation) (it has a prebuilt
Windows x64 build; `anistream` also looks in `%USERPROFILE%\.local\bin`, where its installer puts it).

To install by hand instead, from this folder:

```
pip install .            # or: pipx install .
anistream doctor         # checks everything and tells you what is missing
anistream
```

No install? Run `anistream.cmd` (Windows) or `./anistream.sh` (Linux/macOS) from the folder. Linux/macOS: same steps with your package
manager (`apt install mpv fzf`, `brew install mpv fzf`).

## Using it

`anistream` opens the menus. With fzf: type to filter, Enter to choose, Esc to go back. Without fzf: a number, some text to filter,
`b` back, `q` quit.

After an episode you get: **Next episode · Replay · Pick an episode · Mark as watched · Back**.

`play` and `search` query each configured `ani-cli-rs` catalog directly. anistream consults AniList titles and IDs to auto-pick a matching entry, checks strict season/stage markers, and falls back to a picker only when it cannot confidently decide. This is separate from AniList list membership, so catalog-only shows can still play. The home menu also has **Search all catalogs**. Playback from a raw catalog result only syncs progress when that result can be safely matched to a title/season already on your AniList list; otherwise it plays without syncing.

```
anistream                              # menus
anistream play "dandadan"              # search catalogs first; next episode if matched to your list
anistream play "dandadan" -e 3         # a specific episode from the chosen catalog entry
anistream search "frieren"             # search ALL configured catalogs, even anime not on your list
anistream --mode dub play "frieren"    # dub for this run
anistream --player sixel               # video inside the terminal
anistream --no-sync                    # send nothing to AniList in this run
anistream --debug                      # print the ani-cli-rs commands that are run
anistream probe "dandadan" -e 3       # per catalog: what matched, is there a stream? (plays nothing)
anistream doctor
anistream auth
anistream config
```

## AniList sync (optional)

Reading your lists needs only your username. To **update** your list you connect your account once:

1. `anistream auth` (or *Settings → Sync*).
2. Open <https://anilist.co/settings/developer> → *Create New Client*. Name: anything. **Redirect URL:
   `https://anilist.co/api/v2/oauth/pin`**. Copy the client ID.
3. Enter the client ID; your browser opens AniList's authorize page; paste the token it shows.

The token is stored in your config file (`%APPDATA%\anistream\config.json` on Windows, `~/.config/anistream/config.json` elsewhere; private
permissions on Linux/macOS, on Windows it sits in your user profile, so treat it like a password). To keep it out of the file, set
`ANISTREAM_TOKEN` instead. Tokens last about a year.

When does an episode count? At **85%** or when it plays to the end it is recorded automatically. Between **30% and 85%** you are asked.
Below 30% nothing happens. If the progress report is missing you are asked. Skipping ahead (Ep 7 when you are at 3) asks first.

### Chibi (optional backend)

[chibi-cli](https://github.com/CosmicPredator/chibi-cli) can do the sending instead: `anistream config sync chibi`. Log in with
`chibi login` first. anistream then runs only `chibi update <id> --progress <n>`.

Know before you choose it: chibi keeps its token in the OS keyring, so anistream cannot share it; and a known upstream issue (#37) says
`chibi update` can **clear the start date and notes** of an entry. The built-in sync never does that, which is why it is the default.
The chibi backend also cannot change the status (Watching/Completed).

## Settings

`anistream config` lists them, `anistream config KEY VALUE` changes one (also in *Settings*).

| Key | Default | Meaning |
| --- | --- | --- |
| `username` | – | your AniList name |
| `sync` | `anilist` | `anilist` (needs a token), `chibi`, or `off` |
| `threshold` / `ask_below` | `85` / `30` | % that counts as watched / % below which nothing is asked |
| `mode` / `mode_fallback` | `sub` / `true` | `sub` or `dub`; try the other when missing |
| `prefer_subtitles` | `true` | in sub mode, try links with subtitle tracks before links without them |
| `quality` | `best` | `best`, `1080p`, `720p`… (preferred first, never required) |
| `player_mode` | `window` | `window` or `sixel` |
| `fullscreen` | `false` | window mode only |
| `mpv` / `mpv_args` | `mpv` / `[]` | executable and extra arguments (`anistream config mpv_args '["--volume=60"]'`) |
| `mpv_buffer` | `true` | large read-ahead, pause on buffer underrun and reconnect dropped connections, so mpv does not close when the buffer runs out |
| `mpv_heal` | `true` | when the source skips a stretch of video, seek back and re-request it (up to 3 times per gap) |
| `title_lang` | `english` | `english` or `romaji` |
| `use_fzf` | `true` | use fzf when installed |
| `providers` | `anikoto anikoto2` | ani-cli-rs catalogs, in order |

## Troubleshooting

- **First step for anything:** `anistream doctor`; then `anistream probe "name" -e N` for one anime. It checks mpv (and sixel support), ani-cli-rs and both catalogs, fzf, AniList and your token.
- **"No catalog entry matches this anime":** run with `--debug` to see the searches. The exact name you typed is now tried first, followed by AniList titles and synonyms. Matches still need compatible season/stage numbers; AniList's "2nd & 3rd STAGE" is accepted when the catalog says "2nd Stage".
- **`ACL-3001 No playable sources found`:** the provider has no working stream for that episode yet (often a brand-new episode). Raw catalog results are now resolved through the same provider that returned them. If list-based playback still fails, use its **Search all catalogs…** recovery option or run `anistream search "name"`; try again later or with `--mode dub`.
- **mpv not found:** `winget install mpv.mpv`. For `--player sixel` on Windows the console build `mpv.com` is used.
- **Watched but nothing was recorded:** check `anistream doctor` for the token; below 85% you are asked; with `sync off` nothing is sent.
  A failed upload is queued ("it will be retried next time").
- **AniList says the token was rejected:** run `anistream auth` again.

## Limits and what is not verified

- **Streaming backends:** anistream uses the two independent `ani-cli-rs` catalogs (`anikoto`, `anikoto2`) and their stream-link fallbacks. `ani-cli`, `ani-tupi`, and GoAnime in the reference `anilist-autodl` project are download or self-playing pipelines, not link resolvers that can hand a stream URL to anistream's mpv/progress tracker, so they are not treated as drop-in streaming backends. Adding one would require a real stream adapter or a separate-player mode.
- **Confirmed on a real Windows setup:** `doctor` passes with mpv, ani-cli-rs 0.11.2 and fzf, and the search output of both catalogs is
  understood. **Not verified against the real thing:** (1) the exact field names of `ani-cli-rs links --json` (the parser accepts several
  spellings; `anistream probe` and `--debug` show what it got); (2) `progress.lua`, the small mpv script that reports how much you watched, was
  written against mpv's documented API but never run in a real mpv; (3) sixel output and Windows Terminal behaviour; (4) AniList's PIN
  authorization flow and the API calls were checked only against a fake server. Please report anything odd with the `--debug` output.
- Streams are signed and temporary: they are resolved right before playing, never saved.

## Documentation

The expanded guides are in [`docs/`](docs/README.md): [command reference](docs/COMMANDS.md), [configuration and file locations](docs/CONFIGURATION.md), [architecture](docs/ARCHITECTURE.md), and [troubleshooting](docs/TROUBLESHOOTING.md).

## Development

```
python -m unittest discover -s tests -v      # the existing offline test suite
```

`anistream/matching.py` is the matching code of anilist-autodl; keep the two in sync if you change the rules.

## AI disclosure

This project was **100% made with AI** (Anthropic's Claude). I directed the work through prompts but did not write any of it by hand.
Read the code before you run it and use it at your own risk.

## Disclaimer

anistream does not host or provide any content; it only plays streams that the catalogs ani-cli-rs searches expose. You are responsible
for following the copyright laws and terms of service that apply to you. Provided "as is", without warranty of any kind. Not affiliated
with AniList, ani-cli-rs, mpv or Chibi.

## Credits

[mpv](https://mpv.io), [ani-cli-rs](https://github.com/vorlie/ani-cli-rs), [AniList API](https://anilist.gitbook.io/anilist-apiv2-docs/),
[fzf](https://github.com/junegunn/fzf), [chibi-cli](https://github.com/CosmicPredator/chibi-cli) (optional).

## License

[MIT](LICENSE)
