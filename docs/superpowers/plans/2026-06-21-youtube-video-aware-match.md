# Video-aware Comment-Match Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fuzzy scorer in the fallback resolver with a token-set matcher (all query words present in the candidate title) plus a version-marker guard, so the comments-collect worker actually finds a regular YouTube video for the track.

**Architecture:** A new pure `video_matches(artist, title, candidate_title) -> bool` (token coverage + version equality). `YouTubeCommentProvider.resolve_alternate_videos` searches `"{Artists} - {Title}"`, filters candidates through it, and returns matches in ytmusicapi relevance order (top 3). The vendor-match fuzzy scorer and the worker are untouched. Backend only — no migration/infra/OpenAPI/frontend.

**Tech Stack:** Python 3, ytmusicapi (unauthenticated, already a dependency).

---

## Conventions for every task

- **Worktree venv:** `.venv` lives at the MAIN repo root. Run pytest by absolute path:
  `WT=/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/add_comments_collect`
  `PYTEST=/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest`
  Run from `$WT`. `pytest.ini` sets `PYTHONPATH=src`.
- Branch is already `feat/youtube-video-aware-match` (off `origin/main`).
- Commit with plain `git commit -m "..."` (Conventional Commits). NO `Co-Authored-By`/AI trailer (a hook blocks it). ACTUALLY RUN `git commit` and report the SHA.

## File Structure

- **Create:** `src/collector/providers/youtube/video_match.py` — the pure matcher + token-class constants.
- **Modify:** `src/collector/providers/youtube/comments.py` — rewrite `resolve_alternate_videos`; drop the `threshold` ctor param.
- **Create:** `tests/unit/test_youtube_video_match.py` — matcher unit tests.
- **Modify:** `tests/unit/test_youtube_comment_provider.py` — replace the resolver tests (the old ones used `threshold`/scoring).

No other files. The collect (Data API) tests in `test_youtube_comment_provider.py` (top of file) are unaffected.

---

## Task 1: Pure token-set matcher

**Files:**
- Create: `src/collector/providers/youtube/video_match.py`
- Test: `tests/unit/test_youtube_video_match.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_youtube_video_match.py`:
```python
from collector.providers.youtube.video_match import video_matches


def test_positive_clean_title():
    assert video_matches("Lychee", "Back In Time", "Lychee - Back in Time")


def test_positive_second_artist_format():
    assert video_matches("Tremor", "Disposition", "Tremor - Disposition")


def test_noise_in_title_still_matches():
    assert video_matches(
        "Lychee", "Back In Time",
        "Lychee - Back in Time (Official Video) [Fokuz Recordings]",
    )


def test_stopword_missing_in_title_still_matches():
    # query word "in" is a stopword; the title omits it -> still a match
    assert video_matches("Lychee", "Back In Time", "Lychee - Back Time")


def test_negative_different_track_same_artist():
    assert not video_matches(
        "Dysfunctional Family", "Overwhelmingly Positive",
        "Dysfunctional Family Christmas (Music Video)",
    )


def test_negative_unrelated():
    assert not video_matches("TENEM", "Sonar", "Liquid Drum and Bass Mix 747")


def test_version_original_rejects_remix():
    assert not video_matches("Lychee", "Back In Time", "Lychee - Back in Time (Someone Remix)")


def test_version_remix_track_matches_remix_video():
    assert video_matches(
        "Lychee", "Back In Time (Klute Remix)", "Lychee - Back in Time (Klute Remix)",
    )


def test_version_original_rejects_extended_mix():
    assert not video_matches("Lychee", "Back In Time", "Lychee - Back in Time (Extended Mix)")


def test_version_original_mix_candidate_matches_original():
    assert video_matches("Lychee", "Back In Time", "Lychee - Back in Time (Original Mix)")


def test_empty_query_returns_false():
    assert not video_matches("", "", "anything at all")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd $WT && $PYTEST tests/unit/test_youtube_video_match.py -q`
Expected: FAIL — `ModuleNotFoundError: collector.providers.youtube.video_match`.

- [ ] **Step 3: Implement the matcher**

