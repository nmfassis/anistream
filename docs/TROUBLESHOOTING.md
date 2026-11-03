# Troubleshooting

## Start with `doctor`

```sh
anistream doctor
```

This checks the Python runtime, mpv, `ani-cli-rs`, search results from configured providers, fzf, AniList API reachability, username, and token validity when configured. Fix missing dependencies or invalid credentials reported there before debugging a specific title.

## Search finds nothing or chooses the wrong season

Try the shorter franchise title, then a season-specific title:

```sh
anistream search "frieren"
anistream search "jojo 2nd stage"
anistream --debug search "frieren"
```

Matching uses the catalog's embedded AniList ID when available, otherwise normalized titles and strict season/stage information. A picker may appear when there is no confident match. Catalog availability and naming can differ by provider.

## Search works but an episode does not play

```sh
anistream probe "frieren" -e 3
anistream --debug probe "frieren" -e 3
```

Probe compares sub/dub links across the configured providers without launching mpv. `ACL-3001` generally means that provider could not obtain playable sources for that catalog entry/episode; try another episode, `--mode dub`, or the all-catalog search. Streams can be missing temporarily.

## mpv logs or video clutter the terminal

Normal playback suppresses mpv stdout/stderr in window mode and stderr in sixel mode. Diagnostic logs are shown when you run with `--debug`; this also disables the default `--really-quiet` flag:

```sh
anistream config mpv_args '[]'
```

If you explicitly enabled mpv logs for diagnosis, remove that `mpv_args` entry again after troubleshooting. Sixel mode requires a terminal and mpv build that support sixel output.

## Video plays, but progress does not update

- Run `anistream doctor` and confirm the token is valid.
- Confirm that sync is enabled and you did not use `--no-sync`.
- Review the watched-percentage thresholds in `anistream config`.
- Progress syncing is only allowed when the selected catalog result can be safely matched to the right AniList entry and season.
- Failed updates may be queued for a later run; keep the config/state directory intact if you want the queue retained.

## Common dependency issues

- **mpv missing:** install mpv, then rerun `anistream doctor`.
- **ani-cli-rs missing:** install it using the [official installation instructions](https://github.com/vorlie/ani-cli-rs/wiki/Installation).
- **fzf missing:** optional; anistream falls back to numbered menus.
- **AniList authorization rejected:** run `anistream auth` again and do not share the token.

When reporting a bug, include the exact command, OS, `anistream --version`, and relevant `doctor` / `probe` output. Remove access tokens and any private details first. `--debug` output can include searched titles and local executable paths, so review it before posting publicly.
