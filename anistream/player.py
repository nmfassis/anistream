"""Launch mpv for a resolved stream and learn how much of it was watched.

Two modes, like the yt-terminal port: `window` (a normal mpv window) and `sixel` (video drawn inside a sixel-capable terminal such
as Windows Terminal, via `mpv.com --vo=sixel` on Windows). Progress comes from progress.lua, which mpv runs and which writes a
small JSON file when playback ends.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPT = str(Path(__file__).with_name("progress.lua"))


class PlayerError(Exception):
    pass


class PlayResult:
    def __init__(self, returncode=None, percent=None, position=0.0, duration=0.0, eof=False, started=False, elapsed=0.0,
                 early=False, reason="", skipped=0.0):
        self.returncode = returncode
        self.percent = percent            # None = the progress script did not report (unknown)
        self.position = position
        self.duration = duration
        self.eof = eof
        self.started = started
        self.elapsed = elapsed
        self.early = early                # the stream ended well before the end of the episode (broken/stalled HLS)
        self.reason = reason
        self.skipped = skipped            # seconds the source jumped over and could not be re-fetched

    def __repr__(self):
        return f"PlayResult(rc={self.returncode}, percent={self.percent}, eof={self.eof}, started={self.started})"


def mpv_executable(cfg, which=shutil.which):
    """On Windows the console build (mpv.com) is needed to draw in the terminal."""
    exe = cfg.get("mpv") or "mpv"
    if cfg.get("player_mode") == "sixel" and sys.platform.startswith("win") and exe.lower() in ("mpv", "mpv.exe"):
        return which("mpv.com") or exe
    return exe


# By default mpv reads ahead only a few seconds of an HLS stream, and a failed segment download is treated as end-of-file,
# which closes the player as soon as the buffer runs dry. These keep a large read-ahead, make mpv PAUSE and wait on an
# underrun, and let ffmpeg reconnect dropped HTTP connections instead of giving up.
BUFFER_ARGS = [
    "--cache=yes",
    # Modest read-ahead on purpose: the source rate-limits (HTTP 429 Too Many Requests), and a big read-ahead pulls segments
    # in a burst that triggers exactly that. ~45 s ahead is enough to ride out a short stall.
    "--demuxer-max-bytes=128MiB",
    "--demuxer-max-back-bytes=32MiB",
    "--demuxer-readahead-secs=45",
    "--cache-pause=yes",
    "--cache-pause-wait=8",
    "--network-timeout=30",
    # reconnect_on_http_error=429 makes ffmpeg wait and retry a rate-limited request, with a growing delay up to 30 s
    # (reconnect_delay_max). rw_timeout (microseconds) cuts a hung request after 15 s. seg_max_retry makes the HLS demuxer
    # retry a segment many times before it would skip it (a skipped segment is a missing stretch of video).
    "--stream-lavf-o=reconnect=1,reconnect_streamed=1,reconnect_on_network_error=1,reconnect_on_http_error=429,reconnect_delay_max=30,rw_timeout=15000000",
    "--demuxer-lavf-o=reconnect=1,reconnect_streamed=1,reconnect_on_network_error=1,reconnect_on_http_error=429,reconnect_delay_max=30,rw_timeout=15000000,seg_max_retry=40",
]


def log_path():
    from .config import config_dir
    return str(config_dir() / "mpv.log")


def build_command(cfg, stream, title, out_file, exe=None, start=None):
    cmd = [exe or mpv_executable(cfg)]
    if not cfg.get("_debug"):
        cmd.append("--really-quiet")
    else:
        # The terminal output flashes by (or is wiped by the menu), so keep a copy that can be read afterwards.
        cmd += [f"--log-file={log_path()}", "--msg-level=all=v"]
    if start:
        cmd.append(f"--start={int(start)}")
    cmd += [f"--force-media-title={title}", f"--script={SCRIPT}",
            f"--script-opts=anistream-out={out_file}"]
    if not cfg.get("mpv_heal", True):
        cmd.append("--script-opts-append=anistream-heal=0")
    for key, value in stream.headers.items():
        low = key.lower()
        if low == "user-agent":
            cmd.append(f"--user-agent={value}")
        elif low in ("referer", "referrer"):
            cmd.append(f"--referrer={value}")
        else:                                              # one option per header: values may contain commas
            cmd.append(f"--http-header-fields-append={key}: {value}")
    for url, label in stream.subtitles:
        cmd.append(f"--sub-file={url}")
    if stream.subtitles:
        cmd += ["--sid=auto", "--slang=en,eng,english"]
    if cfg.get("player_mode") == "sixel":
        cmd.append("--vo=sixel")
    elif cfg.get("fullscreen"):
        cmd.append("--fullscreen")
    if cfg.get("mpv_buffer", True):
        cmd += BUFFER_ARGS
    cmd += [str(a) for a in cfg.get("mpv_args") or []]
    cmd.append(stream.url)
    return cmd


def read_result(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def play(cfg, stream, title, runner=None, clock=time.time, which=shutil.which, start=None):
    """Run mpv quietly by default, preserving stdout only for sixel video."""
    exe = mpv_executable(cfg, which)
    if not which(exe) and not os.path.exists(exe):
        raise PlayerError(f"'{exe}' was not found. Install mpv: winget install mpv.mpv  (or: scoop install mpv)")
    out = os.path.join(tempfile.gettempdir(), f"anistream-{os.getpid()}-{int(clock() * 1000)}.json")
    cmd = build_command(cfg, stream, title, out, exe, start=start)
    t0 = clock()
    try:
        if runner is None:
            # Window mode does not need terminal output at all. Sixel mode writes the video
            # stream to stdout, so keep stdout attached there and silence only stderr.
            if cfg.get("_debug"):
                rc = subprocess.call(cmd)
            elif cfg.get("player_mode") == "sixel":
                rc = subprocess.call(cmd, stderr=subprocess.DEVNULL)
            else:
                rc = subprocess.call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            # Keep custom/test runners backwards-compatible with the original one-argument API.
            rc = runner(cmd)
    except OSError as e:
        raise PlayerError(f"Could not start mpv: {e}")
    elapsed = clock() - t0
    data = read_result(out)
    for leftover in (out, out + ".tmp"):
        try:
            os.remove(leftover)
        except OSError:
            pass
    if data is None:
        return PlayResult(returncode=rc, elapsed=elapsed)
    return PlayResult(returncode=rc, percent=float(data.get("percent") or 0), position=float(data.get("position") or 0),
                      duration=float(data.get("duration") or 0), eof=bool(data.get("eof")), started=bool(data.get("started")),
                      elapsed=elapsed, early=bool(data.get("early")), reason=str(data.get("reason") or ""), skipped=float(data.get("skipped") or 0))
