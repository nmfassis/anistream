"""Settings and small persistent state (resolved shows, queued AniList updates)."""
import json
import os
import sys
import tempfile
from pathlib import Path

APP = "anistream"

DEFAULTS = {
    "username": "",            # your AniList name (lists are public; no token needed to read them)
    "token": "",               # AniList access token (only needed to sync progress)
    "client_id": "",           # your own AniList API client id (used by `anistream auth`)
    "sync": "anilist",         # anilist | chibi | off   (anilist only works when a token is set)
    "threshold": 85,           # % of an episode that counts as watched
    "ask_below": 30,           # between this and threshold the app asks; below it, nothing is recorded
    "mode": "sub",             # sub | dub
    "mode_fallback": True,     # try the other version when the preferred one is not available
    "prefer_subtitles": True,  # for sub: try catalogs with subtitle tracks before sources without tracks
    "quality": "best",         # best | worst | 1080p | 720p ...
    "title_lang": "english",   # english | romaji
    "player_mode": "window",   # window | sixel  (sixel = video inside the terminal, like the yt-terminal port)
    "fullscreen": False,
    "mpv": "mpv",
    "mpv_args": [],            # extra mpv arguments (added last, so they override the buffering defaults)
    "mpv_heal": True,          # when the source skips a stretch of video, seek back and re-request it (up to 3 times)
    "mpv_buffer": True,        # read-ahead + network reconnect so a stalled buffer pauses mpv instead of ending playback
    "ani_cli_rs": "ani-cli-rs",
    "chibi": "chibi",
    "providers": ["anikoto", "anikoto2"],
    "use_fzf": True,           # use fzf for menus when it is installed
}


def config_dir():
    override = os.environ.get("ANISTREAM_HOME")
    if override:
        return Path(override)
    if sys.platform.startswith("win"):
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / APP
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / APP


def config_path():
    return Path(os.environ.get("ANISTREAM_CONFIG") or config_dir() / "config.json")


def state_path():
    return config_dir() / "state.json"


def secure_write(path, text):
    """Atomic write; private to the user where the OS supports it (the file can hold your AniList token)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def load_config(path=None):
    """Defaults < config file < environment (ANISTREAM_TOKEN / ANISTREAM_USERNAME)."""
    cfg = dict(DEFAULTS)
    path = Path(path) if path else config_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            cfg.update({k: v for k, v in data.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    if os.environ.get("ANISTREAM_TOKEN"):
        cfg["token"] = os.environ["ANISTREAM_TOKEN"].strip()
    if os.environ.get("ANISTREAM_USERNAME"):
        cfg["username"] = os.environ["ANISTREAM_USERNAME"].strip()
    return cfg


def save_config(cfg, path=None):
    """Only keys that differ from the defaults are written, so new defaults reach existing users."""
    path = Path(path) if path else config_path()
    keep = {k: v for k, v in cfg.items() if k in DEFAULTS and v != DEFAULTS[k]}
    if os.environ.get("ANISTREAM_TOKEN"):
        keep.pop("token", None)                       # never write a token that came from the environment
    secure_write(path, json.dumps(keep, indent=2, ensure_ascii=False) + "\n")


class State:
    """~/.config/anistream/state.json: which catalog entry belongs to which AniList entry, and updates waiting for the network."""

    def __init__(self, path=None):
        self.path = Path(path) if path else state_path()
        self.data = {"shows": {}, "pending": []}
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self.data["shows"] = loaded.get("shows") or {}
                self.data["pending"] = loaded.get("pending") or []
        except (OSError, ValueError):
            pass

    def save(self):
        try:
            secure_write(self.path, json.dumps(self.data, indent=1) + "\n")
        except OSError:
            pass

    # resolved catalog entries -------------------------------------------------
    def show(self, media_id, mode, provider):
        return self.data["shows"].get(f"{media_id}:{mode}:{provider}")

    def remember_show(self, media_id, mode, provider, sid, name):
        self.data["shows"][f"{media_id}:{mode}:{provider}"] = {"sid": sid, "name": name}
        self.save()

    def forget_show(self, media_id, mode, provider):
        if self.data["shows"].pop(f"{media_id}:{mode}:{provider}", None) is not None:
            self.save()

    # updates that could not be sent --------------------------------------------
    def queue(self, media_id, episode):
        item = {"media_id": int(media_id), "episode": int(episode)}
        if item not in self.data["pending"]:
            self.data["pending"].append(item)
            self.save()

    def pending(self):
        return list(self.data["pending"])

    def clear_pending(self, item):
        if item in self.data["pending"]:
            self.data["pending"].remove(item)
            self.save()
