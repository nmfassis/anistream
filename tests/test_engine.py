import base64
import json
import os
import unittest

from anistream import engine as eng
from anistream.config import State
from anistream.engine import AniCliRs, EngineError, parse_links
from tests.helpers import media

KOTO = "anikoto:eyJhbmlsaXN0SWQiOiIyMTA0ODIiLCJtYWxJZCI6IjYxNDY5IiwidGl0bGUiOiJTVEVFTCBCQUxMIFJVTiBKb0pvJ3MgQml6YXJyZSBBZHZlbnR1cmUgMm5kIC0gM3JkIFNUQUdFIiwiZXBpc29kZXMiOjExfQ"
JOJO = media(210482, "STEEL BALL RUN JoJo's Bizarre Adventure 2nd - 3rd STAGE", episodes=11)


class Links(unittest.TestCase):
    def test_list_of_objects(self):
        out = json.dumps([{"url": "https://a/x.m3u8", "resolution": "1080p", "hls": True, "provider": "megaplay",
                           "headers": {"Referer": "https://r", "User-Agent": "UA"}},
                          {"url": "https://b/y.mp4", "quality": "720p"}])
        s = parse_links(out)
        self.assertEqual([x.url for x in s], ["https://a/x.m3u8", "https://b/y.mp4"])
        self.assertEqual((s[0].resolution, s[0].hls, s[0].provider, s[0].headers["Referer"]), ("1080p", True, "megaplay", "https://r"))
        self.assertIsNone(s[1].hls)

    def test_wrapped_with_shared_headers_and_subtitles(self):
        out = json.dumps({"headers": {"Referer": "https://shared"}, "links": [{"link": "https://a/x.m3u8"}],
                          "subtitles": [{"url": "https://s/en.vtt", "lang": "English"}, {"url": "https://s/thumbs.vtt", "kind": "thumbnails"}]})
        s = parse_links(out)[0]
        self.assertEqual(s.headers, {"Referer": "https://shared"})
        self.assertEqual(s.subtitles, [("https://s/en.vtt", "English")])
        self.assertTrue(s.hls)                                       # inferred from .m3u8

    def test_header_list_and_referer_key(self):
        s = parse_links(json.dumps([{"url": "https://a/x", "headers": ["Origin: https://o", "X-A: b"], "referer": "https://ref"}]))[0]
        self.assertEqual(s.headers, {"Origin": "https://o", "X-A": "b", "Referer": "https://ref"})

    def test_plain_urls_and_text(self):
        self.assertEqual([x.url for x in parse_links('["https://a/1.m3u8", "https://a/2.mp4"]')], ["https://a/1.m3u8", "https://a/2.mp4"])
        self.assertEqual([x.url for x in parse_links("best: https://a/1.m3u8\nother https://a/2.mp4 ok")], ["https://a/1.m3u8", "https://a/2.mp4"])

    def test_garbage(self):
        for text in ("", "nothing here", "[]", "{}", '[{"x": 1}]', '[{"url": "ftp://nope"}]'):
            self.assertEqual(parse_links(text), [])

    def test_quality_preference_keeps_order_otherwise(self):
        s = parse_links(json.dumps([{"url": "https://a/1", "resolution": "1080p"}, {"url": "https://a/2", "resolution": "720p"}]))
        self.assertEqual([x.url for x in eng.pick_stream_order(s, "best")], ["https://a/1", "https://a/2"])
        self.assertEqual([x.url for x in eng.pick_stream_order(s, "720p")], ["https://a/2", "https://a/1"])


class FindExe(unittest.TestCase):
    def test_path_then_default_install_folder(self):
        import tempfile
        home = tempfile.mkdtemp()
        os.makedirs(os.path.join(home, ".local", "bin"))
        self.assertEqual(eng.find_exe("ani-cli-rs", which=lambda n: "/usr/bin/ani-cli-rs", home=home), "/usr/bin/ani-cli-rs")
        self.assertIsNone(eng.find_exe("ani-cli-rs", which=lambda n: None, home=home))
        exe = os.path.join(home, ".local", "bin", "ani-cli-rs.exe")
        open(exe, "w").write("x")
        self.assertEqual(eng.find_exe("ani-cli-rs", which=lambda n: None, home=home), exe)


class Runner:
    """A scripted ani-cli-rs: maps (provider, subcommand) to (rc, out, err)."""

    def __init__(self, table):
        self.table, self.calls = table, []

    def __call__(self, cmd, timeout):
        self.calls.append(cmd)
        provider = cmd[cmd.index("--provider") + 1] if "--provider" in cmd else None
        sub = next(c for c in cmd if c in ("search", "links", "--version"))
        key = (provider, sub, cmd[cmd.index("--json") + 1]) if sub == "search" and "--json" in cmd else (provider, sub)
        for k in (key, (provider, sub), (None, sub)):
            if k in self.table:
                v = self.table[k]
                return v(cmd) if callable(v) else v
        return 1, "", "unscripted"


