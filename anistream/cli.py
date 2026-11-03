"""Command line: `anistream` (menus), `play`, `auth`, `doctor`, `config`."""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

from . import __version__
from . import matching as m
from .anilist import AniList, AniListError
from .app import App
from .config import DEFAULTS, State, config_path, load_config, save_config
from .engine import AniCliRs, EngineError, find_exe, parse_links
from .player import PlayerError, mpv_executable, play
from .sync import make_backend
from .ui import UI, Quit


def build_parser():
    p = argparse.ArgumentParser(prog="anistream", description="Stream the anime on your AniList lists, with optional progress sync.")
    p.add_argument("--version", action="version", version=f"anistream {__version__}")
    p.add_argument("--config", help="use this config file")
    p.add_argument("--mode", choices=["sub", "dub"], help="sub or dub for this run")
    p.add_argument("--player", choices=["window", "sixel"], dest="player_mode", help="window, or video inside the terminal (sixel)")
    p.add_argument("--no-sync", action="store_true", help="do not send anything to AniList in this run")
    p.add_argument("--debug", action="store_true", help="print the commands that are run")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("auth", help="connect your AniList account (optional)")
    sub.add_parser("doctor", help="check mpv, ani-cli-rs, fzf, AniList")
    se = sub.add_parser("search", help="search all ani-cli-rs catalogs, including anime not on your AniList")
    se.add_argument("name", nargs="+")
    pl = sub.add_parser("play", help="search all catalogs and play an anime (default: next episode if safely on your list)")
    pl.add_argument("name", nargs="+")
    pl.add_argument("-e", "--episode", type=int)
    pr = sub.add_parser("probe", help="show, per catalog, what matches an anime and whether a stream exists (plays nothing)")
    pr.add_argument("name", nargs="+")
    pr.add_argument("-e", "--episode", type=int)
    cf = sub.add_parser("config", help="show or change a setting")
    cf.add_argument("key", nargs="?")
    cf.add_argument("value", nargs="?")
    return p


def build_app(cfg, args, ui=None):
    ui = ui or UI(use_fzf=cfg.get("use_fzf", True), debug=getattr(args, "debug", False))
    state = State()
    api = AniList(cfg.get("token", ""))
    log = (lambda msg: ui.log(msg)) if args.debug else None
    engine = AniCliRs(cfg["ani_cli_rs"], cfg["providers"], state, log=log)
    backend = None if args.no_sync else make_backend(cfg, api)
    return App(cfg, ui, api, engine, play, backend, state)


def _coerce(key, raw):
    default = DEFAULTS[key]
    if isinstance(default, bool):
        return raw.lower() in ("1", "true", "yes", "on", "y")
    if isinstance(default, int):
        return int(raw)
    if isinstance(default, list):
        return json.loads(raw) if raw.strip().startswith("[") else [x for x in re.split(r"[,\s]+", raw) if x]
    return raw


def cmd_config(cfg, args, ui, path):
    if not args.key:
        for k in DEFAULTS:
            v = cfg.get(k)
            ui.say(f"{k} = {'(set)' if k == 'token' and v else json.dumps(v, ensure_ascii=False)}")
        ui.dim(f"file: {path or config_path()}")
        return 0
    if args.key not in DEFAULTS:
        ui.error(f"Unknown setting '{args.key}'. Known: {', '.join(DEFAULTS)}")
        return 2
    if args.value is None:
        ui.say(json.dumps(cfg.get(args.key), ensure_ascii=False) if args.key != "token" else "(set)" if cfg.get("token") else "")
        return 0
    try:
        cfg[args.key] = _coerce(args.key, args.value)
    except ValueError:
        ui.error(f"'{args.value}' is not valid for {args.key}.")
        return 2
    save_config(cfg, path)
    ui.ok(f"{args.key} saved.")
    return 0


def lookup_media(app, name_parts):
    """The anime called `name_parts`: from your lists first, then an AniList search. -> (media, entry) or None."""
    ui, api, cfg = app.ui, app.api, app.cfg
    needle = " ".join(name_parts).lower()
    entries = []
    if cfg.get("username"):
        try:
            entries = api.lists(cfg["username"])
        except AniListError as e:
            ui.warn(f"Could not read your lists ({e}); searching AniList instead.")
    hits = [e for e in entries if any(needle in t.lower() for t in m.all_titles(e["media"]))]
    if len(hits) > 1:
        i = ui.pick("Which one?", [app.entry_label(e) for e in hits])
        hits = [hits[i]] if i is not None else []
    if hits:
        return hits[0]["media"], hits[0]
    results = api.search(" ".join(name_parts))
    results = [r for r in results if not r.get("isAdult")] or results
    if not results:
        ui.error("No anime found.")
        return None
    i = 0 if len(results) == 1 else ui.pick("Which one?", [app.name(r) for r in results])
    if i is None:
        return None
    media = dict(results[i])
    raw = media.pop("mediaListEntry", None)
    return media, (dict(raw, media=media) if raw else None)


