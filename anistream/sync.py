"""Deciding what to send to AniList after an episode, and how to send it.

Rules (never destructive): progress only goes up; status moves Planning/Paused/Dropped -> Watching on the first episode and ->
Completed on the last one; start/finish dates are set only when missing; notes, scores and other fields are never touched.
"""
import datetime
import subprocess


class Update:
    def __init__(self, media_id, progress, status=None, started=None, completed=None, repeat=None):
        self.media_id, self.progress, self.status = media_id, progress, status
        self.started, self.completed, self.repeat = started, completed, repeat

    def describe(self):
        bits = [f"progress {self.progress}"]
        if self.status:
            bits.append(f"status {self.status.lower()}")
        return ", ".join(bits)

    def as_dict(self):
        return {k: v for k, v in vars(self).items() if v is not None}

    def __repr__(self):
        return f"Update({self.as_dict()})"


def fuzzy_today(today=None):
    d = today or datetime.date.today()
    return {"year": d.year, "month": d.month, "day": d.day}


def _has_date(entry):
    d = (entry or {}).get("startedAt") or {}
    return bool(d.get("year"))


def plan_update(entry, media, episode, today=None):
    """What to save after watching `episode`. None = nothing to change."""
    entry = entry or {}
    status = entry.get("status")
    current = entry.get("progress") or 0
    total = media.get("episodes")
    if status == "COMPLETED":
        return None                                    # an old, finished entry: leave it alone
    if episode <= current and status in ("CURRENT", "REPEATING"):
        return None
    upd = Update(media["id"], max(current, episode))
    if status in (None, "PLANNING", "PAUSED", "DROPPED"):
        upd.status = "CURRENT"
    if status != "REPEATING" and not _has_date(entry):
        upd.started = fuzzy_today(today)
    if total and upd.progress >= total:
        upd.status = "COMPLETED"
        if status == "REPEATING":
            upd.repeat = (entry.get("repeat") or 0) + 1
        else:
            upd.completed = fuzzy_today(today)
    return upd


class AniListBackend:
    name = "AniList"

    def __init__(self, api):
        self.api = api

    def apply(self, upd):
        self.api.save(upd.media_id, progress=upd.progress, status=upd.status, started=upd.started,
                      completed=upd.completed, repeat=upd.repeat)


class ChibiBackend:
    """Optional: let chibi-cli (https://github.com/CosmicPredator/chibi-cli) send the progress.

    Only `--progress` is used. Known upstream issue (#37): `chibi update` can clear the start date and notes of the entry;
    the built-in AniList backend never does that, so it is the default.
    """
    name = "chibi"

    def __init__(self, exe="chibi", runner=subprocess.run):
        self.exe, self.runner = exe, runner

    def apply(self, upd):
        try:
            p = self.runner([self.exe, "update", str(upd.media_id), "--progress", str(upd.progress)],
                            capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise RuntimeError(f"chibi could not run: {e}")
        if p.returncode != 0:
            raise RuntimeError("chibi failed: " + ((p.stderr or p.stdout).strip()[:200] or f"exit {p.returncode}"))


def make_backend(cfg, api):
    """The sync backend the settings ask for, or None (sync off / not set up)."""
    kind = cfg.get("sync")
    if kind == "chibi":
        return ChibiBackend(cfg.get("chibi") or "chibi")
    if kind == "anilist" and cfg.get("token"):
        return AniListBackend(api)
    return None
