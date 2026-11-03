"""Title and catalog-entry matching, ported from anilist-autodl (src/fetch_anime.py, version 2.2.2).

Decides which catalog entry IS the anime you picked: same words AND compatible season/stage numbers
('1st STAGE' and '2nd - 3rd STAGE' are different entries), with the catalog's own AniList id as exact proof when it carries one.
Keep this file in sync with the downloader if you change the rules there.
"""
import base64
import json
import os
import re
import unicodedata


VIDEO_EXTS = ('.mp4', '.mkv', '.webm')


STOPWORDS = {'the', 'a', 'an', 'and', 'or', 'to', 'of', 'in', 'for', 'on', 'with', 'is', 'at',
             'by', 'this', 'that', 'your', 'you', 'my', 'i', 'it', 'season', 'episode', 'ep',
             # sequel markers: "2nd Season", "Part 2", "II" tell seasons apart but are not part of the name
             'nd', 'st', 'rd', 'th', 'ii', 'iii', 'iv', 'part', 'cour', 'stage'}


# tags that sources add to file names; they say nothing about WHICH anime it is
FILE_NOISE = {'episodes', 'eps', 'dub', 'dubbed', 'sub', 'subbed', 'dublado', 'legendado', 'hd', 'uncensored'}


MATCH_MIN_COVERAGE = 0.8    # share of the expected title's words that must be in the file name


MATCH_EXTRA_PER = 5         # unrelated extra words allowed in the file name: one per this many words of the title


def tokenize(s):
    s = re.sub(r'[\d\W_]+', ' ', s.lower())
    return set(s.split()) - STOPWORDS


def all_titles(media):
    t = media.get('title') or {}
    names = [t.get('english'), t.get('romaji')] + list(media.get('synonyms') or [])[:5]
    seen, out = set(), []
    for n in names:
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def file_name_tokens(filename):
    """(all words, main words) of a file name. 'main' ignores 'Episode N', (tags), [tags] and dub/sub labels."""
    stem = os.path.splitext(filename)[0] if os.path.splitext(filename)[1].lower() in VIDEO_EXTS + ('.part',) else filename
    stem = re.sub(r'\bepisode\s*\d+.*$', ' ', stem, flags=re.IGNORECASE)
    main = tokenize(re.sub(r'[(\[].*?[)\]]', ' ', stem)) - FILE_NOISE
    return tokenize(stem), main


def title_match(titles, filename):
    """Is this file really one of the anime in `titles`? Strict on purpose: a wrong anime in the library is worse
    than a skipped download ('Magical Explorer' must not accept 'Magical Girl Magical Destroyers')."""
    full, main = file_name_tokens(filename)
    if not main:
        return False
    for t in titles:
        exp = tokenize(t)
        if not exp:
            continue
        covered = len(exp & full) / len(exp)
        extra = len(main - exp)
        if covered >= MATCH_MIN_COVERAGE and extra <= len(exp) // MATCH_EXTRA_PER:
            return True                      # same title; short titles allow NO unrelated words ('... Alicization')
        if len(main) >= 2 and main <= exp:
            return True                      # the source shortened a long title
    return False


def safe_name(s):
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()[:120] or 'Anime'


def clean_query(q):
    """Search backends don't URL-encode reliably: strip accents, dashes, quotes and symbols that cause HTTP 400 / bad searches."""
    q = re.sub(r'[\u2010-\u2015]', ' ', q).replace("'", "").replace("\u2019", "")
    q = unicodedata.normalize('NFKD', q).encode('ascii', 'ignore').decode()
    q = re.sub(r'[^A-Za-z0-9\s\-]', ' ', q)
    return re.sub(r'\s+', ' ', q).strip()


