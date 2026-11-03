"""Whole program through the real command line: fake AniList server + fake ani-cli-rs + fake mpv (POSIX only)."""
import base64
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EID = base64.urlsafe_b64encode(json.dumps({"anilistId": "42", "malId": "1", "title": "Dandadan", "episodes": 12}).encode()).decode().rstrip("=")

MEDIA = {"id": 42, "status": "RELEASING", "format": "TV", "episodes": 12, "seasonYear": 2024, "isAdult": False,
         "startDate": {"year": 2024}, "title": {"english": "Dandadan", "romaji": "Dandadan"}, "synonyms": ["DAN DA DAN"],
         "nextAiringEpisode": {"episode": 6, "airingAt": 2_000_000_000}}

FAKE_ANI_CLI_RS = f'''#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
open(os.environ["E2E_LOG"], "a").write("ani-cli-rs " + " ".join(a) + "\\n")
if a and a[0] == "--provider": a = a[2:]
if a[0] == "--version": print("ani-cli-rs 0.9.6"); sys.exit(0)
provider = "anikoto2" if "anikoto2" in sys.argv[1:3] else "anikoto"
if a[0] == "search":
    q = a[-1]
    sid = "anikoto2:slug-dandadan" if provider == "anikoto2" else "anikoto:{EID}"
    print(json.dumps([{{"id": sid, "title": "Dandadan"}}] if q == "Dandadan" else [])); sys.exit(0)
if a[0] == "links":
    if os.environ.get("E2E_KOTO_DOWN") and a[1].startswith("anikoto:"):
        print("error[ACL-3001]: No playable sources found\\n\\nhelp: Try another provider", file=sys.stderr); sys.exit(1)
    if os.environ.get("E2E_ALL_DOWN"):
        print("error[ACL-3001]: No playable sources found", file=sys.stderr); sys.exit(1)
    print(json.dumps({{"headers": {{"Referer": "https://ref.example/"}},
                       "links": [{{"url": "https://cdn.example/ep.m3u8", "resolution": "1080p", "hls": True, "provider": "megaplay"}}],
                       "subtitles": [{{"url": "https://cdn.example/en.vtt", "lang": "English"}}]}})); sys.exit(0)
sys.exit(2)
'''

FAKE_MPV = '''#!/usr/bin/env python3
import json, os, sys
open(os.environ["E2E_LOG"], "a").write("mpv " + json.dumps(sys.argv[1:]) + "\\n")
if "--version" in sys.argv: print("mpv 0.40.0 fake"); sys.exit(0)
if "--vo=help" in sys.argv: print("Available video outputs:\\n  sixel  Sixel graphics"); sys.exit(0)
out = next(a for a in sys.argv if a.startswith("--script-opts=anistream-out=")).split("=", 2)[2]
pct = float(os.environ.get("FAKE_MPV_PERCENT", "100"))
json.dump({"percent": pct, "position": 14 * pct, "duration": 1400, "eof": pct >= 100, "started": True}, open(out, "w"))
'''


