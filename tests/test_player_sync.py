import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date

from anistream import player, sync
from anistream.config import DEFAULTS
from anistream.engine import Stream
from tests.helpers import entry, media

CFG = dict(DEFAULTS)
TODAY = date(2026, 10, 24)


class Command(unittest.TestCase):
    def test_headers_subtitles_and_script(self):
        s = Stream("https://cdn/x.m3u8", headers={"Referer": "https://r", "User-Agent": "UA", "Origin": "https://o, with comma"},
                   subtitles=[("https://s/en.vtt", "English")])
        cmd = player.build_command(CFG, s, "Dandadan - Episode 3", "/tmp/out.json", exe="mpv")
        self.assertEqual(cmd[0], "mpv")
        self.assertEqual(cmd[-1], "https://cdn/x.m3u8")
        self.assertIn("--force-media-title=Dandadan - Episode 3", cmd)
        self.assertIn("--referrer=https://r", cmd)
        self.assertIn("--user-agent=UA", cmd)
        self.assertIn("--http-header-fields-append=Origin: https://o, with comma", cmd)     # one option per header: commas are safe
        self.assertIn("--sub-file=https://s/en.vtt", cmd)
        self.assertIn("--script-opts=anistream-out=/tmp/out.json", cmd)
        self.assertTrue(any(c.startswith("--script=") and c.endswith("progress.lua") for c in cmd))
        self.assertTrue(os.path.exists(player.SCRIPT))

    def test_modes(self):
        s = Stream("https://x")
        self.assertIn("--vo=sixel", player.build_command(dict(CFG, player_mode="sixel"), s, "t", "o", exe="mpv"))
        self.assertNotIn("--vo=sixel", player.build_command(CFG, s, "t", "o", exe="mpv"))
        self.assertIn("--fullscreen", player.build_command(dict(CFG, fullscreen=True), s, "t", "o", exe="mpv"))
        self.assertNotIn("--fullscreen", player.build_command(dict(CFG, fullscreen=True, player_mode="sixel"), s, "t", "o", exe="mpv"))
        self.assertIn("--volume=50", player.build_command(dict(CFG, mpv_args=["--volume=50"]), s, "t", "o", exe="mpv"))

    def test_buffering_defaults_can_be_disabled_and_overridden(self):
        s = Stream("https://x")
        on = player.build_command(CFG, s, "t", "o", exe="mpv")
        self.assertIn("--cache-pause=yes", on)
        self.assertIn("--demuxer-readahead-secs=45", on)
        self.assertTrue(any("reconnect_on_http_error=429" in c for c in on))
        self.assertLess(on.index("--demuxer-readahead-secs=45"), on.index("https://x"))
        off = player.build_command(dict(CFG, mpv_buffer=False), s, "t", "o", exe="mpv")
        self.assertNotIn("--cache-pause=yes", off)
        both = player.build_command(dict(CFG, mpv_args=["--demuxer-readahead-secs=60"]), s, "t", "o", exe="mpv")
        self.assertGreater(both.index("--demuxer-readahead-secs=60"), both.index("--demuxer-readahead-secs=45"))   # later wins in mpv

    def test_windows_sixel_uses_the_console_build(self):
        real = sys.platform
        try:
            sys.platform = "win32"
            which = lambda n: "C:/mpv/mpv.com" if n == "mpv.com" else None
            self.assertEqual(player.mpv_executable(dict(CFG, player_mode="sixel"), which), "C:/mpv/mpv.com")
            self.assertEqual(player.mpv_executable(dict(CFG, player_mode="window"), which), "mpv")
            self.assertEqual(player.mpv_executable(dict(CFG, player_mode="sixel", mpv="D:/x/mpv.exe"), which), "D:/x/mpv.exe")
        finally:
            sys.platform = real


class Play(unittest.TestCase):
    def fake_mpv(self, payload):
        """A runner that 'plays' by writing the progress file the Lua script would write."""
        def runner(cmd):
            out = next(c for c in cmd if c.startswith("--script-opts=anistream-out=")).split("=", 2)[2]
            if payload is not None:
                with open(out, "w") as f:
                    json.dump(payload, f)
            return 0
        return runner

    def test_reads_what_the_script_reports(self):
        r = player.play(CFG, Stream("https://x"), "t", runner=self.fake_mpv({"percent": 93.5, "position": 1300, "duration": 1400, "eof": True, "started": True}),
                        which=lambda n: "/usr/bin/mpv")
        self.assertEqual((r.percent, r.eof, r.started, r.returncode), (93.5, True, True, 0))

    def test_no_report_means_unknown(self):
        r = player.play(CFG, Stream("https://x"), "t", runner=self.fake_mpv(None), which=lambda n: "/usr/bin/mpv")
        self.assertIsNone(r.percent)

    def test_temp_files_are_removed(self):
        before = set(os.listdir(tempfile.gettempdir()))
        player.play(CFG, Stream("https://x"), "t", runner=self.fake_mpv({"percent": 10}), which=lambda n: "/x")
        self.assertFalse([f for f in set(os.listdir(tempfile.gettempdir())) - before if f.startswith("anistream-")])

    def test_missing_mpv_is_explained(self):
        with self.assertRaises(player.PlayerError) as cm:
            player.play(CFG, Stream("https://x"), "t", which=lambda n: None)
        self.assertIn("winget install mpv.mpv", str(cm.exception))

    def test_corrupt_report(self):
        p = os.path.join(tempfile.mkdtemp(), "r.json")
        open(p, "w").write("not json")
        self.assertIsNone(player.read_result(p))