def base_title_query(title):
    """Remove a trailing/embedded season marker so users can search the whole franchise/catalog."""
    value = str(title or "")
    patterns = (
        r"\b\d+\s*(?:st|nd|rd|th)?\s+(?:season|stage|part|cour)\b",
        r"\b(?:season|stage|part|cour)\s*\d+\b",
        r"\b(?:second|third|fourth|fifth|sixth)\s+season\b",
        r"\b\d+(?:st|nd|rd|th)\s*[-–]\s*\d+(?:st|nd|rd|th)\s+(?:stage|season)\b",
    )
    for pattern in patterns:
        value = re.sub(pattern, " ", value, flags=re.IGNORECASE)
    value = re.sub(r"[\s:：–—-]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _same_catalog_title(left, right):
    left_primary = left.get("name") or (left.get("names") or [""])[0]
    right_primary = right.get("name") or (right.get("names") or [""])[0]
    # Do not merge a season-specific result with a different season just because both expose
    # an unqualified alias such as "Frieren" in their alternate-title list.
    # Symmetric on purpose: one catalog names the combined entry '2nd - 3rd STAGE' ({2, 3}), another '2nd Stage' ({2});
    # they are the same entry whichever one happened to be seen first.
    if left_primary and right_primary:
        lm, rm = sequel_markers(left_primary), sequel_markers(right_primary)
        if not (markers_compatible(lm, rm) or markers_compatible(rm, lm)):
            return False
    left_names = left.get("names") or [left_primary]
    right_names = right.get("names") or [right_primary]
    for a in left_names:
        for b in right_names:
            if not a or not b:
                continue
            if tokenize(a) == tokenize(b) and (markers_compatible(sequel_markers(a), sequel_markers(b))
                                                or markers_compatible(sequel_markers(b), sequel_markers(a))):
                return True
    return False


def group_catalog_results(results):
    """Group the same title/season from multiple providers while keeping every SID available for playback."""
    groups = []
    seen = set()
    for result in results:
        key = (result.get("provider"), result.get("sid"))
        if key in seen:
            continue
        seen.add(key)
        group = next((g for g in groups if _same_catalog_title(g, result)), None)
        if group is None:
            groups.append({"name": result.get("name") or (result.get("names") or ["Unknown title"])[0],
                           "names": list(result.get("names") or []), "matches": [result]})
        else:
            group["matches"].append(result)
            for name in result.get("names") or []:
                if name not in group["names"]:
                    group["names"].append(name)
    return groups


_RS_ID_KEYS = ('id', 'show_id', 'showId', 'slug')


_RS_LIST_KEYS = ('results', 'shows', 'items', 'data', 'anime', 'list', 'episodes')


def _json_or_none(text):
    text = (text or '').strip()
    if text[:1] not in ('[', '{'):
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def _rs_items(data):
    if isinstance(data, dict):
        for k in _RS_LIST_KEYS:
            if isinstance(data.get(k), list):
                return data[k]
        return [data]
    return data if isinstance(data, list) else []


def _item_titles(item):
    """Every name an item carries: 'title', 'name', 'english_name'... (also nested {'english': ..., 'romaji': ...})."""
    out = []
    for k, v in item.items():
        if 'title' in k.lower() or 'name' in k.lower():
            if isinstance(v, str) and v.strip():
                out.append(v.strip())
            elif isinstance(v, dict):
                out += [x.strip() for x in v.values() if isinstance(x, str) and x.strip()]
    return list(dict.fromkeys(out))


def parse_rs_results(text):
    """'ani-cli-rs search --json' (or its tab-separated text) -> [(show_id, [names])].
    Written against the documented behaviour, so it is deliberately tolerant about field names."""
    data = _json_or_none(text)
    results = []
    if data is not None:
        for it in _rs_items(data):
            if not isinstance(it, dict):
                continue
            sid = next((str(it[k]) for k in _RS_ID_KEYS if it.get(k) not in (None, '')), None)
            names = _item_titles(it)
            if sid and names:
                results.append((sid, names))
        return results
    for line in (text or '').splitlines():       # text format: the show ID comes first
        cols = [c.strip() for c in line.split('\t') if c.strip()]
        names = [c for c in cols[1:] if not re.fullmatch(r'[\d.,/ ]+', c)]
        if len(cols) >= 2 and names:
            results.append((cols[0], names))
    return results


ROMAN_SEASONS = {'ii': 2, 'iii': 3, 'iv': 4}


def sequel_markers(text):
    """Season/stage numbers named in a title: '2nd Season', 'Season 2', 'Part 2', '2nd - 3rd STAGE', 'II' -> {2} / {2, 3}.
    Resolutions, '(12 episodes)', years and numbers above 99 ('Mob Psycho 100') are not season numbers."""
    text = re.sub(r'\bepisode\s*\d+.*$', ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'\(\s*\d+\s*(episodes?|eps?)\s*\)|\b\d{3,4}p\b', ' ', text, flags=re.IGNORECASE)
    nums = {int(n) for n in re.findall(r'\d+', text) if 1 <= int(n) <= 99}
    nums |= {ROMAN_SEASONS[w] for w in re.findall(r'[a-z]+', text.lower()) if w in ROMAN_SEASONS}
    return nums


def markers_compatible(candidate, wanted):
    """Do two sets of season/stage numbers describe the same entry? A plain title is season/stage 1.
    A catalog may name a combined entry by its first stage only: AniList '2nd - 3rd STAGE' ({2, 3}) is the catalog's
    '2nd Stage' ({2}). So the catalog's numbers may be a subset of the wanted range if they start at the same number."""
    c, w = set(candidate) or {1}, set(wanted) or {1}
    return c == w or (c <= w and min(c) == min(w))


def _subtitle_present(wanted, name):
    """'JoJo's Bizarre Adventure: Steel Ball Run' must not accept the franchise entry 'JoJo's Bizarre Adventure (2012)'.
    title_match() lets a source SHORTEN a long title, which is exactly how a parent franchise passes as its own
    sequel. So when the wanted title has a ': Subtitle', the entry has to carry at least one subtitle word."""
    if ':' not in wanted and '\uff1a' not in wanted:
        return True
    sub = tokenize(re.split(r'[:\uff1a]', wanted, maxsplit=1)[1])
    return not sub or bool(sub & tokenize(name))


def result_match(name, titles):
    """Is this catalog entry the anime we want? -> (True, '') or (False, why).
    Same words AND compatible season/stage numbers: 'X 1st STAGE' and 'X 2nd - 3rd STAGE' are different entries (each with
    its own episode numbering) even though their words are identical."""
    fname = f"{name} Episode 1.mp4"
    same_words = [t for t in titles if title_match([t], fname) and _subtitle_present(t, name)]
    if not same_words:
        return False, 'different title'
    mine = sequel_markers(name)
    if not any(markers_compatible(mine, sequel_markers(t)) for t in same_words):
        wanted = sorted({tuple(sorted(sequel_markers(t))) for t in same_words})
        return False, f"season/stage numbers differ (entry {sorted(mine) or '-'}, wanted {[list(w) or '-' for w in wanted]})"
    return True, ''


def rs_embedded(sid):
    """ani-cli-rs 'anikoto:' ids are base64 JSON ({"anilistId": "...", "malId": "...", "title": "...", "episodes": N}):
    the catalog itself says which AniList entry this is. {} when the id is not of that kind."""
    try:
        body = str(sid).split(':', 1)[-1].replace('+', '-').replace('/', '_')
        data = json.loads(base64.urlsafe_b64decode(body + '=' * (-len(body) % 4)))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _embedded_anilist_id(sid):
    emb = rs_embedded(sid)
    value = emb.get('anilistId') or emb.get('anilist_id')
    return str(value) if value not in (None, '') else None


def _embedded_stage_conflict(names, titles):
    """True only when the catalog explicitly names a different season/stage.

    Some catalogs reuse an AniList ID for multiple separately indexed stages. The ID is strong
    evidence, but must not override an explicit "1st Stage" vs "2nd Stage" conflict. Names with
    no explicit stage marker remain eligible for ID-based matching.
    """
    candidate_sets = [sequel_markers(n) for n in names if sequel_markers(n)]
    wanted_sets = [sequel_markers(t) for t in titles if sequel_markers(t)]
    if not candidate_sets or not wanted_sets:
        return False
    return all(not markers_compatible(c, w) for c in candidate_sets for w in wanted_sets)


def result_verdict(sid, names, titles, anilist_id=None):
    """(accepted, why) for a catalog result, preserving explicit season/stage distinctions."""
    emb_id = _embedded_anilist_id(sid)
    if emb_id and anilist_id:
        if emb_id != str(anilist_id):
            return False, f'the catalog says this is AniList id {emb_id}, not {anilist_id}'
        if _embedded_stage_conflict(names, titles):
            return False, 'the catalog entry explicitly names a different season/stage'
        return True, 'same AniList id'
    return result_match(names[0], titles)


def pick_result(results, titles, anilist_id=None):
    """Pick the right catalog entry by AniList ID and compatible stage, or by strict title match."""
    best = None
    for sid, names in results:
        emb_id = _embedded_anilist_id(sid)
        if emb_id and anilist_id:
            if emb_id != str(anilist_id):
                continue                                   # the catalog knows it is another anime
            if _embedded_stage_conflict(names, titles):
                continue                                   # same AniList ID, but explicitly another stage
            return sid, names[0]
        ok = [n for n in names if result_match(n, titles)[0]]
        if not ok:
            continue
        exact = any(tokenize(n) == tokenize(t) for n in ok for t in titles)
        key = (0 if exact else 1, min(len(n) for n in ok), sid)
        if best is None or key < best[0]:
            best = (key, sid, ok[0])
    return (best[1], best[2]) if best else None


def rs_error_summary(text):
    """'ACL-3001 No playable sources found (the provider has no working stream for this episode)' from ani-cli-rs's output."""
    m = re.search(r'error\[(ACL-\d+)\]:\s*([^\n]+)', text or '')
    if m:
        hints = {'ACL-3001': 'the provider has no working stream for this episode (yet)', 'ACL-3003': 'the stream is unavailable',
                 'ACL-2003': 'the catalog lists no episodes', 'ACL-2004': 'that episode does not exist in this mode',
                 'ACL-1004': 'rate limited', 'ACL-4002': 'install yt-dlp or ffmpeg'}
        return f"{m.group(1)} {m.group(2).strip()}" + (f" ({hints[m.group(1)]})" if m.group(1) in hints else '')
    return ' '.join((text or '').split())[:200] or 'no message'


def build_candidates(media):
    """Search texts per engine. ani-cli does not URL-encode, so it gets symbol-free text. ani-cli-rs and ani-tupi encode
    properly and catalogs contain the real punctuation ("JoJo's"): they get the original titles FIRST, then the cleaned
    ones, then the parts of 'Title: Subtitle'."""
    t = media.get('title') or {}
    eng, rom = t.get('english'), t.get('romaji')
    year = media.get('seasonYear') or (media.get('startDate') or {}).get('year')
    raw = []
    for q in (eng, rom, f"{eng} {year}" if eng and year else None, f"{rom} {year}" if rom and year else None):
        if q and q not in raw:
            raw.append(q)
    for syn in (media.get('synonyms') or [])[:5]:
        if syn and syn not in raw:
            raw.append(syn)
    cleaned = []
    for q in raw:
        q = clean_query(q)
        if q and q not in cleaned:
            cleaned.append(q)
    parts = []
    for q in (eng, rom):
        for piece in re.split(r'\s*[:\uff1a]\s+', q or ''):
            if len(piece.split()) >= 2 and piece != q and piece not in parts:
                parts.append(piece)
    rich = list(dict.fromkeys(raw + cleaned + parts))
    plain = list(dict.fromkeys(raw + cleaned))
    return {'ani-cli': cleaned, 'ani-cli-rs': rich, 'ani-tupi': plain, 'goanime': plain}
