import io
import json

from anistream.player import PlayResult
from anistream.ui import UI


def media(mid=1, title="Dandadan", episodes=12, status="RELEASING", nxt=5, year=2024, **extra):
    m = {"id": mid, "status": status, "format": "TV", "episodes": episodes, "seasonYear": year, "isAdult": False,
         "startDate": {"year": year}, "title": {"english": title, "romaji": title}, "synonyms": [],
         "nextAiringEpisode": {"episode": nxt, "airingAt": 2_000_000_000} if nxt else None}
    m.update(extra)
    return m


def entry(mid=1, title="Dandadan", progress=2, status="CURRENT", media_status="RELEASING", **kw):
    """`status` is the status on YOUR list; `media_status` is the anime's own (RELEASING / FINISHED / ...)."""
    return {"status": status, "progress": progress, "repeat": 0, "startedAt": {"year": 2024, "month": 1, "day": 1},
            "media": media(mid, title, status=media_status, **kw)}


class ScriptedUI(UI):
    """A UI answering from a list of inputs and recording everything printed."""

    def __init__(self, answers=()):
        self.answers = list(answers)
        self.lines = []
        super().__init__(use_fzf=False, input_fn=self._input, print_fn=self.lines.append, color=False, tty=False)

    def _input(self, prompt=""):
        self.lines.append(f"<{prompt}>")
        if not self.answers:
            raise EOFError
        return self.answers.pop(0)

    def text(self):
        return "\n".join(str(x) for x in self.lines)


class FakeResponse:
    def __init__(self, body, status=200):
        self.body, self.status = body, status

    def read(self):
        return json.dumps(self.body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeOpener:
    """Stands in for urllib.request.urlopen: records requests and answers from a queue."""

    def __init__(self, *responses):
        self.responses, self.requests = list(responses), []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return FakeResponse(r)

    def last_body(self):
        return json.loads(self.requests[-1].data.decode())


def http_error(code, body=None):
    import urllib.error
    return urllib.error.HTTPError("https://graphql.anilist.co", code, "x", {}, io.BytesIO(json.dumps(body or {}).encode()))


class FakeApi:
    """The AniList client interface used by the app."""

    def __init__(self, entries=(), results=(), token="tok"):
        self.token, self._entries, self._results = token, list(entries), list(results)
        self.saved, self.fail_save = [], False
        self.server = {}                                    # media id -> your entry as the server has it

    def lists(self, username):
        return list(self._entries)

    def search(self, text):
        return list(self._results)

    def entry(self, media_id):
        for e in self._entries:
            if e["media"]["id"] == media_id:
                return e["media"], self.server.get(media_id, {k: v for k, v in e.items() if k != "media"})
        return media(media_id), self.server.get(media_id)

    def save(self, media_id, **fields):
        from anistream.anilist import AniListError
        if self.fail_save:
            raise AniListError("offline")
        self.saved.append(dict(fields, media_id=media_id))
        self.server[media_id] = dict(self.server.get(media_id) or {}, progress=fields.get("progress"),
                                     status=fields.get("status") or (self.server.get(media_id) or {}).get("status"))
        return {}

    def viewer(self):
        return {"id": 7, "name": "tester"}


class FakeEngine:
    def __init__(self, streams_by_mode=None, fail_modes=()):
        from anistream.engine import Stream
        self.state = None
        self.fail_modes = set(fail_modes)
        self.calls = []
        self.streams_by_mode = streams_by_mode or {"sub": [Stream("https://cdn/a.m3u8", "1080p", True, "anikoto", {"Referer": "https://x"})],
                                                   "dub": [Stream("https://cdn/d.m3u8", "720p", True, "anikoto2")]}

    def resolve(self, media, episode, mode, quality="best"):
        from anistream.engine import EngineError, Resolved
        self.calls.append(("resolve", media["id"], episode, mode))
        if mode in self.fail_modes:
            raise EngineError(f"anikoto: no matching entry; anikoto2: no matching entry")
        return Resolved(f"id-{mode}", "Name", "anikoto", self.streams_by_mode[mode])


class FakePlayer:
    """Returns the given PlayResults one per call."""

    def __init__(self, *results):
        self.results, self.played = list(results), []

    def __call__(self, cfg, stream, title):
        self.played.append((stream.url, title))
        return self.results.pop(0) if self.results else PlayResult(returncode=0, percent=100.0, eof=True, started=True, elapsed=1400)