class Rules(unittest.TestCase):
    def plan(self, e, ep, **mkw):
        return sync.plan_update(e, media(**mkw), ep, TODAY)

    def test_normal_next_episode(self):
        u = self.plan(entry(progress=2), 3)
        self.assertEqual((u.progress, u.status, u.started, u.completed), (3, None, None, None))

    def test_never_lowers_progress(self):
        self.assertIsNone(self.plan(entry(progress=5), 3))
        self.assertIsNone(self.plan(entry(progress=5), 5))

    def test_first_episode_of_a_planned_or_new_anime(self):
        planned = dict(entry(progress=0, status="PLANNING"), startedAt={"year": None, "month": None, "day": None})   # AniList: no date yet
        for e in (planned, None):
            u = self.plan(e, 1)
            self.assertEqual((u.progress, u.status), (1, "CURRENT"))
            self.assertEqual(u.started, {"year": 2026, "month": 10, "day": 24})

    def test_existing_start_date_is_kept(self):
        e = entry(progress=0, status="PLANNING")                                       # already has startedAt 2024-01-01
        self.assertIsNone(sync.plan_update(e, media(), 1, TODAY).started)

    def test_paused_and_dropped_resume(self):
        for status in ("PAUSED", "DROPPED"):
            self.assertEqual(self.plan(entry(progress=4, status=status), 5).status, "CURRENT")

    def test_last_episode_completes(self):
        u = self.plan(entry(progress=11), 12, episodes=12)
        self.assertEqual((u.progress, u.status, u.completed), (12, "COMPLETED", {"year": 2026, "month": 10, "day": 24}))

    def test_unknown_episode_count_never_completes(self):
        self.assertIsNone(self.plan(entry(progress=11), 12, episodes=None).status)

    def test_rewatch_finishing_counts_a_repeat(self):
        e = entry(progress=11, status="REPEATING")
        e["repeat"] = 2
        u = self.plan(e, 12, episodes=12)
        self.assertEqual((u.status, u.repeat, u.completed), ("COMPLETED", 3, None))

    def test_completed_entries_are_left_alone(self):
        self.assertIsNone(self.plan(entry(progress=12, status="COMPLETED"), 3))

    def test_jumping_ahead(self):
        self.assertEqual(self.plan(entry(progress=2), 7).progress, 7)


class Backends(unittest.TestCase):
    def test_make_backend(self):
        self.assertIsNone(sync.make_backend(dict(CFG, sync="off", token="t"), None))
        self.assertIsNone(sync.make_backend(dict(CFG, sync="anilist", token=""), None))
        self.assertEqual(sync.make_backend(dict(CFG, sync="anilist", token="t"), object()).name, "AniList")
        self.assertEqual(sync.make_backend(dict(CFG, sync="chibi"), None).name, "chibi")

    def test_anilist_backend_passes_only_set_fields(self):
        class Api:
            def save(self, media_id, **kw):
                self.got = (media_id, kw)
        api = Api()
        sync.AniListBackend(api).apply(sync.Update(5, 3, status="CURRENT"))
        self.assertEqual(api.got, (5, {"progress": 3, "status": "CURRENT", "started": None, "completed": None, "repeat": None}))

    def test_chibi_sends_progress_only(self):
        calls = []
        def runner(cmd, **kw):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        sync.ChibiBackend("chibi", runner).apply(sync.Update(210482, 3, status="CURRENT"))
        self.assertEqual(calls, [["chibi", "update", "210482", "--progress", "3"]])

    def test_chibi_failure_is_reported(self):
        runner = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "not logged in")
        with self.assertRaises(RuntimeError) as cm:
            sync.ChibiBackend("chibi", runner).apply(sync.Update(1, 1))
        self.assertIn("not logged in", str(cm.exception))


if __name__ == "__main__":
    unittest.main()


class EarlyEnd(unittest.TestCase):
    def test_start_and_debug_log_flags(self):
        s = Stream("https://x")
        self.assertIn("--start=754", player.build_command(CFG, s, "t", "o", exe="mpv", start=754.6))
        dbg = player.build_command(dict(CFG, _debug=True), s, "t", "o", exe="mpv")
        self.assertTrue(any(c.startswith("--log-file=") and c.endswith("mpv.log") for c in dbg))
        self.assertFalse(any(c.startswith("--log-file=") for c in player.build_command(CFG, s, "t", "o", exe="mpv")))

    def test_early_flag_is_read_from_the_progress_file(self):
        def runner(cmd):
            out = [c for c in cmd if c.startswith("--script-opts=anistream-out=")][0].split("=", 2)[2]
            with open(out, "w", encoding="utf-8") as f:
                json.dump({"percent": 20.0, "position": 300, "duration": 1400, "eof": False, "early": True, "reason": "eof", "started": True}, f)
            return 0
        res = player.play(CFG, Stream("https://x"), "t", runner=runner, which=lambda e: e)
        self.assertTrue(res.early)
        self.assertFalse(res.eof)

    def test_app_offers_resume_after_an_early_end(self):
        from anistream.app import App
        calls = []
        results = [player.PlayResult(percent=20, position=300, duration=1400, early=True, started=True),
                   player.PlayResult(percent=99.9, position=1400, duration=1400, eof=True, started=True)]

        def play_fn(cfg, stream, title, start=None):
            calls.append(start)
            return results[len(calls) - 1]

        class UI:
            def warn(self, *a): pass
            def confirm(self, *a): return True
        a = App.__new__(App)
        a.cfg, a.ui, a.play_fn = {}, UI(), play_fn
        res = a._play(Stream("https://x"), "t")
        self.assertEqual(calls, [None, 297])
        self.assertTrue(res.eof)