class FakeAniList(BaseHTTPRequestHandler):
    store = {}

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        q, v, store = body["query"], body.get("variables", {}), self.server.store
        auth = self.headers.get("Authorization") == "Bearer good-token"
        entry = store.get("entry", {"status": "CURRENT", "progress": 2, "repeat": 0, "startedAt": {"year": 2024, "month": 1, "day": 1}})
        if "SaveMediaListEntry" in q:
            if not auth:
                return self.reply({"errors": [{"message": "Unauthenticated"}]}, 401)
            store.setdefault("saved", []).append(v)
            entry = dict(entry, progress=v.get("progress", entry["progress"]), status=v.get("status", entry["status"]))
            store["entry"] = entry
            return self.reply({"data": {"SaveMediaListEntry": {"id": 1, "status": entry["status"], "progress": entry["progress"], "repeat": 0}}})
        if "Viewer" in q:
            return self.reply({"data": {"Viewer": {"id": 7, "name": "nmfas"}}} if auth else {"errors": [{"message": "x"}]}, 200 if auth else 401)
        if "MediaListCollection" in q:
            return self.reply({"data": {"MediaListCollection": {"lists": [{"entries": [dict(entry, media=MEDIA)]}]}}})
        if "Page(" in q:
            return self.reply({"data": {"Page": {"media": [dict(MEDIA, mediaListEntry=entry)]}}})
        if "Media(id: $id" in q:
            return self.reply({"data": {"Media": dict(MEDIA, mediaListEntry=entry if auth else None)}})
        return self.reply({"data": {"Media": {"id": 1}}})

    def reply(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@unittest.skipIf(os.name == "nt", "uses POSIX shebang scripts")
class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), FakeAniList)
        cls.server.store = {}
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.tmp = tempfile.mkdtemp()
        cls.bin = os.path.join(cls.tmp, "bin")
        os.makedirs(cls.bin)
        for name, body in (("ani-cli-rs", FAKE_ANI_CLI_RS), ("mpv", FAKE_MPV)):
            path = os.path.join(cls.bin, name)
            open(path, "w").write(body)
            os.chmod(path, 0o755)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        self.server.store.clear()
        self.home = tempfile.mkdtemp()
        self.log = os.path.join(self.home, "calls.log")

    def run_cli(self, *args, stdin="", token="good-token", **env):
        e = dict(os.environ, PATH=self.bin + os.pathsep + os.environ["PATH"], ANISTREAM_HOME=self.home, ANISTREAM_USERNAME="nmfas",
                 ANISTREAM_API_URL=f"http://127.0.0.1:{self.server.server_port}", E2E_LOG=self.log, PYTHONPATH=ROOT, NO_COLOR="1", **env)
        e.pop("ANISTREAM_CONFIG", None)
        if token:
            e["ANISTREAM_TOKEN"] = token
        else:
            e.pop("ANISTREAM_TOKEN", None)
        return subprocess.run([sys.executable, "-m", "anistream", *args], input=stdin, capture_output=True, text=True, env=e, timeout=60)

    def calls(self):
        return open(self.log).read().splitlines() if os.path.exists(self.log) else []

    def mpv_args(self):
        line = next(c for c in self.calls() if c.startswith("mpv ["))
        return json.loads(line[4:])

    def test_play_an_episode_and_sync(self):
        r = self.run_cli("play", "dandadan", "-e", "3")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(self.server.store["saved"], [{"mediaId": 42, "progress": 3}])
        args = self.mpv_args()
        self.assertEqual(args[-1], "https://cdn.example/ep.m3u8")
        self.assertIn("--referrer=https://ref.example/", args)
        self.assertIn("--sub-file=https://cdn.example/en.vtt", args)
        self.assertIn("--force-media-title=Dandadan - Episode 3", args)
        self.assertIn("ani-cli-rs links anikoto:" + EID + " 3 --mode sub --json", " ".join(self.calls()))
        self.assertIn("AniList: Dandadan → progress 3", r.stdout)

    def test_second_catalog_plays_when_the_first_has_no_stream(self):
        """The reported failure: anikoto has the anime but ACL-3001; anikoto2 must still be tried."""
        r = self.run_cli("play", "dandadan", "-e", "3", E2E_KOTO_DOWN="1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("Could not play", r.stdout)
        links = [c for c in self.calls() if " links " in c]
        self.assertEqual(len(links), 2)                                   # first catalog asked, then the second
        self.assertTrue(links[0].split(" links ")[1].startswith("anikoto:"))
        self.assertTrue(links[1].split(" links ")[1].startswith("anikoto2:"))
        self.assertEqual(self.server.store["saved"], [{"mediaId": 42, "progress": 3}])
        self.assertIn("anikoto2", r.stdout)                                # the line says which catalog it plays from

    def test_nothing_anywhere_explains_itself_per_catalog(self):
        r = self.run_cli("play", "dandadan", "-e", "3", E2E_ALL_DOWN="1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("anikoto: ACL-3001", r.stdout)
        self.assertIn("anikoto2: ACL-3001", r.stdout)
        self.assertIn("no stream for this episode yet", r.stdout)
        self.assertNotIn("saved", self.server.store)

    def test_probe_shows_each_catalog_and_plays_nothing(self):
        r = self.run_cli("probe", "dandadan", "-e", "3", E2E_KOTO_DOWN="1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("[sub] anikoto: 'Dandadan' matched, but no stream: ACL-3001", r.stdout)
        self.assertIn("[sub] anikoto2: 'Dandadan' → 1 stream(s); first: megaplay 1080p HLS @ cdn.example", r.stdout)
        self.assertFalse([c for c in self.calls() if c.startswith("mpv [")])        # nothing was played
        self.assertNotIn("saved", self.server.store)

    def test_probe_fails_when_no_catalog_has_a_stream(self):
        self.assertEqual(self.run_cli("probe", "dandadan", "-e", "3", E2E_ALL_DOWN="1").returncode, 1)

    def test_the_catalog_is_found_through_its_anilist_id(self):
        self.run_cli("play", "dandadan", "-e", "3")
        searches = [c for c in self.calls() if " search " in c]
        self.assertGreaterEqual(len(searches), 2)                      # typed query first, AniList title fallback next
        self.assertIn("--json dandadan", searches[0])
        self.assertTrue(any("--json Dandadan" in c for c in searches))

    def test_no_sync_flag_and_missing_token(self):
        self.run_cli("--no-sync", "play", "dandadan", "-e", "3")
        self.assertNotIn("saved", self.server.store)
        r = self.run_cli("play", "dandadan", "-e", "3", token="")
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("saved", self.server.store)

    def test_sixel_mode(self):
        self.run_cli("--player", "sixel", "play", "dandadan", "-e", "3")
        self.assertIn("--vo=sixel", self.mpv_args())

    def test_half_watched_asks_first(self):
        no = self.run_cli("play", "dandadan", "-e", "3", stdin="n\n", FAKE_MPV_PERCENT="50")
        self.assertIn("You watched 50%", no.stdout)
        self.assertNotIn("saved", self.server.store)
        yes = self.run_cli("play", "dandadan", "-e", "3", stdin="y\n", FAKE_MPV_PERCENT="50")
        self.assertEqual(self.server.store["saved"], [{"mediaId": 42, "progress": 3}])

    def test_interactive_session_through_the_menus(self):
        r = self.run_cli(stdin="1\n1\n5\nb\nb\n")                    # Continue watching → Dandadan → (plays Ep 3) → Back → Back → Back
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertIn("▶ Ep 3 ready", r.stdout)
        self.assertEqual(self.server.store["saved"][0]["progress"], 3)

    def test_doctor_all_green(self):
        r = self.run_cli("doctor")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for expect in ("mpv:", "ani-cli-rs: ani-cli-rs 0.9.6", "AniList: reachable", "logged in as nmfas"):
            self.assertIn(expect, r.stdout)

    def test_doctor_names_what_is_missing(self):
        e = dict(os.environ, PATH="/nonexistent", ANISTREAM_HOME=self.home, ANISTREAM_API_URL=f"http://127.0.0.1:{self.server.server_port}", PYTHONPATH=ROOT)
        r = subprocess.run([sys.executable, "-m", "anistream", "doctor"], capture_output=True, text=True, env=e, timeout=60)
        self.assertEqual(r.returncode, 1)
        self.assertIn("winget install mpv.mpv", r.stdout)
        self.assertIn("ani-cli-rs/wiki/Installation", r.stdout)

    def test_config_command(self):
        self.run_cli("config", "mode", "dub")
        self.run_cli("config", "threshold", "90")
        shown = self.run_cli("config").stdout
        self.assertIn('mode = "dub"', shown)
        self.assertIn("threshold = 90", shown)
        self.assertEqual(self.run_cli("config", "nope", "1").returncode, 2)
        self.assertIn("token = (set)", self.run_cli("config").stdout)


if __name__ == "__main__":
    unittest.main()
