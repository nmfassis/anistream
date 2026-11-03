import os
import tempfile
import unittest
from pathlib import Path

from anistream import config
from anistream.ui import Quit, UI
from tests.helpers import ScriptedUI


class Config(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "config.json")
        self.env = dict(os.environ)
        for k in ("ANISTREAM_TOKEN", "ANISTREAM_USERNAME"):
            os.environ.pop(k, None)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(self.env)))

    def test_defaults_and_roundtrip(self):
        cfg = config.load_config(self.path)
        self.assertEqual(cfg["mode"], "sub")
        cfg.update(mode="dub", username="nmfas", token="secret")
        config.save_config(cfg, self.path)
        again = config.load_config(self.path)
        self.assertEqual((again["mode"], again["username"], again["token"]), ("dub", "nmfas", "secret"))
        self.assertNotIn("threshold", open(self.path).read())              # defaults are not written

    def test_unknown_keys_and_corrupt_files_are_ignored(self):
        Path(self.path).write_text('{"mode": "dub", "bogus": 1}')
        self.assertEqual(config.load_config(self.path)["mode"], "dub")
        self.assertNotIn("bogus", config.load_config(self.path))
        Path(self.path).write_text("{oops")
        self.assertEqual(config.load_config(self.path)["mode"], "sub")

    def test_token_from_the_environment_is_never_written(self):
        os.environ["ANISTREAM_TOKEN"] = " envtoken "
        cfg = config.load_config(self.path)
        self.assertEqual(cfg["token"], "envtoken")
        config.save_config(cfg, self.path)
        self.assertNotIn("envtoken", open(self.path).read())

    @unittest.skipIf(os.name == "nt", "POSIX permissions")
    def test_config_file_is_private(self):
        config.save_config(dict(config.DEFAULTS, token="t"), self.path)
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)

    def test_state_remembers_and_queues(self):
        p = os.path.join(self.dir, "state.json")
        s = config.State(p)
        s.remember_show(5, "sub", "anikoto", "sid", "Name")
        s.queue(5, 3)
        s.queue(5, 3)
        again = config.State(p)
        self.assertEqual(again.show(5, "sub", "anikoto")["sid"], "sid")
        self.assertIsNone(again.show(5, "sub", "anikoto2"))
        self.assertEqual(again.pending(), [{"media_id": 5, "episode": 3}])
        again.clear_pending({"media_id": 5, "episode": 3})
        again.forget_show(5, "sub", "anikoto")
        self.assertEqual((config.State(p).pending(), config.State(p).show(5, "sub", "anikoto")), ([], None))

    def test_paths_follow_the_override(self):
        os.environ["ANISTREAM_HOME"] = self.dir
        self.assertEqual(config.config_dir(), Path(self.dir))
        self.assertEqual(config.state_path(), Path(self.dir) / "state.json")


class Menus(unittest.TestCase):
    ITEMS = ["Dandadan  [2/12]", "Frieren  [28/28]", "Apothecary Diaries  [3/24]"]

    def test_number(self):
        self.assertEqual(ScriptedUI(["2"]).pick("t", self.ITEMS), 1)

    def test_filter_then_number(self):
        ui = ScriptedUI(["a", "3"])                    # 'a' matches two items, then choose by their original number
        self.assertEqual(ui.pick("t", self.ITEMS), 2)

    def test_single_filter_match_is_chosen(self):
        self.assertEqual(ScriptedUI(["frier"]).pick("t", self.ITEMS), 1)

    def test_back_default_and_quit(self):
        self.assertIsNone(ScriptedUI(["b"]).pick("t", self.ITEMS))
        self.assertEqual(ScriptedUI([""]).pick("t", self.ITEMS, default=0), 0)
        with self.assertRaises(Quit):
            ScriptedUI(["q"]).pick("t", self.ITEMS)
        with self.assertRaises(Quit):
            ScriptedUI([]).pick("t", self.ITEMS)         # input closed

    def test_bad_input_asks_again(self):
        ui = ScriptedUI(["99", "xyz", "1"])
        self.assertEqual(ui.pick("t", self.ITEMS), 0)
        self.assertIn("No such number", ui.text())
        self.assertIn("Nothing matches", ui.text())

    def test_confirm(self):
        self.assertTrue(ScriptedUI(["y"]).confirm("?"))
        self.assertFalse(ScriptedUI(["n"]).confirm("?", True))
        self.assertTrue(ScriptedUI([""]).confirm("?", True))
        self.assertTrue(ScriptedUI(["maybe", "s"]).confirm("?"))

    def test_fzf_selection_and_cancel(self):
        import subprocess
        def runner(cmd, input=None, **kw):
            runner.sent = input
            return subprocess.CompletedProcess(cmd, 0, "1\tFrieren  [28/28]\n", "")
        ui = UI(use_fzf=True, which=lambda n: "/usr/bin/fzf", runner=runner, tty=True, color=False)
        self.assertEqual(ui.pick("t", self.ITEMS), 1)
        self.assertIn("2\tApothecary", runner.sent)
        cancel = lambda cmd, input=None, **kw: subprocess.CompletedProcess(cmd, 130, "", "")
        self.assertIsNone(UI(use_fzf=True, which=lambda n: "/x", runner=cancel, tty=True, color=False).pick("t", self.ITEMS))

    def test_fzf_is_skipped_without_a_terminal_or_binary(self):
        self.assertFalse(UI(use_fzf=True, which=lambda n: "/x", tty=False).use_fzf)
        self.assertFalse(UI(use_fzf=True, which=lambda n: None, tty=True).use_fzf)


if __name__ == "__main__":
    unittest.main()
