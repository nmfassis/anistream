"""AniList GraphQL client (standard library only). Reading lists needs no token; saving progress does."""
import json
import os
import urllib.error
import urllib.request

API_URL = os.environ.get("ANISTREAM_API_URL") or "https://graphql.anilist.co"     # the override exists for tests
USER_AGENT = "anistream/0.1 (+terminal anime streamer)"

MEDIA_FIELDS = """
  id
  status
  format
  episodes
  seasonYear
  isAdult
  startDate { year }
  title { english romaji }
  synonyms
  nextAiringEpisode { episode airingAt }
"""

ENTRY_FIELDS = "status progress repeat startedAt { year month day }"

LISTS_QUERY = """
query ($user: String) {
  MediaListCollection(userName: $user, type: ANIME, status_in: [CURRENT, REPEATING, PLANNING]) {
    lists { entries { %s media { %s } } }
  }
}
""" % (ENTRY_FIELDS, MEDIA_FIELDS)

SEARCH_QUERY = """
query ($q: String) {
  Page(perPage: 15) {
    media(search: $q, type: ANIME, sort: SEARCH_MATCH) { %s mediaListEntry { %s } }
  }
}
""" % (MEDIA_FIELDS, ENTRY_FIELDS)

ENTRY_QUERY = """
query ($id: Int) { Media(id: $id, type: ANIME) { %s mediaListEntry { %s } } }
""" % (MEDIA_FIELDS, ENTRY_FIELDS)

VIEWER_QUERY = "query { Viewer { id name } }"

SAVE_MUTATION = """
mutation ($mediaId: Int, $progress: Int, $status: MediaListStatus, $startedAt: FuzzyDateInput,
          $completedAt: FuzzyDateInput, $repeat: Int) {
  SaveMediaListEntry(mediaId: $mediaId, progress: $progress, status: $status, startedAt: $startedAt,
                     completedAt: $completedAt, repeat: $repeat) {
    id status progress repeat
  }
}
"""


class AniListError(Exception):
    pass


class AniList:
    def __init__(self, token="", opener=None, timeout=30):
        self.token = (token or "").strip()
        self.opener = opener or urllib.request.urlopen     # injectable for tests
        self.timeout = timeout

    def _post(self, query, variables=None, auth=False):
        headers = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": USER_AGENT}
        if auth or self.token:
            if not self.token:
                raise AniListError("This needs an AniList token (run: anistream auth).")
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(API_URL, data=json.dumps({"query": query, "variables": variables or {}}).encode("utf-8"),
                                     headers=headers)
        try:
            with self.opener(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                body = json.loads(e.read().decode("utf-8"))
                detail = "; ".join(x.get("message", "") for x in body.get("errors", []))
            except Exception:
                pass
            if e.code == 429:
                raise AniListError("AniList rate limit reached, try again in a minute.")
            if e.code in (401, 403):
                raise AniListError("AniList rejected the token (expired or wrong). Run: anistream auth")
            raise AniListError(f"AniList error {e.code}: {detail or e.reason}")
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise AniListError(f"Cannot reach AniList: {getattr(e, 'reason', e)}")
        if body.get("errors"):
            raise AniListError("; ".join(x.get("message", "?") for x in body["errors"]))
        return body.get("data") or {}

    # ------------------------------------------------------------------ reads
    def ping(self):
        """True when AniList answers (a tiny public query)."""
        self._post("query { Media(id: 1, type: ANIME) { id } }")
        return True

    def viewer(self):
        data = self._post(VIEWER_QUERY, auth=True).get("Viewer")
        if not data:
            raise AniListError("AniList did not return your profile.")
        return data

    def lists(self, username):
        """Watching + rewatching + planning entries, one per anime: [{status, progress, repeat, startedAt, media}]."""
        data = self._post(LISTS_QUERY, {"user": username})
        collection = data.get("MediaListCollection")
        if collection is None:
            raise AniListError(f"AniList has no user called '{username}'.")
        seen, out = set(), []
        for lst in collection.get("lists") or []:
            for entry in lst.get("entries") or []:
                mid = (entry.get("media") or {}).get("id")
                if mid is not None and mid not in seen:
                    seen.add(mid)
                    out.append(entry)
        return out

    def search(self, text):
        data = self._post(SEARCH_QUERY, {"q": text})
        return (data.get("Page") or {}).get("media") or []

    def entry(self, media_id):
        """(media, your list entry or None). The entry is only filled in when a token is set."""
        media = self._post(ENTRY_QUERY, {"id": int(media_id)}).get("Media") or {}
        entry = media.pop("mediaListEntry", None)
        return media, entry

    # ----------------------------------------------------------------- writes
    def save(self, media_id, progress=None, status=None, started=None, completed=None, repeat=None):
        """Only the fields passed are changed (AniList leaves the others, like notes and scores, alone)."""
        variables = {"mediaId": int(media_id)}
        for key, value in (("progress", progress), ("status", status), ("startedAt", started),
                           ("completedAt", completed), ("repeat", repeat)):
            if value is not None:
                variables[key] = value
        return self._post(SAVE_MUTATION, variables, auth=True).get("SaveMediaListEntry") or {}
