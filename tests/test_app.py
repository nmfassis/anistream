import os
import tempfile
import unittest
from datetime import date

from anistream import app as appmod
from anistream.app import App, countdown, released, title_of
from anistream.config import DEFAULTS, State, load_config
from anistream.engine import Stream
from anistream.player import PlayResult
from anistream.sync import AniListBackend
from tests.helpers import FakeApi, FakeEngine, FakePlayer, ScriptedUI, entry, media

WATCHED = PlayResult(returncode=0, percent=100.0, eof=True, started=True, elapsed=1400)
HALF = PlayResult(returncode=0, percent=50.0, started=True, elapsed=700)
BARELY = PlayResult(returncode=0, percent=10.0, started=True, elapsed=100)
UNKNOWN = PlayResult(returncode=0, percent=None, started=False, elapsed=1400)
CLOSED = PlayResult(returncode=1, percent=None, started=False, elapsed=1)


def build(answers, entries=(), results=(), players=(), engine=None, sync=True, token="tok", **cfg_over):
    cfg = dict(DEFAULTS, username="nmfas", token=token)
    cfg.update(cfg_over)
    ui, api = ScriptedUI(answers), FakeApi(entries, results, token)
    state = State(os.path.join(tempfile.mkdtemp(), "state.json"))
    player = FakePlayer(*players)
    a = App(cfg, ui, api, engine or FakeEngine(), player, AniListBackend(api) if sync else None, state,
            now=lambda: 1_999_900_000, today=date(2026, 10, 24))
    return a, ui, api, player


class Helpers(unittest.TestCase):
    def test_title_and_availability(self):
        m = media(title="Dandadan")
        self.assertEqual(title_of(m), "Dandadan")
        self.assertEqual(title_of({"id": 3, "title": {"english": None, "romaji": "Romaji"}}), "Romaji")
        self.assertEqual(title_of({"id": 3, "title": {}}), "AniList #3")
        self.assertEqual(released(media(status="RELEASING", nxt=5)), 4)
        self.assertEqual(released(media(status="NOT_YET_RELEASED", nxt=None)), 0)
        self.assertEqual(released(media(status="FINISHED", episodes=12, nxt=None)), 12)
        self.assertIsNone(released(media(status="FINISHED", episodes=None, nxt=None)))

    def test_countdown(self):
        m = media(nxt=5)                                        # airs at 2_000_000_000
        self.assertEqual(countdown(m, now=2_000_000_000 - 90061), "1d 1h")
        self.assertEqual(countdown(m, now=2_000_000_000 - 7500), "2h 5m")
        self.assertEqual(countdown(m, now=2_000_000_000 - 600), "10m")
        self.assertEqual(countdown(m, now=2_000_000_001), "any moment")

    def test_labels_and_order(self):
        a, *_ = build([])
        ready, waiting = entry(1, "Ready", progress=2, nxt=5), entry(2, "Waiting", progress=4, nxt=5)
        self.assertIn("▶ Ep 3 ready", a.entry_label(ready))
        self.assertIn("Ep 5 airs in", a.entry_label(waiting))
        self.assertIn("finished", a.entry_label(entry(3, "Done", progress=12, media_status="FINISHED", nxt=None)))
        self.assertEqual([e["media"]["id"] for e in a.sorted_entries([waiting, ready])], [1, 2])