def _catalog_group_for_query(app, query):
    """Search raw catalogs, then auto-pick using AniList ID + strict title/season matching.

    The search result menu is only shown when neither AniList metadata nor a strict query match can
    safely disambiguate the catalog results.
    """
    try:
        raw = app.engine.search_catalog(query, app.cfg["mode"])
    except EngineError as e:
        app.ui.warn(f"Raw catalog search failed ({e}); falling back to AniList lookup.")
        return None
    groups = m.group_catalog_results(raw)
    if not groups:
        return None

    # Like fetch_anime.py: use each AniList result's ID when the catalog carries it; otherwise use
    # matching words and season/stage numbers. Iterate AniList's ranked results so an unavailable
    # sequel doesn't shadow a playable earlier season with a different AniList ID.
    try:
        candidates = app.api.search(query)
    except AniListError as e:
        app.ui.log(f"AniList matching unavailable ({e}); trying exact catalog-title matching.")
        candidates = []
    for media in candidates:
        group = app.pick_catalog_group(groups, m.all_titles(media), media.get("id"))
        if group is not None:
            linked_media, linked_entry = app.catalog_list_entry(group)
            app.ui.log(f"Auto-selected catalog entry: {group['name']}")
            return group, linked_media, linked_entry

    group = app.pick_catalog_group(groups, [query], None)
    if group is None and len(groups) == 1:
        group = groups[0]
    if group is not None:
        linked_media, linked_entry = app.catalog_list_entry(group)
        app.ui.log(f"Auto-selected catalog entry: {group['name']}")
        return group, linked_media, linked_entry

    labels = []
    for result_group in groups:
        providers = ", ".join(dict.fromkeys(row.get("provider", "?") for row in result_group["matches"]))
        labels.append(f"{result_group['name']}  [{providers}]")
    idx = app.ui.pick(f"No confident match for '{query}'. Choose a catalog result", labels)
    if idx is None:
        return (None, None, None)
    group = groups[idx]
    media, entry = app.catalog_list_entry(group)
    return group, media, entry


def cmd_play(app, args):
    search_query = " ".join(args.name)
    found_catalog = _catalog_group_for_query(app, search_query)
    if found_catalog is not None:
        group, media, entry = found_catalog
        if group is None:                 # the user backed out of the result picker
            return 0
        if media is None:
            app.ui.dim("This catalog result is not safely matched to an AniList list entry; progress will not be synced.")
        if args.episode:
            return 0 if app.play_catalog_episode(group["matches"], args.episode, group["name"], media, entry) else 1
        app.watch_catalog(group["matches"], group["name"], None, media, entry)
        return 0

    # Compatibility fallback for entries that AniList knows but the configured raw catalogs do not return.
    found = lookup_media(app, args.name)
    if not found:
        return 1
    media, entry = found
    app.entries[media["id"]] = entry if entry else {"media": media, "progress": 0}
    if args.episode:
        return 0 if app.play_episode(media, app.entries[media["id"]], args.episode, search_query=search_query) else 1
    app.watch(media, entry, search_query=search_query)
    return 0


def cmd_search(app, args):
    """Explicit raw-catalog search, independent of AniList lists and AniList's search ranking."""
    query = " ".join(args.name)
    found_catalog = _catalog_group_for_query(app, query)
    if found_catalog is None:
        app.ui.warn(f"No raw catalog results for '{query}'. Try `anistream --debug search {query!r}` for command details.")
        return 1
    group, media, entry = found_catalog
    if group is None:
        return 0
    if media is None:
        app.ui.dim("This catalog result is not safely matched to an AniList list entry; progress will not be synced.")
    app.watch_catalog(group["matches"], group["name"], None, media, entry)
    return 0


def cmd_probe(app, args):
    """For every version and catalog: which entry matched and whether it has a stream. Nothing is played or recorded."""
    from urllib.parse import urlparse
    ui, cfg = app.ui, app.cfg
    found = lookup_media(app, args.name)
    if not found:
        return 1
    media, entry = found
    done = (entry or {}).get("progress") or 0
    ep = args.episode or done + 1
    ui.say(ui.bold(f"{app.name(media)}  ·  AniList id {media['id']}  ·  Ep {ep}  (your progress {done})"))
    ui.dim("names AniList knows: " + " | ".join(m.all_titles(media)))
    any_ok = False
    for mode in ("sub", "dub"):
        for row in app.engine.probe(media, ep, mode, cfg["quality"], search_query=" ".join(args.name)):
            head = f"[{mode}] {row['provider']}"
            if row["streams"]:
                any_ok = True
                s = row["streams"][0]
                ui.ok(f"{head}: '{row['entry']}' → {len(row['streams'])} stream(s); first: {s.label()} @ {urlparse(s.url).netloc}"
                      + (f", {len(s.subtitles)} subtitle track(s)" if s.subtitles else ""))
            elif row["entry"]:
                ui.warn(f"{head}: '{row['entry']}' matched, but no stream: {row['error']}")
            else:
                ui.warn(f"{head}: {row['error']}")
    return 0 if any_ok else 1