Create `src/collector/providers/youtube/video_match.py`:
```python
"""Token-set matcher for picking a regular YouTube video for a track.

YouTube `videos` results expose the uploading channel as the "artist" and embed
the artist in the title ("Artist - Title"), so the vendor-match fuzzy scorer is
unusable here. Instead require every meaningful query word (artist + title) to
appear in the candidate title (coverage == 1.0), and require the version markers
to match (so an original track does not match a remix video, and vice versa).
"""

from __future__ import annotations

import re

_STOPWORDS = {"the", "a", "an", "of", "in", "on", "and", "to"}

_NOISE = {
    "official", "video", "audio", "lyric", "lyrics", "hd", "hq", "4k", "mv",
    "visualizer", "visualiser", "premiere", "ft", "feat", "featuring", "music",
    "clip", "free", "download", "out", "now", "prod",
}

_VERSION_MARKERS = {
    "remix", "edit", "bootleg", "mashup", "rework", "flip", "vip", "instrumental",
    "acapella", "acappella", "live", "cover", "version", "remaster", "remastered",
    "sped", "slowed", "karaoke", "dub", "extended", "radio", "mix",
}


def _tokens(s: str) -> list[str]:
    return [w for w in re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).split() if w]


def _versions(tokens: set[str]) -> set[str]:
    v = _VERSION_MARKERS & tokens
    # "original mix"/"original version" denotes the original, not a distinct version.
    if "original" in tokens:
        v -= {"mix", "version"}
    return v


def video_matches(query_artist: str, query_title: str, candidate_title: str) -> bool:
    q_all = set(_tokens(query_artist) + _tokens(query_title))
    c_all = set(_tokens(candidate_title))

    q_sig = q_all - _STOPWORDS - _NOISE
    c_sig = c_all - _NOISE
    if not q_sig:
        return False

    coverage = q_sig <= c_sig
    version_ok = _versions(q_all) == _versions(c_all)
    return coverage and version_ok
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd $WT && $PYTEST tests/unit/test_youtube_video_match.py -q`
Expected: PASS (11 tests).

- [ ] **Step 5: Commit**

```bash
cd $WT && git add src/collector/providers/youtube/video_match.py tests/unit/test_youtube_video_match.py
git commit -m "feat(providers): add token-set video matcher for comment fallback"
git rev-parse --short HEAD
```

---

## Task 2: Use the matcher in the resolver

**Files:**
- Modify: `src/collector/providers/youtube/comments.py`
- Test: `tests/unit/test_youtube_comment_provider.py`

The current `resolve_alternate_videos` (lines ~90-125) uses `score_candidate` +
`get_vendor_match_settings().fuzzy_match_threshold` and `build_query`, and the
ctor (lines ~31-46) has a `threshold` param. Replace both.

- [ ] **Step 1: Replace the resolver tests (write the new failing tests)**

In `tests/unit/test_youtube_comment_provider.py`, DELETE everything from
`class FakeYtClient:` to end of file (the old resolver tests that pass
`threshold=...`), and append this in its place:
```python
class FakeYtClient:
    def __init__(self, results):
        self._results = results
        self.calls = []

    def search(self, query, filter=None, limit=None):
        self.calls.append((query, filter, limit))
        return self._results


def _video(video_id, title):
    # artists is the uploading channel on purpose — the matcher must ignore it.
    return {"videoId": video_id, "title": title,
            "artists": [{"name": "Some Channel"}], "duration_seconds": 200}


def _provider(results):
    return YouTubeCommentProvider(api_key="K", session=object(),
                                  ytmusic_client=FakeYtClient(results))


def test_resolve_returns_matching_videos_in_search_order():
    results = [
        _video("good1", "Lychee - Back in Time"),
        _video("bad", "Totally Different Song"),
        _video("good2", "Lychee - Back in Time (Official Video)"),
    ]
    provider = _provider(results)
    out = provider.resolve_alternate_videos(
        artist="Lychee", title="Back In Time", duration_ms=200000, exclude_video_id="art1"
    )
    assert out == ["good1", "good2"]
    q, flt, _ = provider._ytmusic_client.calls[-1]
    assert flt == "videos"
    assert q == "Lychee - Back In Time"


def test_resolve_excludes_art_track():
    results = [_video("art1", "Lychee - Back in Time"), _video("good1", "Lychee - Back in Time")]
    provider = _provider(results)
    out = provider.resolve_alternate_videos(
        artist="Lychee", title="Back In Time", duration_ms=None, exclude_video_id="art1"
    )
    assert out == ["good1"]


def test_resolve_caps_at_three():
    results = [_video(f"v{i}", "Lychee - Back in Time") for i in range(6)]
    provider = _provider(results)
    out = provider.resolve_alternate_videos(
        artist="Lychee", title="Back In Time", duration_ms=None, exclude_video_id="art1"
    )
    assert out == ["v0", "v1", "v2"]


def test_resolve_empty_when_nothing_matches():
    provider = _provider([_video("v1", "Completely Unrelated Mix 2026")])
    out = provider.resolve_alternate_videos(
        artist="Lychee", title="Back In Time", duration_ms=None, exclude_video_id="art1"
    )
    assert out == []


def test_resolve_rejects_remix_for_original():
    provider = _provider([_video("rmx", "Lychee - Back in Time (Klute Remix)")])
    out = provider.resolve_alternate_videos(
        artist="Lychee", title="Back In Time", duration_ms=None, exclude_video_id="art1"
    )
    assert out == []


def test_resolve_tolerates_malformed_results():
    provider = _provider(["junk", {}, {"title": "no id"}])
    out = provider.resolve_alternate_videos(
        artist="Lychee", title="Back In Time", duration_ms=None, exclude_video_id="art1"
    )
    assert out == []
```