class Watching(unittest.TestCase):
    def test_continue_plays_the_next_episode_and_syncs(self):
        a, ui, api, player = build(["1", "1", "5", "b", "b"], entries=[entry(1, "Dandadan", progress=2)], players=[WATCHED])
        a.home()
        self.assertEqual(len(player.played), 1)
        self.assertIn("Episode 3", player.played[0][1])
        self.assertEqual(api.saved, [{"media_id": 1, "progress": 3, "status": None, "started": None, "completed": None, "repeat": None}])
        self.assertIn("AniList: Dandadan → progress 3", ui.text())

    def test_below_threshold_asks_and_respects_no(self):
        a, ui, api, _ = build(["1", "1", "n", "5", "b", "b"], entries=[entry(1, progress=2)], players=[HALF])
        a.home()
        self.assertIn("You watched 50% of Ep 3", ui.text())
        self.assertEqual(api.saved, [])

    def test_below_threshold_yes_records(self):
        a, _, api, _ = build(["1", "1", "y", "5", "b", "b"], entries=[entry(1, progress=2)], players=[HALF])
        a.home()
        self.assertEqual(api.saved[0]["progress"], 3)

    def test_barely_watched_is_not_even_asked(self):
        a, ui, api, _ = build(["1", "1", "5", "b", "b"], entries=[entry(1, progress=2)], players=[BARELY])
        a.home()
        self.assertEqual(api.saved, [])
        self.assertNotIn("Mark it as watched", ui.text())

    def test_unknown_progress_asks(self):
        a, ui, api, _ = build(["1", "1", "y", "5", "b", "b"], entries=[entry(1, progress=2)], players=[UNKNOWN])
        a.home()
        self.assertIn("Did you finish Ep 3?", ui.text())
        self.assertEqual(api.saved[0]["progress"], 3)

    def test_sync_off_plays_without_prompts_or_saves(self):
        a, ui, api, player = build(["1", "1", "4", "b", "b"], entries=[entry(1, progress=2)], players=[WATCHED], sync=False)
        a.home()
        self.assertEqual((len(player.played), api.saved), (1, []))
        self.assertIn("sync: off", ui.text())
        self.assertNotIn("Mark Ep", ui.text())

    def test_last_episode_completes_the_entry(self):
        a, _, api, _ = build(["1", "1", "5", "b", "b"], entries=[entry(1, progress=11, episodes=12, nxt=None, media_status="FINISHED")], players=[WATCHED])
        a.home()
        self.assertEqual((api.saved[0]["progress"], api.saved[0]["status"]), (12, "COMPLETED"))

    def test_skipping_ahead_needs_confirmation(self):
        # pick episode 7 while at 2: asked about skipping, answer no
        a, ui, api, _ = build(["1", "1", "3", "7", "n", "5", "b", "b"], entries=[entry(1, progress=2, nxt=None, media_status="FINISHED")],
                              players=[WATCHED, WATCHED])
        a.home()
        self.assertIn("skipping 3", ui.text())
        self.assertEqual([s["progress"] for s in api.saved], [3])

    def test_next_episode_and_replay(self):
        a, _, api, player = build(["1", "1", "1", "5", "b", "b"], entries=[entry(1, progress=2, nxt=None, media_status="FINISHED")], players=[WATCHED, WATCHED])
        a.home()
        self.assertEqual([p[1].endswith(f"Episode {n}") for p, n in zip(player.played, (3, 4))], [True, True])
        self.assertEqual([s["progress"] for s in api.saved], [3, 4])

    def test_episode_not_out_yet(self):
        a, ui, _, player = build(["1", "1", "n", "b", "b"], entries=[entry(1, progress=4, nxt=5)])
        a.home()
        self.assertEqual(player.played, [])
        self.assertIn("Ep 5 is not out yet (airs in", ui.text())

    def test_finished_anime_offers_a_rewatch(self):
        a, ui, _, player = build(["1", "1", "2", "5", "b", "b"], entries=[entry(1, progress=12, episodes=12, nxt=None, media_status="FINISHED")], players=[WATCHED])
        a.home()
        self.assertIn("finished on your list", ui.text())
        self.assertTrue(player.played[0][1].endswith("Episode 2"))


class Resilience(unittest.TestCase):
    def test_other_version_when_the_preferred_one_is_missing(self):
        eng = FakeEngine(fail_modes=["sub"])
        a, ui, _, player = build(["1", "1", "5", "b", "b"], entries=[entry(1, progress=2)], players=[WATCHED], engine=eng)
        a.home()
        self.assertIn("sub: anikoto: no matching entry", ui.text())
        self.assertEqual(player.played[0][0], "https://cdn/d.m3u8")                   # the dub stream

    def test_no_fallback_when_disabled(self):
        a, ui, _, player = build(["1", "1", "3", "b", "b"], entries=[entry(1, progress=2)], engine=FakeEngine(fail_modes=["sub"]), mode_fallback=False)
        a.home()
        self.assertEqual(player.played, [])
        self.assertIn("Could not play Ep 3", ui.text())

    def test_every_version_fails_with_a_hint(self):
        from anistream.engine import EngineError
        class Dead(FakeEngine):
            def resolve(self, *a, **k):
                raise EngineError("anikoto: ACL-3001 No playable sources found; anikoto2: ACL-3001 No playable sources found", code="ACL-3001")
        a, ui, _, _ = build(["1", "1", "3", "b", "b"], entries=[entry(1, progress=2)], engine=Dead())
        a.home()
        self.assertIn("have no stream for this episode yet", ui.text())

    def test_a_stream_that_closes_at_once_is_followed_by_the_next(self):
        from anistream.engine import Stream
        eng = FakeEngine({"sub": [Stream("https://cdn/bad"), Stream("https://cdn/good")], "dub": []})
        a, ui, _, player = build(["1", "1", "5", "b", "b"], entries=[entry(1, progress=2)], players=[CLOSED, WATCHED], engine=eng)
        a.home()
        self.assertEqual([p[0] for p in player.played], ["https://cdn/bad", "https://cdn/good"])
        self.assertIn("closed right away", ui.text())

    def test_offline_update_is_queued_then_sent_later(self):
        a, ui, api, _ = build(["1", "1", "5", "b", "b"], entries=[entry(1, progress=2)], players=[WATCHED])
        api.fail_save = True
        a.home()
        self.assertEqual(a.state.pending(), [{"media_id": 1, "episode": 3}])
        self.assertIn("Saved; it will be retried", ui.text())
        api.fail_save = False
        a.flush_pending()
        self.assertEqual([s["progress"] for s in api.saved], [3])
        self.assertEqual(a.state.pending(), [])

    def test_a_queued_update_never_lowers_progress(self):
        a, _, api, _ = build([], entries=[entry(1, progress=2)])
        a.state.queue(1, 3)
        api.server[1] = {"status": "CURRENT", "progress": 8, "startedAt": {"year": 2024}}      # watched further elsewhere
        a.flush_pending()
        self.assertEqual(api.saved, [])
        self.assertEqual(a.state.pending(), [])

    def test_queue_survives_while_offline(self):
        a, ui, api, _ = build([], entries=[entry(1, progress=2)])
        a.state.queue(1, 3)
        api.fail_save = True
        a.flush_pending()
        self.assertEqual(len(a.state.pending()), 1)
        self.assertIn("stay queued", ui.text())

    def test_after_a_failure_the_menu_offers_retry_not_next_episode(self):
        a, ui, _, player = build(["1", "1", "1", "3", "b", "b"], entries=[entry(1, progress=2)],
                                 engine=FakeEngine(fail_modes=["sub", "dub"]))
        a.home()                                           # "1" = Try again (fails again), "3" = Back
        self.assertNotIn("Next episode", ui.text())
        self.assertGreaterEqual(ui.text().count("Try again"), 2)

    def test_player_missing_stops_cleanly(self):
        from anistream.player import PlayerError
        def no_mpv(cfg, stream, title):
            raise PlayerError("'mpv' was not found. Install mpv: winget install mpv.mpv")
        a, ui, _, _ = build(["1", "1", "3", "b", "b"], entries=[entry(1, progress=2)])
        a.play_fn = no_mpv
        a.home()
        self.assertIn("winget install mpv.mpv", ui.text())