class Engine(unittest.TestCase):
    def test_finds_the_entry_by_its_anilist_id(self):
        out = json.dumps([{"id": KOTO, "title": "STEEL BALL RUN JoJo's Bizarre Adventure 2nd - 3rd STAGE"}])
        e = AniCliRs(runner=Runner({("anikoto", "search"): (0, out, "")}))
        self.assertEqual(e.find_in(JOJO, "sub", "anikoto")[0], KOTO)
        self.assertIn(JOJO["title"]["english"], e.runner.calls[0])           # the raw title, with its apostrophe

    def test_explicit_cli_query_can_match_a_catalog_alias_and_refresh_cache(self):
        import tempfile
        state = State(os.path.join(tempfile.mkdtemp(), "state.json"))
        state.remember_show(777, "sub", "anikoto", "anikoto:stale", "Stale entry")
        alias_sid = "anikoto:catalog-alias"
        alias_out = json.dumps([{"id": alias_sid, "title": "My Search Alias"}])
        runner = Runner({("anikoto", "search", "My Search Alias"): (0, alias_out, "")})
        e = AniCliRs(state=state, runner=runner)
        show = media(777, "Official AniList Title")

        found = e.find_in(show, "sub", "anikoto", search_query="  My   Search Alias  ")

        self.assertEqual(found, (alias_sid, "My Search Alias"))
        self.assertEqual(runner.calls[0][-1], "My Search Alias")
        self.assertEqual(State(state.path).show(777, "sub", "anikoto")["sid"], alias_sid)

    def test_same_anilist_id_does_not_override_explicitly_wrong_stage(self):
        wrong_data = {"anilistId": "210482", "malId": "61469", "title": "STEEL BALL RUN JoJo's Bizarre Adventure 1st STAGE"}
        wrong_sid = "anikoto:" + base64.urlsafe_b64encode(json.dumps(wrong_data).encode()).decode().rstrip("=")
        out = json.dumps([
            {"id": wrong_sid, "title": "STEEL BALL RUN JoJo's Bizarre Adventure 1st STAGE"},
            {"id": KOTO, "title": "STEEL BALL RUN JoJo's Bizarre Adventure 2nd - 3rd STAGE"},
        ])
        e = AniCliRs(runner=Runner({("anikoto", "search"): (0, out, "")}))

        self.assertEqual(e.find_in(JOJO, "sub", "anikoto")[0], KOTO)

    def test_falls_back_to_the_second_catalog_and_accepts_the_range_start(self):
        second = json.dumps([{"id": "anikoto2:a", "title": "Steel Ball Run: JoJo's Bizarre Adventure 2nd Stage"},
                             {"id": "anikoto2:b", "title": "Steel Ball Run: JoJo's Bizarre Adventure"}])
        e = AniCliRs(runner=Runner({("anikoto", "search"): (0, "[]", ""), ("anikoto2", "search"): (0, second, "")}))
        self.assertIsNone(e.find_in(JOJO, "sub", "anikoto"))
        self.assertEqual(e.find_in(JOJO, "sub", "anikoto2")[0], "anikoto2:a")

    def test_a_catalog_that_errors_is_not_asked_forever(self):
        e = AniCliRs(runner=Runner({(None, "search"): (1, "", "error[ACL-1004]: rate limited")}))
        with self.assertRaises(EngineError) as cm:
            e.resolve(JOJO, 3, "sub")
        self.assertIn("anikoto: the catalog is not answering", str(cm.exception))
        self.assertIn("anikoto2: the catalog is not answering", str(cm.exception))
        self.assertLessEqual(len(e.runner.calls), 4)                      # two tries per catalog, then it moves on

    def test_remembers_the_resolved_show_per_catalog(self):
        import tempfile
        state = State(os.path.join(tempfile.mkdtemp(), "state.json"))
        out = json.dumps([{"id": KOTO, "title": JOJO["title"]["english"]}])
        e = AniCliRs(state=state, runner=Runner({("anikoto", "search"): (0, out, "")}))
        e.find_in(JOJO, "sub", "anikoto")
        n = len(e.runner.calls)
        self.assertEqual(e.find_in(JOJO, "sub", "anikoto")[0], KOTO)
        self.assertEqual(len(e.runner.calls), n)                              # served from the state file
        self.assertEqual(State(state.path).show(210482, "sub", "anikoto")["sid"], KOTO)
        self.assertIsNone(State(state.path).show(210482, "sub", "anikoto2"))   # another catalog: not mixed up
        self.assertIsNone(State(state.path).show(210482, "dub", "anikoto"))

    def test_streams_and_errors(self):
        good = json.dumps([{"url": "https://a/x.m3u8", "resolution": "1080p", "headers": {"Referer": "https://r"}}])
        e = AniCliRs(runner=Runner({(None, "links"): (0, good, "")}))
        self.assertEqual(e.streams("sid", 3, "sub", "best")[0].headers["Referer"], "https://r")
        bad = AniCliRs(runner=Runner({(None, "links"): (1, "", "error[ACL-3001]: No playable sources found")}))
        with self.assertRaises(EngineError) as cm:
            bad.streams("sid", 3, "sub", "best")
        self.assertEqual(cm.exception.code, "ACL-3001")
        empty = AniCliRs(runner=Runner({(None, "links"): (0, "[]", "")}))
        with self.assertRaises(EngineError):
            empty.streams("sid", 3, "sub", "best")

    # ---- the reported failure: the first catalog has the anime but no stream ----
    def two_catalogs(self, koto_links, second_links):
        second = json.dumps([{"id": "anikoto2:a", "title": "Steel Ball Run: JoJo's Bizarre Adventure 2nd Stage"}])
        koto = json.dumps([{"id": KOTO, "title": JOJO["title"]["english"]}])
        good = json.dumps([{"url": "https://cdn/ep.m3u8", "resolution": "1080p", "provider": "megaplay"}])
        def links(cmd):
            sid = cmd[cmd.index("links") + 1]
            return koto_links if sid.startswith("anikoto:") else second_links
        return AniCliRs(runner=Runner({("anikoto", "search"): (0, koto, ""), ("anikoto2", "search"): (0, second, ""), (None, "links"): links})), good

    def test_second_catalog_is_asked_when_the_first_has_no_stream(self):
        e, good = self.two_catalogs((1, "", "error[ACL-3001]: No playable sources found"), None)
        e.runner.table[(None, "links")] = lambda cmd: ((1, "", "error[ACL-3001]: No playable sources found") if cmd[cmd.index("links") + 1].startswith("anikoto:") else (0, good, ""))
        r = e.resolve(JOJO, 3, "sub")
        self.assertEqual((r.provider, r.sid), ("anikoto2", "anikoto2:a"))
        self.assertEqual(r.streams[0].url, "https://cdn/ep.m3u8")
        asked = [c[c.index("links") + 1] for c in e.runner.calls if "links" in c]
        self.assertEqual(asked, [KOTO, "anikoto2:a"])                         # first catalog tried, then the second

    def test_every_catalog_without_a_stream_reports_each_one(self):
        e, _ = self.two_catalogs((1, "", "error[ACL-3001]: No playable sources found"), (1, "", "error[ACL-3001]: No playable sources found"))
        with self.assertRaises(EngineError) as cm:
            e.resolve(JOJO, 3, "sub")
        self.assertEqual(cm.exception.code, "ACL-3001")                        # all said the same: the app can explain it
        self.assertIn("anikoto: ACL-3001", str(cm.exception))
        self.assertIn("anikoto2: ACL-3001", str(cm.exception))

    def test_mixed_reasons_have_no_single_code(self):
        e, _ = self.two_catalogs((1, "", "error[ACL-3001]: No playable sources found"), (0, "[]", ""))
        with self.assertRaises(EngineError) as cm:
            e.resolve(JOJO, 3, "sub")
        self.assertIsNone(cm.exception.code)

    def test_a_stream_side_failure_keeps_the_cached_entry_but_other_errors_drop_it(self):
        import tempfile
        state = State(os.path.join(tempfile.mkdtemp(), "state.json"))
        e, good = self.two_catalogs((1, "", "error[ACL-3001]: x"), (0, "[]", ""))
        e.state = state
        with self.assertRaises(EngineError):
            e.resolve(JOJO, 3, "sub")
        self.assertIsNotNone(state.show(210482, "sub", "anikoto"))             # the entry is right; just no stream yet
        e.runner.table[(None, "links")] = (1, "", "error[ACL-2004]: Episode not found")
        with self.assertRaises(EngineError):
            e.resolve(JOJO, 3, "sub")
        self.assertIsNone(state.show(210482, "sub", "anikoto"))                # something else: do not trust the cache

    def test_probe_reports_each_catalog(self):
        e, good = self.two_catalogs((1, "", "error[ACL-3001]: No playable sources found"), None)
        e.runner.table[(None, "links")] = lambda cmd: ((1, "", "error[ACL-3001]: No playable sources found") if cmd[cmd.index("links") + 1].startswith("anikoto:") else (0, good, ""))
        rows = e.probe(JOJO, 3, "sub")
        self.assertEqual([r["provider"] for r in rows], ["anikoto", "anikoto2"])
        self.assertIn("ACL-3001", rows[0]["error"])
        self.assertEqual((rows[0]["entry"], len(rows[1]["streams"])), (JOJO["title"]["english"], 1))

    def test_links_command_shape(self):
        e = AniCliRs(runner=Runner({(None, "links"): (0, '[{"url": "https://a/x"}]', "")}))
        e.streams("SID", 3, "dub", "best")
        cmd = e.runner.calls[0]
        self.assertEqual(cmd[1:], ["links", "SID", "3", "--mode", "dub", "--json"])


if __name__ == "__main__":
    unittest.main()
