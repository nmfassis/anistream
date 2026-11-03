import json
import unittest

from anistream.anilist import AniList, AniListError
from tests.helpers import FakeOpener, entry, http_error, media


class Client(unittest.TestCase):
    def test_lists_flatten_and_dedupe_custom_lists(self):
        e = entry(1)
        body = {"data": {"MediaListCollection": {"lists": [{"entries": [e]}, {"entries": [e, entry(2, "B")]}]}}}
        api = AniList(opener=FakeOpener(body))
        self.assertEqual([x["media"]["id"] for x in api.lists("nmfas")], [1, 2])

    def test_unknown_user(self):
        api = AniList(opener=FakeOpener({"data": {"MediaListCollection": None}}))
        with self.assertRaises(AniListError) as cm:
            api.lists("nobody")
        self.assertIn("no user called 'nobody'", str(cm.exception))

    def test_lists_send_the_token_only_when_there_is_one(self):
        op = FakeOpener({"data": {"MediaListCollection": {"lists": []}}}, {"data": {"MediaListCollection": {"lists": []}}})
        AniList(opener=op).lists("a")
        self.assertNotIn("Authorization", {k.title(): v for k, v in op.requests[0].headers.items()})
        AniList("tok", opener=op).lists("a")
        self.assertEqual({k.title(): v for k, v in op.requests[1].headers.items()}["Authorization"], "Bearer tok")

    def test_save_sends_only_the_fields_given(self):
        op = FakeOpener({"data": {"SaveMediaListEntry": {"id": 9, "status": "CURRENT", "progress": 3}}})
        AniList("tok", opener=op).save(42, progress=3)
        self.assertEqual(op.last_body()["variables"], {"mediaId": 42, "progress": 3})       # nothing else is touched

    def test_save_full_update(self):
        op = FakeOpener({"data": {"SaveMediaListEntry": {}}})
        AniList("tok", opener=op).save(42, progress=12, status="COMPLETED", completed={"year": 2026, "month": 10, "day": 24})
        v = op.last_body()["variables"]
        self.assertEqual((v["status"], v["progress"], v["completedAt"]["day"]), ("COMPLETED", 12, 24))

    def test_save_needs_a_token(self):
        with self.assertRaises(AniListError):
            AniList("", opener=FakeOpener()).save(1, progress=1)

    def test_http_errors_become_readable(self):
        for code, text in ((401, "rejected the token"), (429, "rate limit"), (500, "AniList error 500")):
            with self.assertRaises(AniListError) as cm:
                AniList("t", opener=FakeOpener(http_error(code))).lists("a")
            self.assertIn(text, str(cm.exception))

    def test_graphql_errors_and_network(self):
        with self.assertRaises(AniListError) as cm:
            AniList(opener=FakeOpener({"errors": [{"message": "bad thing"}]})).search("x")
        self.assertIn("bad thing", str(cm.exception))
        import urllib.error
        with self.assertRaises(AniListError) as cm:
            AniList(opener=FakeOpener(urllib.error.URLError("no route"))).search("x")
        self.assertIn("Cannot reach AniList", str(cm.exception))

    def test_entry_splits_media_and_list_entry(self):
        m = dict(media(5), mediaListEntry={"status": "PLANNING", "progress": 0})
        got_media, got_entry = AniList("t", opener=FakeOpener({"data": {"Media": m}})).entry(5)
        self.assertNotIn("mediaListEntry", got_media)
        self.assertEqual(got_entry["status"], "PLANNING")

    def test_viewer(self):
        self.assertEqual(AniList("t", opener=FakeOpener({"data": {"Viewer": {"id": 1, "name": "me"}}})).viewer()["name"], "me")


if __name__ == "__main__":
    unittest.main()


class SubtitledSequel(unittest.TestCase):
    def test_franchise_entry_is_not_accepted_for_a_subtitled_sequel(self):
        from anistream import matching as m
        media = {"id": 1, "title": {"english": "JoJo's Bizarre Adventure: Steel Ball Run", "romaji": "JoJo no Kimyou na Bouken: Steel Ball Run"}, "synonyms": []}
        titles = m.all_titles(media)
        self.assertFalse(m.result_match("JoJo's Bizarre Adventure (2012)", titles)[0])
        self.assertFalse(m.result_match("JoJo's Bizarre Adventure", titles)[0])
        self.assertTrue(m.result_match("JoJo's Bizarre Adventure: Steel Ball Run", titles)[0])
        self.assertTrue(m.result_match("Steel Ball Run", titles)[0])


class CombinedStageAcrossCatalogs(unittest.TestCase):
    def test_combined_and_first_stage_names_merge_regardless_of_order(self):
        from anistream import matching as m
        a = {"provider": "anikoto", "sid": "x", "name": "STEEL BALL RUN JoJo's Bizarre Adventure 2nd - 3rd STAGE", "names": ["STEEL BALL RUN JoJo's Bizarre Adventure 2nd - 3rd STAGE"]}
        b = {"provider": "anikoto2", "sid": "y", "name": "Steel Ball Run: JoJo's Bizarre Adventure 2nd Stage", "names": ["Steel Ball Run: JoJo's Bizarre Adventure 2nd Stage"]}
        for order in ([a, b], [b, a]):
            groups = m.group_catalog_results(order)
            self.assertEqual(len(groups), 1)
            self.assertEqual({r["provider"] for r in groups[0]["matches"]}, {"anikoto", "anikoto2"})