class Search(unittest.TestCase):
    def test_search_play_and_add_to_the_list(self):
        found = dict(media(77, "Frieren", episodes=28, status="FINISHED", nxt=None), mediaListEntry=None)
        a, ui, api, player = build(["3", "frieren", "1", "5", "b", "b"], entries=[], results=[found], players=[WATCHED])
        a.home()
        self.assertIn("added to Watching when you finish the first episode", ui.text())
        self.assertEqual((api.saved[0]["media_id"], api.saved[0]["progress"], api.saved[0]["status"]), (77, 1, "CURRENT"))
        self.assertEqual(api.saved[0]["started"], {"year": 2026, "month": 10, "day": 24})

    def test_results_show_what_is_already_on_your_list(self):
        found = dict(media(5, "Dandadan"), mediaListEntry={"status": "CURRENT", "progress": 4})
        a, ui, *_ = build(["3", "dan", "b", "b"], results=[found])
        a.home()
        self.assertIn("on your list: Current 4", ui.text())


class Settings(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "config.json")
        os.environ["ANISTREAM_CONFIG"] = self.path
        self.addCleanup(os.environ.pop, "ANISTREAM_CONFIG", None)

    def test_toggles_are_saved(self):
        a, *_ = build(["4", "1", "2", "5", "b", "b"])           # Settings: version, player, titles, back
        a.home()
        saved = load_config(self.path)
        self.assertEqual((saved["mode"], saved["player_mode"], saved["title_lang"]), ("dub", "sixel", "romaji"))

    def test_threshold_is_validated(self):
        a, *_ = build(["4", "4", "250", "b", "b"])
        a.home()
        self.assertEqual(a.cfg["threshold"], 85)

    def test_first_run_asks_for_the_username(self):
        a, ui, *_ = build(["nmfas", "n", "b"], username="")
        a.cfg["username"] = ""
        a.home()
        self.assertEqual(load_config(self.path)["username"], "nmfas")
        self.assertIn("Welcome to anistream", ui.text())


class Auth(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "config.json")
        os.environ["ANISTREAM_CONFIG"] = self.path
        self.addCleanup(os.environ.pop, "ANISTREAM_CONFIG", None)

    def test_connect(self):
        a, ui, api, _ = build(["12345", "  secret-token  "], sync=False, token="")
        opened = []
        a.open_url = opened.append
        a.auth()
        self.assertEqual(a.api.token, "secret-token")
        self.assertIn("client_id=12345&response_type=token", opened[0])
        saved = load_config(self.path)
        self.assertEqual((saved["token"], saved["username"], saved["client_id"]), ("secret-token", "tester", "12345"))
        self.assertEqual(a.backend.name, "AniList")
        self.assertIn("Connected as tester", ui.text())

    def test_bad_client_id_and_bad_token(self):
        a, ui, api, _ = build(["abc"], sync=False, token="")
        a.auth()
        self.assertIsNone(a.backend)
        self.assertIn("client ID is a number", ui.text())
        from anistream.anilist import AniListError
        b, ui2, api2, _ = build(["12345", "wrong"], sync=False, token="")
        b.open_url = lambda u: None
        def bad():
            raise AniListError("AniList rejected the token")
        api2.viewer = bad
        b.auth()
        self.assertIsNone(b.backend)
        self.assertEqual(b.api.token, "")
        self.assertIn("did not work", ui2.text())


if __name__ == "__main__":
    unittest.main()