# ---------------------------------------------------------------------------- doctor
def _run(cmd, timeout=15):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)
        return p.returncode, p.stdout + p.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, str(e)


def cmd_doctor(cfg, ui, api):
    bad = 0

    def line(ok, name, detail="", hint=""):
        nonlocal bad
        (ui.ok if ok is True else ui.warn if ok == "warn" else ui.error)(f"{name}: {detail}")
        if hint and ok is not True:
            ui.dim("    " + hint)
        if ok is False:
            bad += 1

    line(sys.version_info >= (3, 8), "Python", sys.version.split()[0], "anistream needs Python 3.8 or newer")
    exe = mpv_executable(cfg)
    if shutil.which(exe) or os.path.exists(exe):
        rc, out = _run([exe, "--version"])
        line(True, "mpv", (out.splitlines() or ["?"])[0][:60])
        if cfg["player_mode"] == "sixel":
            rc, vo = _run([exe, "--vo=help"])
            line(True if "sixel" in vo.lower() else "warn", "mpv sixel output", "available" if "sixel" in vo.lower() else "not found in this mpv build",
                 "Use an mpv build with sixel support, or: anistream config player_mode window")
    else:
        line(False, "mpv", "not found", "Windows: winget install mpv.mpv   (or: scoop install mpv)")
    engine = AniCliRs(cfg["ani_cli_rs"], cfg["providers"])
    try:
        version = engine.version()
    except EngineError:
        version = None
    if version:
        line(True, "ani-cli-rs", f"{version}  ({find_exe(cfg['ani_cli_rs'])})")
        for provider in cfg["providers"]:
            rc, out, err = engine._run(["search", "--mode", "sub", "--json", "frieren"], provider, timeout=60)
            found = m.parse_rs_results(out) if rc == 0 else []
            line(True if found else "warn", f"  catalog {provider}", f"{len(found)} result(s) understood" if rc == 0 else m.rs_error_summary(err or out),
                 "" if found else "If this stays empty, paste `ani-cli-rs --provider %s search --json frieren` in an issue." % provider)
    else:
        line(False, "ani-cli-rs", "not found", "Install it: https://github.com/vorlie/ani-cli-rs/wiki/Installation")
    line(True if shutil.which("fzf") else "warn", "fzf", "found" if shutil.which("fzf") else "not installed (numbered menus are used)",
         "Optional: winget install fzf")
    try:
        api.ping()
        line(True, "AniList", "reachable")
    except AniListError as e:
        line(False, "AniList", str(e))
    line(True if cfg.get("username") else "warn", "AniList user", cfg.get("username") or "not set", "Run anistream and enter it, or: anistream config username NAME")
    if cfg.get("token"):
        try:
            line(True, "AniList token", f"valid, logged in as {api.viewer()['name']}")
        except AniListError as e:
            line(False, "AniList token", str(e), "Run: anistream auth")
    else:
        line("warn", "AniList sync", "off (no token)", "Optional: anistream auth")
    if cfg.get("sync") == "chibi":
        line(True if shutil.which(cfg["chibi"]) else False, "chibi", "found" if shutil.which(cfg["chibi"]) else "not found")
        ui.dim("    chibi note: `chibi update` can clear start dates/notes (upstream issue #37). The built-in sync does not.")
    return 1 if bad else 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")    # ▶ ✓ must not crash a legacy console or a redirect
        except (AttributeError, ValueError):
            pass
    if os.name == "nt":
        os.system("")                                  # lets the Windows console understand ANSI colours
    path = args.config
    cfg = load_config(path)
    # Runtime-only flag: never persisted to the user's config file.
    cfg["_debug"] = bool(args.debug)
    if args.mode:
        cfg["mode"] = args.mode
    if args.player_mode:
        cfg["player_mode"] = args.player_mode
    ui = UI(use_fzf=cfg.get("use_fzf", True), debug=args.debug)
    try:
        if args.cmd == "config":
            return cmd_config(cfg, args, ui, path)
        app = build_app(cfg, args, ui)
        if args.cmd == "doctor":
            return cmd_doctor(cfg, ui, app.api)
        if args.cmd == "auth":
            app.auth()
            return 0
        if args.cmd == "play":
            return cmd_play(app, args)
        if args.cmd == "search":
            return cmd_search(app, args)
        if args.cmd == "probe":
            return cmd_probe(app, args)
        app.home()
        return 0
    except (Quit, KeyboardInterrupt, EOFError):
        ui.say()
        return 0
    except (AniListError, EngineError, PlayerError) as e:
        ui.error(str(e))
        return 1
