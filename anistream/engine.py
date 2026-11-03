"""ani-cli-rs adapter: find the catalog entry for an AniList anime and resolve playable stream links.

Written against ani-cli-rs's documented scriptable commands (search / links --json). The `links` JSON field names are not
documented in detail, so the parser accepts several spellings; `anistream doctor` shows what it understood.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

from . import matching as m


class EngineError(Exception):
    """A readable failure (provider has no stream, ani-cli-rs missing, ...)."""

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


# ani-cli-rs error codes that mean "this catalog has no working stream right now", not "the cached entry is wrong"
STREAM_SIDE_CODES = {"ACL-3001", "ACL-3003", "ACL-1004"}


class Resolved:
    def __init__(self, sid, name, provider, streams):
        self.sid, self.name, self.provider, self.streams = sid, name, provider, streams


class Stream:
    def __init__(self, url, resolution=None, hls=None, provider=None, headers=None, subtitles=None):
        self.url = url
        self.resolution = resolution
        self.hls = hls
        self.provider = provider
        self.headers = headers or {}
        self.subtitles = subtitles or []          # [(url, label)]

    def label(self):
        bits = [str(x) for x in (self.provider, self.resolution, "HLS" if self.hls else None) if x]
        return " ".join(bits) or "stream"

    def __repr__(self):
        return f"Stream({self.label()!r}, {self.url[:48]!r}...)"


# --------------------------------------------------------------------------- parsing links
_URL_KEYS = ("url", "link", "src", "file", "stream_url", "streamUrl", "playlist", "href")
_RES_KEYS = ("resolution", "quality", "height", "label", "res")
_HLS_KEYS = ("hls", "is_hls", "isHls", "m3u8")
_PROV_KEYS = ("provider", "server", "source", "name")
_HEAD_KEYS = ("headers", "request_headers", "requestHeaders", "http_headers", "httpHeaders")
_SUB_KEYS = ("subtitles", "subs", "captions", "tracks", "subtitle")
_LIST_KEYS = ("links", "sources", "streams", "results", "data", "items")
_IS_URL = re.compile(r"^https?://", re.I)


def _first(item, keys):
    for k in keys:
        if item.get(k) not in (None, "", [], {}):
            return item[k]
    return None


def _headers(value):
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items() if v not in (None, "")}
    if isinstance(value, list):                                  # ["Referer: https://x", ...]
        out = {}
        for line in value:
            if isinstance(line, str) and ":" in line:
                k, v = line.split(":", 1)
                out[k.strip()] = v.strip()
        return out
    return {}


def _subs(value):
    out = []
    if isinstance(value, dict):
        value = [value]
    for s in value if isinstance(value, list) else []:
        if isinstance(s, str) and _IS_URL.match(s):
            out.append((s, "sub"))
        elif isinstance(s, dict):
            url = _first(s, _URL_KEYS)
            kind = str(s.get("kind") or s.get("type") or "").lower()
            if isinstance(url, str) and _IS_URL.match(url) and kind not in ("thumbnails", "thumbnail", "chapters"):
                out.append((url, str(_first(s, ("label", "lang", "language", "name")) or "sub")))
    return out


def _stream_from(item, inherited):
    url = _first(item, _URL_KEYS)
    if not (isinstance(url, str) and _IS_URL.match(url)):
        return None
    headers = dict(inherited)
    headers.update(_headers(_first(item, _HEAD_KEYS)))
    for key, header in (("referer", "Referer"), ("referrer", "Referer"), ("user_agent", "User-Agent"), ("userAgent", "User-Agent")):
        if item.get(key):
            headers[header] = str(item[key])
    hls = _first(item, _HLS_KEYS)
    if hls is None:
        hls = ".m3u8" in url.lower() or None
    prov = _first(item, _PROV_KEYS)
    return Stream(url, resolution=_first(item, _RES_KEYS), hls=bool(hls) if hls is not None else None,
                  provider=prov if isinstance(prov, str) else None, headers=headers, subtitles=_subs(_first(item, _SUB_KEYS) or []))


def parse_links(text):
    """`ani-cli-rs links --json` (or plain text with URLs) -> [Stream] in the order given (preference order)."""
    text = (text or "").strip()
    if not text:
        return []
    data = m._json_or_none(text)
    streams = []
    if data is not None:
        inherited, items, shared_subs = {}, data, []
        if isinstance(data, dict):
            inherited = _headers(_first(data, _HEAD_KEYS))
            shared_subs = _subs(_first(data, _SUB_KEYS) or [])
            items = next((data[k] for k in _LIST_KEYS if isinstance(data.get(k), list)), [data])
        for item in items if isinstance(items, list) else []:
            if isinstance(item, str) and _IS_URL.match(item):
                streams.append(Stream(item, hls=".m3u8" in item.lower() or None, headers=dict(inherited)))
            elif isinstance(item, dict):
                s = _stream_from(item, inherited)
                if s:
                    streams.append(s)
        for s in streams:
            if not s.subtitles:
                s.subtitles = list(shared_subs)
        return streams
    for line in text.splitlines():                               # text fallback: any URL on a line
        mt = re.search(r"https?://\S+", line)
        if mt:
            streams.append(Stream(mt.group(0), hls=".m3u8" in mt.group(0).lower() or None))
    return streams


def pick_stream_order(streams, quality="best"):
    """Keep the engine's own preference order; for a numeric quality ('720p') put matching resolutions first."""
    digits = re.sub(r"\D", "", quality or "")
    if not digits:
        return streams
    def matches(s):
        return digits in re.sub(r"\D", "", str(s.resolution or ""))
    return [s for s in streams if matches(s)] + [s for s in streams if not matches(s)]