- [ ] **Step 2: Run to verify the new resolver tests fail**

Run: `cd $WT && $PYTEST tests/unit/test_youtube_comment_provider.py -q`
Expected: FAIL — the new tests fail because the resolver still scores/threshold-gates and builds `"artist title"` (no dash); the query assertion `q == "Lychee - Back In Time"` and the match-based expectations won't hold yet. (The collect tests at the top still pass.)

- [ ] **Step 3: Rewrite the resolver + drop the `threshold` param**

In `src/collector/providers/youtube/comments.py`:

(a) Remove the `threshold` param from `__init__`. Change the signature/body:
```python
    def __init__(
        self,
        *,
        api_key: str,
        session: Any,
        ytmusic_client: Any | None = None,
        ytmusic_client_factory: Any = _default_ytmusic_factory,
        search_limit: int = 10,
    ) -> None:
        self._api_key = api_key
        self._session = session
        self._ytmusic_client = ytmusic_client
        self._ytmusic_client_factory = ytmusic_client_factory
        self._search_limit = search_limit
```

(b) Replace the entire `resolve_alternate_videos` method with:
```python
    def resolve_alternate_videos(
        self,
        *,
        artist: str,
        title: str,
        duration_ms: int | None,
        exclude_video_id: str,
    ) -> list[str]:
        from ..ytmusic.normalize import result_to_ref
        from .video_match import video_matches

        query = f"{artist} - {title}".strip()
        raw_results = self._get_ytmusic().search(
            query, filter="videos", limit=self._search_limit
        )
        out: list[str] = []
        for raw in raw_results or []:
            if not isinstance(raw, dict):
                continue
            ref = result_to_ref(raw)
            if ref is None or ref.vendor_track_id == exclude_video_id:
                continue
            if video_matches(artist, title, ref.title):
                out.append(ref.vendor_track_id)
                if len(out) >= 3:
                    break
        return out
```
(`duration_ms` stays in the signature — it is part of the `CommentProvider` protocol — but is no longer used. The old local imports of `build_query`, `score_candidate`, and `get_vendor_match_settings` are gone.)

- [ ] **Step 4: Run the full provider test file**

Run: `cd $WT && $PYTEST tests/unit/test_youtube_comment_provider.py -q`
Expected: PASS (the collect tests + the 6 new resolver tests).

- [ ] **Step 5: Run the dependent suites to confirm no regression**

Run: `cd $WT && $PYTEST tests/unit/test_comment_registry.py tests/unit/test_comments_collect_handler.py -q`
Expected: PASS. (The registry builds the provider with `api_key=`/`session=` only — unaffected by dropping `threshold`. The worker calls `resolve_alternate_videos` with the same keyword args — unaffected.)

- [ ] **Step 6: Commit**

```bash
cd $WT && git add src/collector/providers/youtube/comments.py tests/unit/test_youtube_comment_provider.py
git commit -m "feat(providers): gate comment fallback on token-set video match"
git rev-parse --short HEAD
```

---

## Task 3: Full verification + finish

- [ ] **Step 1: Backend suite**

Run: `cd $WT && /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest -q`
Expected: all pass (no migration/infra/frontend/OpenAPI touched).

- [ ] **Step 2: Confirm scope**

Run: `cd $WT && git status --porcelain` (expect clean) and
`git diff --stat origin/main` — expect only: the two docs, `video_match.py`,
`comments.py`, and the two test files.

- [ ] **Step 3: Finish the branch**

Use `superpowers:finishing-a-development-branch`. PR title/body via
`caveman:caveman-commit`. Deploy is via merge → CI (no new secrets/infra; the
`YOUTUBE_API_KEY` wiring fix is already on main). After deploy, the existing
`disabled` collections do not auto-recollect — re-enqueue them (as during the
incident) or wait for new matches.

---

## Notes / decisions baked in

- Coverage gate is all-or-nothing (every meaningful query token in the title); no numeric threshold knob.
- Version-marker equality blocks "original ↛ remix"; coverage already blocks "remix ↛ original" (remixer name/`remix` missing from an original's title).
- Artist is matched via the title words, not the (channel) artist field.
- No duration guard (coverage excludes mega-mixes; revisit in prod).
- `vendor_match/scorer.py` and the playlist-publish path are untouched.
