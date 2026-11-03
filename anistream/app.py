"""The program's flows: lists, search, playing episodes, recording progress."""
import time
import webbrowser

from . import matching as m
from .anilist import AniListError
from .config import save_config
from .engine import EngineError
from .player import PlayerError
from .sync import plan_update


def title_of(media, lang="english"):
    t = media.get("title") or {}
    order = ("english", "romaji") if lang == "english" else ("romaji", "english")
    return t.get(order[0]) or t.get(order[1]) or f"AniList #{media.get('id')}"


def released(media):
    """Episodes that are out: None when unknown."""
    status = media.get("status")
    nxt = (media.get("nextAiringEpisode") or {}).get("episode")
    if status == "NOT_YET_RELEASED":
        return 0
    if status == "RELEASING" and nxt:
        return nxt - 1
    return media.get("episodes")


def countdown(media, now=None):
    at = (media.get("nextAiringEpisode") or {}).get("airingAt")
    if not at:
        return ""
    secs = int(at - (now if now is not None else time.time()))
    if secs <= 0:
        return "any moment"
    d, rest = divmod(secs, 86400)
    h, rest = divmod(rest, 3600)
    return f"{d}d {h}h" if d else (f"{h}h {rest // 60}m" if h else f"{rest // 60}m")


class App:
    def __init__(self, cfg, ui, api, engine, play_fn, backend, state, now=time.time, today=None, open_url=webbrowser.open):
        self.cfg, self.ui, self.api, self.engine = cfg, ui, api, engine
        self.play_fn, self.backend, self.state = play_fn, backend, state
        self.now, self.today, self.open_url = now, today, open_url
        self.entries = {}                       # media id -> your list entry (kept current while the program runs)

    # ---------------------------------------------------------------- labels
    def name(self, media):
        return title_of(media, self.cfg.get("title_lang", "english"))

    def entry_label(self, entry):
        media = entry["media"]
        done, total = entry.get("progress") or 0, media.get("episodes")
        nxt, out = done + 1, released(media)
        if total and done >= total:
            tag = "finished"
        elif out is not None and nxt > out:
            tag = f"Ep {nxt} airs in {countdown(media, self.now())}" if media.get("nextAiringEpisode") else f"Ep {nxt} not out yet"
        else:
            tag = f"▶ Ep {nxt} ready"
        rewatch = "  (rewatching)" if entry.get("status") == "REPEATING" else ""
        return f"{self.name(media)}  [{done}/{total or '?'}]  {tag}{rewatch}"

    def sorted_entries(self, entries):
        def key(e):
            media, nxt = e["media"], (e.get("progress") or 0) + 1
            out = released(media)
            ready = out is None or nxt <= out
            return (0 if ready else 1, self.name(media).lower())
        return sorted(entries, key=key)

    # --------------------------------------------------------------- sync
    def sync_label(self):
        if self.backend:
            return f"sync: {self.backend.name}"
        return "sync: off"

    def flush_pending(self):
        """Send updates that earlier failed (offline). The planner re-reads the entry, so nothing is ever lowered."""
        if not self.backend:
            return
        for item in self.state.pending():
            try:
                media, entry = self.api.entry(item["media_id"])
                upd = plan_update(entry, media, item["episode"], self.today)
                if upd:
                    self.backend.apply(upd)
                    self.ui.ok(f"Sent a queued update: {self.name(media)} → {upd.describe()}")
                self.state.clear_pending(item)
            except (AniListError, RuntimeError) as e:
                self.ui.warn(f"Queued updates stay queued ({e})")
                return

    def record(self, media, ep):
        """Mark `ep` watched on AniList (or queue it when offline)."""
        entry = self.entries.get(media["id"])
        try:
            if self.cfg.get("token"):                       # fresh status/progress from the server
                _, fresh = self.api.entry(media["id"])
                entry = fresh if fresh is not None or entry is None else entry
            upd = plan_update(entry, media, ep, self.today)
            if upd is None:
                self.ui.dim("Nothing to update on AniList (already at or past this episode).")
                return
            self.backend.apply(upd)
        except (AniListError, RuntimeError) as e:
            self.state.queue(media["id"], ep)
            self.ui.warn(f"Could not update AniList now ({e}). Saved; it will be retried next time.")
            return
        merged = dict(entry or {})
        merged.update(progress=upd.progress, status=upd.status or merged.get("status"))
        merged["media"] = media
        self.entries[media["id"]] = merged
        self.ui.ok(f"AniList: {self.name(media)} → {upd.describe()}")

    def after_play(self, media, entry, ep, res):
        """Decide whether this viewing counts, then record it."""
        if not self.backend:
            return
        pct, thr, low = res.percent, self.cfg["threshold"], self.cfg["ask_below"]
        if pct is None:
            mark = self.ui.confirm(f"Did you finish Ep {ep}? Mark it as watched?", False)
        elif res.eof or pct >= thr:
            mark = True
        elif pct >= low:
            mark = self.ui.confirm(f"You watched {pct:.0f}% of Ep {ep}. Mark it as watched?", False)
        else:
            mark = False
        if not mark:
            return
        done = (entry or {}).get("progress") or 0
        if ep > done + 1 and not self.ui.confirm(f"You are at Ep {done}. Mark Ep {ep} (skipping {ep - done - 1}) as watched?", False):
            return
        self.record(media, ep)

    # ------------------------------------------------------------ playing
    def _play(self, stream, title):
        """Run the player; if the stream dies partway (broken HLS), offer to resume where it stopped."""
        res = self.play_fn(self.cfg, stream, title)
        if getattr(res, "skipped", 0) >= 3:
            self.ui.warn(f"The source skipped about {int(res.skipped)}s of this episode (segments kept timing out). Try the other provider or sub/dub.")
        for _ in range(5):
            if not getattr(res, "early", False):
                break
            pos, dur = res.position, res.duration
            self.ui.warn(f"The stream ended early at {int(pos // 60)}:{int(pos % 60):02d} of {int(dur // 60)}:{int(dur % 60):02d} (source error), not the real end.")
            if not self.ui.confirm("Resume from there?", True):
                break
            nxt = self.play_fn(self.cfg, stream, title, start=max(0, pos - 3))
            # Progress made by the resumed run is what counts; if it got nowhere, stop asking.
            stuck = getattr(nxt, "position", 0) <= pos + 5
            res = nxt
            if stuck:
                break
        return res

    @staticmethod
    def _playback_succeeded(result):
        """A launched mpv process is not enough: dead stream URLs can open and close immediately."""
        if result.eof or (result.percent is not None and result.percent > 0):
            return True
        # If progress.lua did not report, elapsed time is the fallback. A very short-lived mpv
        # process is treated as a failed source so the next catalog/link gets a chance.
        return result.elapsed >= 5

    def play_episode(self, media, entry, ep, search_query=None):
        """Try every configured provider and the preferred audio mode before fallback mode."""
        name, first = self.name(media), self.cfg["mode"]
        modes = [first] + (["dub" if first == "sub" else "sub"] if self.cfg.get("mode_fallback") else [])
        last_error = None
        attempts = []
        for mode in modes:
            try:
                if hasattr(self.engine, "resolve_all"):
                    resolved_items = self.engine.resolve_all(media, ep, mode, self.cfg["quality"], search_query=search_query)
                elif search_query:
                    resolved_items = [self.engine.resolve(media, ep, mode, self.cfg["quality"], search_query=search_query)]
                else:
                    resolved_items = [self.engine.resolve(media, ep, mode, self.cfg["quality"])]
            except EngineError as e:
                last_error = e
                self.ui.warn(f"{mode}: {e}")
                continue

            candidates = [(resolved.provider, stream) for resolved in resolved_items for stream in resolved.streams[:3]]
            # Like anilist-autodl's PREFER_SUBS: check other catalogs for real subtitle tracks before
            # accepting a subbed result with no external tracks (it may still be hard-subbed).
            with_subs = [(p, s) for p, s in candidates if mode != "sub" or not self.cfg.get("prefer_subtitles", True) or s.subtitles]
            without_subs = [(p, s) for p, s in candidates if mode == "sub" and self.cfg.get("prefer_subtitles", True) and not s.subtitles]
            for provider, stream in with_subs + without_subs:
                self.ui.say(self.ui.bold(f"▶ {name} — Episode {ep}") + self.ui._c("2", f"  ({mode}, {provider}, {stream.label()})"))
                try:
                    res = self._play(stream, f"{name} - Episode {ep}")
                except PlayerError as e:
                    self.ui.error(str(e))
                    return False
                self.ui.say()
                if self._playback_succeeded(res):
                    if mode == "sub" and not stream.subtitles and self.cfg.get("prefer_subtitles", True):
                        self.ui.dim("No external subtitle tracks were exposed by this source; it may still be hard-subbed.")
                    self.after_play(media, entry, ep, res)
                    return True
                attempt = f"{provider}/{mode}/{stream.label()} closed before playback was established"
                attempts.append(attempt)
                self.ui.warn("The stream closed immediately; trying the next link/catalog.")

        if last_error is not None and attempts:
            self.ui.error(f"Could not play Ep {ep}: {last_error}; stream failures: {'; '.join(attempts)}.")
        elif last_error is not None:
            self.ui.error(f"Could not play Ep {ep}: {last_error}")
        elif attempts:
            self.ui.error(f"Could not play Ep {ep}: all source attempts failed ({'; '.join(attempts)}).")
        if last_error is not None and (getattr(last_error, "code", None) == "ACL-3001" or "playable" in str(last_error).lower()):
            self.ui.dim("That usually means the providers have no stream for this episode yet; try again later.")
        return False

    # ------------------------------------------------------- raw catalog search
    def _catalog_row_matches_titles(self, row, group, titles, anilist_id=None):
        sid = row.get("sid")
        names = row.get("names") or [row.get("name") or group.get("name", "")]
        embedded = m.rs_embedded(sid)
        embedded_id = embedded.get("anilistId") or embedded.get("anilist_id")
        if embedded_id not in (None, "") and anilist_id is not None:
            return m.result_verdict(sid, names, titles, anilist_id)[0]
        if embedded_id not in (None, ""):
            # No target ID is available, so avoid using a catalog ID as proof; strict names still apply.
            return any(name and m.result_match(name, titles)[0] for name in names)
        return any(name and m.result_match(name, titles)[0] for name in names)

    def _catalog_matches_media(self, group, media):
        """Only connect catalog playback to AniList when its embedded ID or strict title/season matches."""
        titles = m.all_titles(media)
        rows = group.get("matches") or []
        if rows:
            return any(self._catalog_row_matches_titles(row, group, titles, media.get("id")) for row in rows)
        names = list(group.get("names") or []) + [group.get("name", "")]
        return any(name and m.result_match(name, titles)[0] for name in names)

    def pick_catalog_group(self, groups, titles, anilist_id=None):
        """Use fetch_anime.py's auto-picking rule: embedded AniList ID first, then strict title/season match."""
        rows = []
        for group in groups or []:
            for row in group.get("matches") or []:
                sid = row.get("sid")
                names = row.get("names") or [row.get("name") or group.get("name", "")]
                if sid is not None and names:
                    rows.append((str(sid), list(names), group))
        picked = m.pick_result([(sid, names) for sid, names, _group in rows], titles, anilist_id)
        if picked:
            sid, name = str(picked[0]), picked[1]
            for row_sid, names, group in rows:
                if row_sid == sid and (name in names or group.get("name") == name):
                    return group
        # Fallback to the strict matcher for records whose catalog ID format isn't recognized.
        matching = [group for group in (groups or []) if any(
            self._catalog_row_matches_titles(row, group, titles, anilist_id)
            for row in (group.get("matches") or [])
        ) or (not group.get("matches") and any(
            name and m.result_match(name, titles)[0]
            for name in (list(group.get("names") or []) + [group.get("name", "")])
        ))]
        if matching:
            matching.sort(key=lambda group: (len(group.get("name") or ""), str(group.get("name") or "").casefold()))
            return matching[0]
        return None

    def _catalog_base_matches_media(self, group, media):
        """Loose franchise match used only to offer a manual choice; never authorizes progress sync."""
        titles = list(dict.fromkeys(m.base_title_query(t) for t in m.all_titles(media) if t))
        titles = [t for t in titles if t]
        names = list(group.get("names") or []) + [group.get("name", "")]
        for name in names:
            base_tokens = m.tokenize(m.base_title_query(name))
            if not base_tokens:
                continue
            for title in titles:
                wanted_tokens = m.tokenize(title)
                # Broad subset matching is deliberately used only for a manual picker; these
                # results are played without AniList progress sync unless the strict match passed.
                if wanted_tokens and (base_tokens <= wanted_tokens or wanted_tokens <= base_tokens):
                    return True
        return False

    def _catalog_groups_for_media(self, media):
        """Search raw catalogs using the list entry's titles, returning strict matches and all nearby results."""
        queries = []
        preferred = self.name(media)
        for title in [preferred] + m.all_titles(media):
            if title and title.casefold() not in {q.casefold() for q in queries}:
                queries.append(title)
            if len(queries) >= 3:
                break

        raw, errors = [], []
        groups, exact = [], []
        for query in queries:
            try:
                raw.extend(self.engine.search_catalog(query, self.cfg["mode"]))
            except EngineError as e:
                errors.append(f"{query}: {e}")
                continue
            groups = m.group_catalog_results(raw)
            exact = [group for group in groups if self._catalog_matches_media(group, media)]
            if exact:
                # A strict title+season match is enough; don't make list navigation painfully slow
                # by searching every synonym after we have a playable catalog result.
                break
        return groups, exact, errors

    def watch_list_entry(self, entry):
        """Continue from a list entry through raw catalog results before using the legacy ID resolver."""
        media = entry["media"]
        episode = (entry.get("progress") or 0) + 1
        groups, exact, errors = self._catalog_groups_for_media(media)

        if exact:
            # Don't prompt between duplicate/provider variants. Match the correct title/season the same
            # way fetch_anime.py does, and keep all provider variants in the chosen group for fallback.
            group = self.pick_catalog_group(exact, m.all_titles(media), media.get("id")) or exact[0]
            self.ui.log(f"Auto-selected catalog entry: {group['name']}")
            # Every exact group is the same AniList entry under another catalog's name; keep all their rows so a
            # provider with no stream for this episode (ACL-3001) falls through to the next provider.
            rows, seen = [], set()
            for g in [group] + [g for g in exact if g is not group]:
                for row in g["matches"]:
                    key = (row.get("provider"), row.get("sid"))
                    if key not in seen:
                        seen.add(key)
                        rows.append(row)
            self.watch_catalog(rows, group["name"], episode, media, entry)
            return

        # The catalog may only expose another season under the same franchise. Let the user
        # choose it explicitly, but detach it from the AniList entry so we never sync the wrong season.
        base_matches = [group for group in groups if self._catalog_base_matches_media(group, media)]
        if base_matches:
            labels = []
            for group in base_matches:
                providers = ", ".join(dict.fromkeys(row.get("provider", "?") for row in group["matches"]))
                labels.append(f"{group['name']}  [{providers}]")
            self.ui.warn(f"No exact catalog match for {self.name(media)} season; a different season will play without AniList sync.")
            if len(base_matches) == 1:
                if not self.ui.confirm(f"Play catalog entry '{base_matches[0]['name']}' without syncing AniList progress?", False):
                    return
                group = base_matches[0]
            else:
                idx = self.ui.pick("Choose a catalog season (progress sync disabled unless the season matches)", labels)
                if idx is None:
                    return
                group = base_matches[idx]
            self.watch_catalog(group["matches"], group["name"], episode, None, None)
            return

        if errors:
            self.ui.log("Catalog-first lookup did not find a matching entry; trying the standard resolver.")
        self.watch(media, entry)

    def catalog_list_entry(self, group, fallback_media=None, fallback_entry=None):
        """Return a matching AniList list item; never sync catalog-only/unrelated results."""
        if fallback_media is not None and self._catalog_matches_media(group, fallback_media):
            if fallback_entry is not None:
                return fallback_media, dict(fallback_entry, media=fallback_media)

        entries = list(self.entries.values())
        if self.cfg.get("username"):
            try:
                entries = self.api.lists(self.cfg["username"])
                for item in entries:
                    self.entries[item["media"]["id"]] = item
            except AniListError as e:
                self.ui.warn(f"Could not check AniList progress ({e}); this catalog result will play without syncing.")
                entries = list(self.entries.values())

        linked = [entry for entry in entries
                  if entry.get("media") and self._catalog_matches_media(group, entry["media"])]
        if not linked:
            return None, None
        if len(linked) == 1:
            entry = linked[0]
            return entry["media"], entry
        idx = self.ui.pick("Link progress to which AniList entry?", [self.entry_label(e) for e in linked])
        if idx is None:
            return None, None
        entry = linked[idx]
        return entry["media"], entry

    def play_catalog_episode(self, matches, ep, display_name, media=None, entry=None):
        """Try all matching catalog/source variants, preferred mode first, then audio fallback."""
        if media is not None:
            safe_matches = [row for row in matches if self._catalog_row_matches_titles(
                row, {"name": display_name}, m.all_titles(media), media.get("id")
            )]
            if safe_matches:
                # A group can contain same-named results from several catalogs. Keep only the rows
                # that identify this AniList entry, so a duplicate ID/name in one provider cannot win.
                matches = safe_matches
        first_mode = self.cfg["mode"]
        modes = [first_mode] + (["dub" if first_mode == "sub" else "sub"] if self.cfg.get("mode_fallback") else [])
        errors, playback_attempts = [], []
        for mode in modes:
            candidates = []
            for match in matches:
                try:
                    streams = self.engine.streams(match["sid"], ep, mode, self.cfg["quality"], provider=match.get("provider"))
                except EngineError as e:
                    errors.append(f"{match.get('provider', '?')} ({mode}): {e}")
                    continue
                for stream in streams[:3]:
                    candidates.append((match.get("provider", "?"), stream))

            with_subs = [(p, s) for p, s in candidates if mode != "sub" or not self.cfg.get("prefer_subtitles", True) or s.subtitles]
            without_subs = [(p, s) for p, s in candidates if mode == "sub" and self.cfg.get("prefer_subtitles", True) and not s.subtitles]
            for provider, stream in with_subs + without_subs:
                label = f"▶ {display_name} — Episode {ep}"
                self.ui.say(self.ui.bold(label) + self.ui._c("2", f"  ({mode}, {provider}, {stream.label()})"))
                try:
                    res = self._play(stream, f"{display_name} - Episode {ep}")
                except PlayerError as e:
                    self.ui.error(str(e))
                    return False
                self.ui.say()
                if self._playback_succeeded(res):
                    if mode == "sub" and not stream.subtitles and self.cfg.get("prefer_subtitles", True):
                        self.ui.dim("No external subtitle tracks were exposed by this source; it may still be hard-subbed.")
                    if media is not None:
                        entry = entry or self.entries.get(media["id"]) or {"media": media, "progress": 0}
                        self.entries[media["id"]] = dict(entry, media=media)
                        self.after_play(media, self.entries[media["id"]], ep, res)
                    else:
                        self.ui.dim("Catalog-only playback: no matching AniList list entry; progress was not synced.")
                    return True
                playback_attempts.append(f"{provider}/{mode}/{stream.label()} closed immediately")
                self.ui.warn("The stream closed immediately; trying the next link/catalog.")
        if errors and playback_attempts:
            self.ui.error("Could not play this catalog entry: " + "; ".join(errors) + "; failed links: " + "; ".join(playback_attempts))
        elif errors:
            self.ui.error("Could not play this catalog entry: " + "; ".join(errors))
        elif playback_attempts:
            self.ui.error("All stream links closed immediately: " + "; ".join(playback_attempts))
        return False

    def watch_catalog(self, matches, display_name, start_episode=None, media=None, entry=None):
        """Episode loop for raw catalog results; availability comes from the selected catalog, not AniList dates."""
        if entry is not None and media is not None:
            done = entry.get("progress") or 0
            self.entries[media["id"]] = dict(entry, media=media)
        else:
            done = 0
        ep = start_episode if start_episode is not None else done + 1
        ep = max(1, int(ep))
        while True:
            played = self.play_catalog_episode(matches, ep, display_name, media, entry)
            if not played:
                choice = self.ui.pick(f"{display_name} · Ep {ep}", ["Try again", "Pick an episode…", "Back"], default=0)
                if choice is None or choice == 2:
                    return
                if choice == 1:
                    raw = self.ui.ask("Episode number", str(ep))
                    if raw.isdigit() and int(raw) >= 1:
                        ep = int(raw)
                    else:
                        self.ui.warn("Not a valid episode number.")
                continue

            options = [f"Next episode (Ep {ep + 1})", f"Replay Ep {ep}", "Pick an episode…", "Back"]
            if self.backend and media is not None:
                options.insert(3, f"Mark Ep {ep} as watched")
            choice = self.ui.pick(f"{display_name} · Ep {ep} · {self.sync_label() if media is not None else 'sync: unavailable for catalog-only title'}", options, default=0)
            if choice is None or options[choice] == "Back":
                return
            label = options[choice]
            if label.startswith("Next"):
                ep += 1
            elif label.startswith("Replay"):
                continue
            elif label.startswith("Pick"):
                raw = self.ui.ask("Episode number", str(ep))
                if raw.isdigit() and int(raw) >= 1:
                    ep = int(raw)
                else:
                    self.ui.warn("Not a valid episode number.")
            elif label.startswith("Mark") and media is not None:
                self.record(media, ep)

    def search_catalog_menu(self, query=None, default_episode=None, fallback_media=None, fallback_entry=None):
        """Search every configured ani-cli-rs provider, independently of AniList search/list membership."""
        entered = self.ui.ask("Search all ani-cli-rs catalogs", query or "")
        if not entered:
            return
        try:
            raw = self.engine.search_catalog(entered, self.cfg["mode"])
        except EngineError as e:
            self.ui.error(str(e))
            return
        groups = m.group_catalog_results(raw)
        if not groups:
            self.ui.warn(f"No catalog results for '{entered}'.")
            return
        # Try the exact AniList list entry first (when this was launched as a recovery action),
        # then use AniList metadata to disambiguate seasons, then strict matching against the query.
        group = None
        if fallback_media is not None:
            group = self.pick_catalog_group(groups, m.all_titles(fallback_media), fallback_media.get("id"))
        if group is None:
            try:
                for media_candidate in self.api.search(entered):
                    group = self.pick_catalog_group(groups, m.all_titles(media_candidate), media_candidate.get("id"))
                    if group is not None:
                        break
            except AniListError as e:
                self.ui.log(f"AniList matching unavailable; using the catalog results directly ({e}).")
        if group is None:
            group = self.pick_catalog_group(groups, [entered], None)
        if group is None and len(groups) == 1:
            group = groups[0]
        if group is None:
            labels = []
            for result_group in groups:
                providers = ", ".join(dict.fromkeys(row.get("provider", "?") for row in result_group["matches"]))
                labels.append(f"{result_group['name']}  [{providers}]")
            idx = self.ui.pick(f"No exact match for '{entered}'. Choose a catalog result", labels)
            if idx is None:
                return
            group = groups[idx]
        else:
            self.ui.log(f"Auto-selected catalog entry: {group['name']}")
        media, entry = self.catalog_list_entry(group, fallback_media, fallback_entry)
        if media is None:
            self.ui.dim("This result is not safely matched to an AniList list entry; it will play without progress sync.")
        start = default_episode
        if start is None:
            start = (entry.get("progress") or 0) + 1 if entry else 1
        self.watch_catalog(group["matches"], group["name"], start, media, entry)

    def choose_episode(self, media, default):
        out, total = released(media), media.get("episodes")
        top = out if out is not None else total
        raw = self.ui.ask(f"Episode number{f' (1-{top})' if top else ''}", str(default))
        if raw.isdigit() and int(raw) >= 1:
            return int(raw)
        self.ui.warn("Not a valid episode number.")
        return None

    def watch(self, media, entry, search_query=None):
        """Play the next episode of an anime, then offer what to do next."""
        entry = entry if entry is not None else self.entries.get(media["id"]) or {}
        self.entries[media["id"]] = dict(entry, media=media) if entry else {"media": media, "progress": 0}
        done = (self.entries[media["id"]].get("progress") or 0)
        ep = done + 1
        total, out = media.get("episodes"), released(media)
        if total and done >= total:
            self.ui.say(f"{self.name(media)} is finished on your list. Pick an episode to rewatch.")
            ep = self.choose_episode(media, 1)
            if ep is None:
                return
        elif out is not None and ep > out:
            self.ui.warn(f"Ep {ep} is not out yet" + (f" (airs in {countdown(media, self.now())})." if media.get("nextAiringEpisode") else "."))
            choice = self.ui.pick(f"{self.name(media)} · AniList availability", ["Pick an earlier episode…", "Search all catalogs…", "Back"], default=0)
            if choice is None or choice == 2:
                return
            if choice == 1:
                self.search_catalog_menu(query=m.base_title_query(self.name(media)),
                                         fallback_media=media, fallback_entry=entry)
                return
            ep = self.choose_episode(media, out or 1)
            if ep is None:
                return
        while True:
            played = self.play_episode(media, self.entries[media["id"]], ep, search_query=search_query)
            if not played:                                   # nothing played: offering "next episode" would make no sense
                choice = self.ui.pick(f"{self.name(media)} · Ep {ep}", ["Try again", "Pick an episode…", "Search all catalogs…", "Back"], default=0)
                if choice is None or choice == 3:
                    return
                if choice == 1:
                    picked = self.choose_episode(media, ep)
                    if picked:
                        ep = picked
                elif choice == 2:
                    self.search_catalog_menu(query=m.base_title_query(self.name(media)), default_episode=ep,
                                             fallback_media=media, fallback_entry=entry)
                    return
                continue
            now_done = self.entries[media["id"]].get("progress") or 0
            options = [f"Next episode (Ep {ep + 1})", f"Replay Ep {ep}", "Pick an episode…", "Back"]
            if self.backend:
                options.insert(3, f"Mark Ep {ep} as watched")
            choice = self.ui.pick(f"{self.name(media)} · Ep {ep} · {self.sync_label()}", options, default=0)
            if choice is None or options[choice] == "Back":
                return
            label = options[choice]
            if label.startswith("Next"):
                nxt = ep + 1
                if released(media) is not None and nxt > released(media):
                    self.ui.warn(f"Ep {nxt} is not out yet.")
                    continue
                ep = nxt
            elif label.startswith("Pick"):
                picked = self.choose_episode(media, ep)
                if picked:
                    ep = picked
            elif label.startswith("Mark"):
                self.record(media, ep)
                self.ui.dim(f"(progress is {self.entries[media['id']].get('progress') or now_done})")
                continue

    # ------------------------------------------------------------- menus
    def list_menu(self, title, entries):
        if not entries:
            self.ui.warn(f"Nothing in '{title}'.")
            return
        entries = self.sorted_entries(entries)
        while True:
            idx = self.ui.pick(title, [self.entry_label(e) for e in entries])
            if idx is None:
                return
            e = entries[idx]
            self.entries[e["media"]["id"]] = e
            self.watch_list_entry(e)
            entries[idx] = self.entries.get(e["media"]["id"], e)

    def search_menu(self):
        text = self.ui.ask("Search AniList")
        if not text:
            return
        try:
            results = self.api.search(text)
        except AniListError as e:
            self.ui.error(str(e))
            return
        results = [r for r in results if not r.get("isAdult")] or results
        if not results:
            self.ui.warn("No results.")
            return

        def label(media):
            ent = media.get("mediaListEntry")
            on = f"  · on your list: {ent['status'].title()} {ent.get('progress') or 0}" if ent else ""
            year = media.get("seasonYear") or (media.get("startDate") or {}).get("year") or ""
            return f"{self.name(media)}  ({media.get('format') or '?'} {year}, {media.get('episodes') or '?'} eps){on}"

        idx = self.ui.pick("Results", [label(r) for r in results])
        if idx is None:
            return
        media = dict(results[idx])
        entry = media.pop("mediaListEntry", None)
        if entry is None and self.backend:
            self.ui.dim("Not on your list yet: it is added to Watching when you finish the first episode.")
        self.watch(media, dict(entry, media=media) if entry else None)

    def settings_menu(self):
        while True:
            c = self.cfg
            items = [f"Version: {c['mode']}  (sub / dub)",
                     f"Player: {c['player_mode']}  (window / sixel inside the terminal)",
                     f"Sync: {self.sync_label()}  (set up / change)",
                     f"Counts as watched at: {c['threshold']}%",
                     f"Titles: {c['title_lang']}",
                     f"AniList user: {c['username'] or '(not set)'}",
                     f"Prefer external subtitle tracks: {'on' if c.get('prefer_subtitles', True) else 'off'}"]
            idx = self.ui.pick("Settings", items)
            if idx is None:
                return
            if idx == 0:
                c["mode"] = "dub" if c["mode"] == "sub" else "sub"
            elif idx == 1:
                c["player_mode"] = "sixel" if c["player_mode"] == "window" else "window"
            elif idx == 2:
                self.auth()
            elif idx == 3:
                raw = self.ui.ask("Percent watched that counts", str(c["threshold"]))
                if raw.isdigit() and 30 <= int(raw) <= 100:
                    c["threshold"] = int(raw)
            elif idx == 4:
                c["title_lang"] = "romaji" if c["title_lang"] == "english" else "english"
            elif idx == 5:
                c["username"] = self.ui.ask("AniList username", c["username"])
            elif idx == 6:
                c["prefer_subtitles"] = not c.get("prefer_subtitles", True)
            save_config(c)

    def auth(self):
        """Connect your AniList account (optional): create an API client once, then paste the token it shows."""
        ui, c = self.ui, self.cfg
        ui.say(ui.bold("AniList sync (optional)"))
        ui.say("1. Open https://anilist.co/settings/developer → 'Create New Client'.")
        ui.say("2. Name: anything.  Redirect URL: https://anilist.co/api/v2/oauth/pin")
        ui.say("3. Copy the client ID it shows.")
        client = ui.ask("Client ID", c.get("client_id", ""))
        if not client.isdigit():
            ui.warn("The client ID is a number. Sync stays off.")
            return
        c["client_id"] = client
        url = f"https://anilist.co/api/v2/oauth/authorize?client_id={client}&response_type=token"
        ui.say(f"4. Authorize here (opening your browser): {url}")
        try:
            self.open_url(url)
        except Exception:
            pass
        token = ui.ask("Paste the token the page shows")
        if not token:
            ui.warn("No token entered. Sync stays off.")
            return
        self.api.token = token.strip()
        try:
            who = self.api.viewer()
        except AniListError as e:
            self.api.token = c.get("token", "")
            ui.error(f"That token did not work: {e}")
            return
        c.update(token=self.api.token, username=who["name"], sync="anilist")
        save_config(c)
        from .sync import make_backend
        self.backend = make_backend(c, self.api)
        ui.ok(f"Connected as {who['name']}. Finished episodes will update your list.")

    def home(self):
        c, ui = self.cfg, self.ui
        if not c.get("username"):
            ui.say(ui.bold("Welcome to anistream."))
            c["username"] = ui.ask("Your AniList username")
            if not c["username"]:
                return
            save_config(c)
            if ui.confirm("Sync watched episodes to AniList? (optional, needs a free API client)", False):
                self.auth()
        self.flush_pending()
        while True:
            try:
                entries = self.api.lists(c["username"])
            except AniListError as e:
                ui.error(str(e))
                if not ui.confirm("Try again?", True):
                    return
                continue
            for e in entries:
                self.entries[e["media"]["id"]] = e
            watching = [e for e in entries if e.get("status") in ("CURRENT", "REPEATING")]
            planning = [e for e in entries if e.get("status") == "PLANNING"]
            ready = sum(1 for e in watching if released(e["media"]) is None or (e.get("progress") or 0) + 1 <= released(e["media"]))
            items = [f"Continue watching  ({ready} ready of {len(watching)})", f"Planning  ({len(planning)})",
                     "Search AniList", "Search all catalogs", "Settings"]
            idx = ui.pick(f"anistream · {c['username']} · {self.sync_label()} · {c['mode']} · {c['player_mode']}", items)
            if idx is None:
                return
            if idx == 0:
                self.list_menu("Continue watching", watching)
            elif idx == 1:
                self.list_menu("Planning", planning)
            elif idx == 2:
                self.search_menu()
            elif idx == 3:
                self.search_catalog_menu()
            elif idx == 4:
                self.settings_menu()