# --------------------------------------------------------------------------- the engine
def find_exe(name, which=shutil.which, home=None):
    """PATH first, then ani-cli-rs's default install folder (the Windows installer uses %USERPROFILE%\\.local\\bin)."""
    found = which(name)
    if found:
        return found
    base = Path(home) if home else Path.home()
    for candidate in (base / ".local" / "bin" / name, base / ".local" / "bin" / (name + ".exe"), base / ".cargo" / "bin" / (name + ".exe")):
        if candidate.is_file():
            return str(candidate)
    return None


def default_runner(cmd, timeout):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return None, "", ""
    except FileNotFoundError:
        raise EngineError(f"'{cmd[0]}' was not found. Install ani-cli-rs (see: anistream doctor).")
    return p.returncode, p.stdout, p.stderr


class AniCliRs:
    def __init__(self, exe="ani-cli-rs", providers=("anikoto", "anikoto2"), state=None, runner=None, log=None):
        self.exe = exe
        self.providers = list(providers)
        self.state = state
        self.runner = runner or default_runner
        self.log = log or (lambda msg: None)

    def _run(self, args, provider=None, timeout=90):
        cmd = [find_exe(self.exe) or self.exe] + (["--provider", provider] if provider else []) + [str(a) for a in args]
        self.log("$ " + " ".join(cmd))
        return self.runner(cmd, timeout)

    def version(self):
        rc, out, err = self._run(["--version"], timeout=15)
        return (out or err).strip().splitlines()[0] if rc == 0 and (out or err).strip() else None

    # -------------------------------------------------------------- search the catalogs directly
    def search_catalog(self, query, mode="sub"):
        """Return raw ani-cli-rs results from every configured provider, without restricting to AniList/list IDs."""
        query = " ".join(str(query or "").split())
        if not query:
            return []
        base = m.base_title_query(query)
        queries = list(dict.fromkeys(q for q in (query, m.clean_query(query), base, m.clean_query(base)) if q))
        results, failures = [], []
        seen = set()
        for provider in self.providers:
            for q in queries:
                rc, out, err = self._run(["search", "--mode", mode, "--json", q], provider)
                if rc is None or rc != 0:
                    failures.append(f"{provider}: " + ("timed out" if rc is None else m.rs_error_summary(err or out)))
                    continue
                for sid, names in m.parse_rs_results(out):
                    key = (provider, sid)
                    if key in seen or not names:
                        continue
                    seen.add(key)
                    results.append({"provider": provider, "sid": sid, "name": names[0], "names": names})
        if not results and failures:
            raise EngineError("catalog search failed: " + "; ".join(failures))
        return results

    # -------------------------------------------------------------- one catalog at a time
    def find_in(self, media, mode, provider, search_query=None):
        """Find an entry in one catalog. Explicit CLI queries are tried first and refresh the cache."""
        cached = self.state.show(media["id"], mode, provider) if self.state else None
        query = " ".join(str(search_query or "").split())
        if cached and not query:
            return cached["sid"], cached["name"]

        titles = m.all_titles(media)
        queries = []
        if query:
            # The caller may have found the AniList entry through an alias unlike its official title.
            if query.casefold() not in {t.casefold() for t in titles}:
                titles.insert(0, query)
            queries.extend((query, m.clean_query(query)))
        queries.extend(m.build_candidates(media)["ani-cli-rs"])
        queries = list(dict.fromkeys(q for q in queries if q))

        errors, last = 0, ""
        for q in queries:
            rc, out, err = self._run(["search", "--mode", mode, "--json", q], provider)
            if rc is None or rc != 0:
                errors += 1
                last = "timed out" if rc is None else m.rs_error_summary(err or out)
                if errors >= 2:
                    raise EngineError(f"the catalog is not answering ({last})")
                continue
            results = m.parse_rs_results(out)
            # Match like fetch_anime.py: an embedded AniList ID is conclusive when present.
            # If the catalog has no AniList ID, allow the explicitly typed alias to identify it.
            pick = m.pick_result(results, titles, media["id"])
            if not pick and query:
                unlinked = []
                for sid, names in results:
                    embedded = m.rs_embedded(sid)
                    embedded_id = embedded.get("anilistId") or embedded.get("anilist_id")
                    if embedded_id in (None, ""):
                        unlinked.append((sid, names))
                pick = m.pick_result(unlinked, [query], None)
            if pick:
                if self.state:
                    self.state.remember_show(media["id"], mode, provider, pick[0], pick[1])
                return pick

        # Do not silently keep a stale match after an explicit query failed to find a replacement.
        if cached and query and self.state:
            self.state.forget_show(media["id"], mode, provider)
        return None

    def streams(self, sid, episode, mode, quality="best", provider=None):
        """Resolve an episode through the same provider that returned its catalog ID."""
        rc, out, err = self._run(["links", sid, episode, "--mode", mode, "--json"], provider)
        if rc is None:
            raise EngineError("ani-cli-rs timed out while resolving the stream.")
        if rc != 0:
            found_code = re.search(r"ACL-\d+", err or out or "")
            raise EngineError(m.rs_error_summary(err or out), code=found_code.group(0) if found_code else None)
        found = parse_links(out)
        if not found:
            raise EngineError("ani-cli-rs returned no playable links (run: anistream probe).")
        return pick_stream_order(found, quality)

    # -------------------------------------------------------------- what the app calls
    def resolve_all(self, media, episode, mode, quality="best", search_query=None):
        """Resolve through every configured catalog, in order, retaining all usable candidates.

        This lets the player try the next catalog when a nominally valid URL closes immediately, not
        only when links resolution itself returns an error.
        """
        attempts, codes, resolved = [], [], []
        for provider in self.providers:
            try:
                found = self.find_in(media, mode, provider, search_query=search_query)
            except EngineError as e:
                attempts.append(f"{provider}: {e}")
                continue
            if not found:
                attempts.append(f"{provider}: no matching entry")
                continue
            sid, name = found
            try:
                streams = self.streams(sid, episode, mode, quality, provider=provider)
            except EngineError as e:
                attempts.append(f"{provider}: {e}")
                codes.append(e.code)
                if e.code not in STREAM_SIDE_CODES and self.state:      # anything else may mean the cached id is stale
                    self.state.forget_show(media["id"], mode, provider)
                continue
            resolved.append(Resolved(sid, name, provider, streams))
        if resolved:
            return resolved
        code = codes[0] if codes and len(set(codes)) == 1 and len(codes) == len(attempts) else None
        raise EngineError("; ".join(attempts) or "no catalog configured", code=code)

    def resolve(self, media, episode, mode, quality="best", search_query=None):
        """Compatibility wrapper returning the first working catalog."""
        return self.resolve_all(media, episode, mode, quality, search_query=search_query)[0]

    def probe(self, media, episode, mode, quality="best", search_query=None):
        """Diagnostic rows, one per catalog: what it matched and whether it has a stream. Nothing is played."""
        rows = []
        for provider in self.providers:
            row = {"provider": provider, "mode": mode, "entry": None, "streams": None, "error": None}
            try:
                found = self.find_in(media, mode, provider, search_query=search_query)
                if not found:
                    row["error"] = "no matching entry"
                else:
                    row["entry"] = found[1]
                    row["streams"] = self.streams(found[0], episode, mode, quality, provider=provider)
            except EngineError as e:
                row["error"] = str(e)
            rows.append(row)
        return rows
