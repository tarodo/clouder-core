# Enrichment Split Experiment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove, in an offline sandbox on 50+50 real prod entities, that the two-pass enrichment (OpenAI narrative + Tavily facts with 3-tier Instagram) beats the current pipeline on coverage and cost — producing a go/no-go report before any prod change.

**Architecture:** New self-contained package `experiments/enrichment_split/` (pattern of `experiments/artists/`). Pass 1: OpenAI Responses API + web_search capped by `max_tool_calls`, narrative-only request schema. Pass 2: Tavily basic search (`include_raw_content`) → regex profile extraction → Tavily Extract on known pages → validated instagram.com top-up; numeric facts extracted by gpt-5.4-mini *without* tools. Deterministic dict merge (fields don't overlap). Metrics compare against each entity's existing prod `merged` payload.

**Tech Stack:** Python 3.12 local venv, pydantic v2, openai SDK, urllib/httpx-free Tavily wrapper (stdlib), boto3 (RDS Data API, sample pull only), pyyaml, pytest (fully mocked — no live calls in tests).

**Spec:** `docs/superpowers/specs/2026-07-15-enrichment-cost-instagram-design.md` (§5 experiment gate; §1 pass design).

## Global Constraints

- **No prod code changes**: nothing under `src/collector/` or `frontend/` is touched.
- **No scraping on our infrastructure**: page content only via Tavily `search`/`extract`.
- **pytest is fully mocked** — live API calls happen only via explicit CLI commands (Tasks 8 and 10).
- Live budget: ~100 entities × 2 variants ≤ **$8 total** (spec estimated $4 for one variant).
- Cost constants: web_search **$0.01/call**, Tavily **$0.008/credit** (basic search = 1, extract = 1 per ≤5 URLs); gpt-5.4-mini tokens are $0 (comped) but token counts are still recorded.
- Models: `gpt-5.4-mini` for both passes.
- Pass thresholds (from spec §5): tagline ≥95%, notable ≥90%, instagram found ≥60% overall with ≥90% spot-check correctness, founded_year/catalog_size not worse than baseline, cost ≤$0.025/run at cap 2.
- Commits: Conventional Commits subject, single `-m` (multi-line via `$(/bin/cat <<'EOF' ... EOF)` — plain `cat` is aliased to `bat` in this shell), no AI-attribution trailers.
- All commands below run from `experiments/enrichment_split/` unless stated otherwise; `aws` CLI lives at `/opt/homebrew/bin/aws`.

## File Structure

```
experiments/enrichment_split/
  README.md
  pyproject.toml
  .gitignore                  # outputs/, .venv/, .env
  .env                        # copied from ../artists/.env (has OPENAI_API_KEY, TAVILY_API_KEY)
  sample/sample.yaml          # checked in — 50 labels + 50 artists pulled from prod (Task 8)
  src/splitlab/
    __init__.py
    config.py                 # .env loader + settings (keys, ARNs, caps, prices)
    schemas.py                # narrative/facts request schemas (label + artist)
    social_regex.py           # profile-URL extraction + handle validation
    tavily_client.py          # search/extract wrapper with credit counter
    facts_pass.py             # 3-tier facts pass + numeric extraction
    narrative_pass.py         # OpenAI narrative pass (capped web_search)
    merge.py                  # two-cell merge + provenance
    sample.py                 # sample.yaml load/save models
    pull_sample.py            # boto3 RDS Data API stratified sample puller
    runner.py                 # pipeline over sample → outputs/<run_id>/
    metrics.py                # fill-rates, IG found-rate, tier rates, cost
    report.py                 # markdown report with gate verdict
    cli.py                    # splitlab pull-sample | run | report
  tests/
    test_config.py  test_schemas.py  test_social_regex.py  test_tavily_client.py
    test_facts_pass.py  test_narrative_pass.py  test_merge.py  test_sample.py
    test_pull_sample.py  test_runner.py  test_metrics.py  test_report.py
  outputs/                    # gitignored run artifacts
```

---

### Task 1: Scaffold the sandbox package

**Files:**
- Create: `experiments/enrichment_split/pyproject.toml`
- Create: `experiments/enrichment_split/.gitignore`
- Create: `experiments/enrichment_split/README.md`
- Create: `experiments/enrichment_split/src/splitlab/__init__.py`
- Create: `experiments/enrichment_split/src/splitlab/config.py`
- Test: `experiments/enrichment_split/tests/test_config.py`

**Interfaces:**
- Produces: `splitlab.config.Settings` dataclass with fields `openai_api_key: str`, `tavily_api_key: str`, `cluster_arn: str`, `secret_arn: str`, `database: str`, `openai_model: str = "gpt-5.4-mini"`, `web_search_usd_per_call: float = 0.01`, `tavily_usd_per_credit: float = 0.008`; function `load_settings(env_path: Path | None = None) -> Settings`.

- [ ] **Step 1: Create pyproject, gitignore, README**

`pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "clouder-enrichment-split-lab"
version = "0.1.0"
description = "Sandbox: two-pass enrichment (OpenAI narrative + Tavily facts) vs prod baseline"
requires-python = ">=3.12"
dependencies = [
  "pydantic>=2.7",
  "openai>=1.60",
  "pyyaml>=6.0",
  "boto3>=1.34",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[project.scripts]
splitlab = "splitlab.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

`.gitignore`:

```
.venv/
outputs/
.env
__pycache__/
*.egg-info/
```

`README.md`:

```markdown
# Enrichment Split Lab

Offline experiment: two-pass enrichment (OpenAI narrative + Tavily facts,
3-tier Instagram) on 50+50 real prod entities vs their prod baselines.
Spec: docs/superpowers/specs/2026-07-15-enrichment-cost-instagram-design.md §5.
Prod code is not touched.

## Setup
    cd experiments/enrichment_split
    python3.12 -m venv .venv
    .venv/bin/pip install -e ".[dev]"
    cp ../artists/.env .env   # OPENAI_API_KEY + TAVILY_API_KEY

## Use
    .venv/bin/splitlab pull-sample                # 50+50 from prod (needs aws creds)
    .venv/bin/splitlab run --cap 2                # live two-pass run
    .venv/bin/splitlab run --cap 2 --limit 3      # smoke on 3 entities
    .venv/bin/splitlab report <run_id>            # metrics + gate verdict

`outputs/` is gitignored; `sample/sample.yaml` is checked in.

## Tests (all mocked, no live calls)
    .venv/bin/pytest -q
```

- [ ] **Step 2: Write the failing test**

`tests/test_config.py`:

```python
from pathlib import Path

from splitlab.config import load_settings


def test_load_settings_reads_env_file(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text(
        'OPENAI_API_KEY="sk-test-123"\n'
        "TAVILY_API_KEY=tvly-test-456\n"
        "IGNORED_LINE\n"
        "# comment\n"
    )
    s = load_settings(env)
    assert s.openai_api_key == "sk-test-123"
    assert s.tavily_api_key == "tvly-test-456"
    assert s.openai_model == "gpt-5.4-mini"
    assert s.web_search_usd_per_call == 0.01
    assert s.tavily_usd_per_credit == 0.008
    assert "clouder-prod-aurora" in s.cluster_arn
    assert s.database == "clouder"


def test_missing_keys_raise(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=x\n")
    try:
        load_settings(env)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "TAVILY_API_KEY" in str(exc)
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd experiments/enrichment_split
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]" -q
.venv/bin/pytest tests/test_config.py -q
```

Expected: FAIL (`ModuleNotFoundError: splitlab.config`).

- [ ] **Step 4: Implement config**

`src/splitlab/__init__.py`: empty file.

`src/splitlab/config.py`:

```python
"""Settings: .env loader (no python-dotenv dep) + fixed experiment constants."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

CLUSTER_ARN = "arn:aws:rds:us-east-1:223458487728:cluster:clouder-prod-aurora"
SECRET_ARN = (
    "arn:aws:secretsmanager:us-east-1:223458487728:"
    "secret:rds!cluster-1ebed129-3946-4c55-a18e-72b53364e0e6-pCk4dS"
)


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    tavily_api_key: str
    cluster_arn: str = CLUSTER_ARN
    secret_arn: str = SECRET_ARN
    database: str = "clouder"
    openai_model: str = "gpt-5.4-mini"
    web_search_usd_per_call: float = 0.01
    tavily_usd_per_credit: float = 0.008


def _parse_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


def load_settings(env_path: Path | None = None) -> Settings:
    path = env_path or Path(__file__).resolve().parents[2] / ".env"
    values = _parse_env(path) if path.exists() else {}
    missing = [k for k in ("OPENAI_API_KEY", "TAVILY_API_KEY") if not values.get(k)]
    if missing:
        raise ValueError(f"missing keys in {path}: {', '.join(missing)}")
    return Settings(
        openai_api_key=values["OPENAI_API_KEY"],
        tavily_api_key=values["TAVILY_API_KEY"],
    )
```

- [ ] **Step 5: Run tests, verify pass**

```bash
.venv/bin/pytest tests/test_config.py -q
```

Expected: `2 passed`.

- [ ] **Step 6: Copy .env and commit**

```bash
cp ../artists/.env .env
cd /Users/roman/Projects/clouder-projects/clouder-core
git add experiments/enrichment_split
git commit -m "chore(experiments): scaffold enrichment_split sandbox"
```

---

### Task 2: Request schemas — narrative and facts

**Files:**
- Create: `experiments/enrichment_split/src/splitlab/schemas.py`
- Test: `experiments/enrichment_split/tests/test_schemas.py`

**Interfaces:**
- Produces: pydantic models `LabelNarrative`, `ArtistNarrative`, `LabelFacts`, `ArtistFacts`. Narrative models carry ONLY narrative fields; facts models ONLY numeric/factual fields. No `ai_*` fields, no URL fields anywhere (URLs are regex-extracted, not LLM-produced). Constant lists `URL_FIELDS` (8 field names) and helpers used by merge/metrics.

- [ ] **Step 1: Write the failing test**

`tests/test_schemas.py`:

```python
from splitlab.schemas import (
    URL_FIELDS,
    ArtistFacts,
    ArtistNarrative,
    LabelFacts,
    LabelNarrative,
)

ALL_REQUEST_MODELS = [LabelNarrative, ArtistNarrative, LabelFacts, ArtistFacts]


def test_no_ai_fields_anywhere():
    for model in ALL_REQUEST_MODELS:
        for name in model.model_fields:
            assert not name.startswith("ai_"), f"{model.__name__}.{name}"


def test_no_url_fields_in_llm_schemas():
    for model in ALL_REQUEST_MODELS:
        for name in model.model_fields:
            assert name not in URL_FIELDS
            assert not name.endswith("_url") and name != "website"


def test_narrative_has_no_numbers():
    for name in ("founded_year", "catalog_size_estimate", "releases_last_12_months"):
        assert name not in LabelNarrative.model_fields
        assert name in LabelFacts.model_fields
    assert "active_since" in ArtistFacts.model_fields
    assert "active_since" not in ArtistNarrative.model_fields


def test_key_narrative_fields_present():
    for f in ("tagline", "summary", "primary_styles", "notable_artists",
              "country", "status", "confidence", "sources"):
        assert f in LabelNarrative.model_fields
    for f in ("tagline", "summary", "bio", "notable_releases",
              "notable_collaborators", "artist_type"):
        assert f in ArtistNarrative.model_fields


def test_url_fields_constant():
    assert set(URL_FIELDS) == {
        "website", "bandcamp_url", "residentadvisor_url", "discogs_url",
        "beatport_url", "soundcloud_url", "instagram_url", "twitter_url",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_schemas.py -q` — Expected: FAIL (module missing).

- [ ] **Step 3: Implement schemas**

`src/splitlab/schemas.py`:

```python
"""Request schemas for the two passes. Narrative = fuzzy/descriptive only;
Facts = sourced numerics/strings only. URLs are never LLM-produced."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

URL_FIELDS = (
    "website", "bandcamp_url", "residentadvisor_url", "discogs_url",
    "beatport_url", "soundcloud_url", "instagram_url", "twitter_url",
)


class LabelNarrative(BaseModel):
    label_name: str
    aliases: list[str] = Field(default_factory=list)
    country: str | None = None
    status: Literal["active", "inactive", "unknown"] = "unknown"
    tagline: str | None = None
    summary: str
    primary_styles: list[str] = Field(default_factory=list)
    notable_artists: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    sources: list[str] = Field(default_factory=list)
    notes: str | None = None


class ArtistNarrative(BaseModel):
    artist_name: str
    aliases: list[str] = Field(default_factory=list)
    real_name: str | None = None
    artist_type: Literal["solo", "duo", "group", "alias_project", "unknown"] = "unknown"
    members: list[str] = Field(default_factory=list)
    country: str | None = None
    city: str | None = None
    status: Literal["active", "inactive", "unknown"] = "unknown"
    primary_styles: list[str] = Field(default_factory=list)
    notable_collaborators: list[str] = Field(default_factory=list)
    notable_releases: list[str] = Field(default_factory=list)
    tagline: str | None = None
    summary: str
    bio: str | None = None
    confidence: float = Field(ge=0, le=1)
    sources: list[str] = Field(default_factory=list)
    notes: str | None = None


class LabelFacts(BaseModel):
    founded_year: int | None = None
    catalog_size_estimate: int | None = None
    releases_last_12_months: int | None = None
    last_release_date: str | None = None
    distribution: str | None = None
    parent_label: str | None = None
    sublabels: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    notes: str | None = None


class ArtistFacts(BaseModel):
    active_since: int | None = None
    labels: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    notes: str | None = None
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_schemas.py -q` — Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
cd /Users/roman/Projects/clouder-projects/clouder-core
git add experiments/enrichment_split
git commit -m "feat(experiments): narrative and facts request schemas"
```

---

### Task 3: Profile-URL regex extraction + handle validation

**Files:**
- Create: `experiments/enrichment_split/src/splitlab/social_regex.py`
- Test: `experiments/enrichment_split/tests/test_social_regex.py`

**Interfaces:**
- Produces:
  - `extract_profiles(text: str) -> dict[str, str]` — maps URL_FIELDS names to normalized profile URLs found in free text (markdown/HTML/plain), first hit per field wins.
  - `extract_instagram(text: str) -> str | None` — convenience: `extract_profiles(text).get("instagram_url")`.
  - `validate_instagram_handle(handle: str, entity_name: str, known_profiles: dict[str, str]) -> bool` — accepts when the normalized handle matches the normalized entity name (substring either way) OR equals a handle from any known profile URL (cross-network match).
  - `handle_of(url: str) -> str | None` — last non-empty path segment of a profile URL.

- [ ] **Step 1: Write the failing test**

`tests/test_social_regex.py`:

```python
from splitlab.social_regex import (
    extract_instagram,
    extract_profiles,
    handle_of,
    validate_instagram_handle,
)

BANDCAMP_PAGE = """
Anarkick Records. Hard techno label.
[Instagram](https://www.instagram.com/anarkick_records) |
<a href="https://anarkickrecs.bandcamp.com/music">music</a>
https://soundcloud.com/anarkickrecs
"""

NOISE_PAGE = """
https://www.instagram.com/p/B42256SBSFa/ deep link to a post
https://www.instagram.com/reel/xyz123/ and a reel
instagram.com/explore/tags/techno
"""


def test_extract_profiles_finds_instagram_and_soundcloud():
    p = extract_profiles(BANDCAMP_PAGE)
    assert p["instagram_url"] == "https://www.instagram.com/anarkick_records"
    assert p["soundcloud_url"] == "https://soundcloud.com/anarkickrecs"
    assert p["bandcamp_url"] == "https://anarkickrecs.bandcamp.com"


def test_post_and_reel_links_are_not_profiles():
    assert extract_instagram(NOISE_PAGE) is None


def test_handle_of():
    assert handle_of("https://www.instagram.com/anarkick_records") == "anarkick_records"
    assert handle_of("https://soundcloud.com/audiocorestudio") == "audiocorestudio"


def test_validate_by_name_similarity():
    assert validate_instagram_handle("anarkick_records", "Anarkick Records", {})
    assert validate_instagram_handle("defiantxrecords", "Defiant", {})
    assert not validate_instagram_handle("ugra.music1111", "Audiocore Production", {})


def test_validate_by_cross_network_match():
    known = {"soundcloud_url": "https://soundcloud.com/audiocorestudio"}
    assert validate_instagram_handle("audiocorestudio", "Audiocore Production", known)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_social_regex.py -q` — Expected: FAIL (module missing).

- [ ] **Step 3: Implement**

`src/splitlab/social_regex.py`:

```python
"""Deterministic profile-URL extraction from page text and handle validation."""

from __future__ import annotations

import re

_NON_PROFILE_IG = {"p", "reel", "reels", "explore", "stories", "accounts", "share", "tv"}
_HANDLE = r"[A-Za-z0-9_.\-]{2,60}"

_PATTERNS: dict[str, re.Pattern[str]] = {
    "instagram_url": re.compile(rf"instagram\.com/({_HANDLE})"),
    "twitter_url": re.compile(rf"(?:twitter|x)\.com/({_HANDLE})"),
    "soundcloud_url": re.compile(rf"soundcloud\.com/({_HANDLE})"),
    "beatport_url": re.compile(rf"beatport\.com/label/({_HANDLE})"),
    "residentadvisor_url": re.compile(rf"ra\.co/labels/({_HANDLE})"),
    "discogs_url": re.compile(rf"discogs\.com/label/({_HANDLE})"),
    "bandcamp_url": re.compile(rf"({_HANDLE})\.bandcamp\.com"),
}

_CANON = {
    "instagram_url": "https://www.instagram.com/{h}",
    "twitter_url": "https://x.com/{h}",
    "soundcloud_url": "https://soundcloud.com/{h}",
    "beatport_url": "https://www.beatport.com/label/{h}",
    "residentadvisor_url": "https://ra.co/labels/{h}",
    "discogs_url": "https://www.discogs.com/label/{h}",
    "bandcamp_url": "https://{h}.bandcamp.com",
}

_TWITTER_SKIP = {"intent", "share", "search", "hashtag", "home", "i"}


def extract_profiles(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for field, pattern in _PATTERNS.items():
        for handle in pattern.findall(text):
            h = handle.rstrip(".")
            if field == "instagram_url" and h.lower() in _NON_PROFILE_IG:
                continue
            if field == "twitter_url" and h.lower() in _TWITTER_SKIP:
                continue
            out[field] = _CANON[field].format(h=h)
            break
    return out


def extract_instagram(text: str) -> str | None:
    return extract_profiles(text).get("instagram_url")


def handle_of(url: str) -> str | None:
    parts = [p for p in url.split("?")[0].split("/") if p]
    if not parts:
        return None
    tail = parts[-1]
    if ".bandcamp.com" in url:
        m = re.search(r"https?://([^./]+)\.bandcamp\.com", url)
        return m.group(1) if m else None
    return tail or None


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def validate_instagram_handle(
    handle: str, entity_name: str, known_profiles: dict[str, str]
) -> bool:
    h = _norm(handle)
    if not h:
        return False
    name = _norm(entity_name)
    # strip generic suffixes so "defiantxrecords" matches "Defiant"
    for stem in (name, name + "records", name + "recs", name + "music", name + "official"):
        if h == stem:
            return True
    if len(name) >= 5 and (name in h or h in name):
        return True
    for url in known_profiles.values():
        known = handle_of(url or "")
        if known and _norm(known) == h:
            return True
    return False
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_social_regex.py -q` — Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
cd /Users/roman/Projects/clouder-projects/clouder-core
git add experiments/enrichment_split
git commit -m "feat(experiments): profile regex extraction + handle validation"
```

---

### Task 4: Tavily client with credit counter

**Files:**
- Create: `experiments/enrichment_split/src/splitlab/tavily_client.py`
- Test: `experiments/enrichment_split/tests/test_tavily_client.py`

**Interfaces:**
- Produces: `TavilyClient(api_key: str, post: Callable[[str, dict], dict] | None = None)` with:
  - `search(query: str, *, max_results: int = 8, include_raw_content: bool = False, include_domains: list[str] | None = None) -> dict` — 1 credit.
  - `extract(urls: list[str]) -> dict` — `ceil(len(urls)/5)` credits.
  - `credits_used: int` property.
  - `post` injection point: `post(path, payload) -> dict` (default: stdlib urllib POST to `https://api.tavily.com/<path>`, 90 s timeout, api key injected into payload).

- [ ] **Step 1: Write the failing test**

`tests/test_tavily_client.py`:

```python
from splitlab.tavily_client import TavilyClient


def make_client(calls):
    def fake_post(path, payload):
        calls.append((path, payload))
        return {"results": []}
    return TavilyClient(api_key="tvly-x", post=fake_post)


def test_search_counts_one_credit_and_sends_params():
    calls = []
    c = make_client(calls)
    c.search("q1", include_raw_content=True)
    c.search("q2", include_domains=["instagram.com"], max_results=5)
    assert c.credits_used == 2
    path, payload = calls[0]
    assert path == "search"
    assert payload["query"] == "q1"
    assert payload["include_raw_content"] is True
    assert payload["search_depth"] == "basic"
    assert payload["api_key"] == "tvly-x"
    assert calls[1][1]["include_domains"] == ["instagram.com"]


def test_extract_counts_credits_per_five_urls():
    calls = []
    c = make_client(calls)
    c.extract(["u1", "u2"])
    assert c.credits_used == 1
    c.extract([f"u{i}" for i in range(6)])
    assert c.credits_used == 3  # 1 + ceil(6/5)
    assert calls[1][0] == "extract"
    assert calls[1][1]["urls"] == [f"u{i}" for i in range(6)]


def test_extract_empty_is_free_noop():
    calls = []
    c = make_client(calls)
    assert c.extract([]) == {"results": []}
    assert c.credits_used == 0
    assert calls == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_tavily_client.py -q` — Expected: FAIL (module missing).

- [ ] **Step 3: Implement**

`src/splitlab/tavily_client.py`:

```python
"""Thin Tavily REST wrapper (stdlib only) with deterministic credit counting.

Pricing model (spec + owner's plan): basic search = 1 credit,
extract = 1 credit per <=5 URLs, $8 per 1000 credits.
"""

from __future__ import annotations

import json
import math
import urllib.request
from typing import Callable


def _default_post(api_key_holder: dict) -> Callable[[str, dict], dict]:
    def post(path: str, payload: dict) -> dict:
        req = urllib.request.Request(
            f"https://api.tavily.com/{path}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=90) as resp:
            return json.load(resp)
    return post


class TavilyClient:
    def __init__(self, api_key: str, post: Callable[[str, dict], dict] | None = None):
        self._api_key = api_key
        self._post = post or _default_post({})
        self._credits = 0

    @property
    def credits_used(self) -> int:
        return self._credits

    def search(
        self,
        query: str,
        *,
        max_results: int = 8,
        include_raw_content: bool = False,
        include_domains: list[str] | None = None,
    ) -> dict:
        payload: dict = {
            "api_key": self._api_key,
            "query": query,
            "search_depth": "basic",
            "max_results": max_results,
            "include_raw_content": include_raw_content,
        }
        if include_domains:
            payload["include_domains"] = include_domains
        self._credits += 1
        return self._post("search", payload)

    def extract(self, urls: list[str]) -> dict:
        if not urls:
            return {"results": []}
        self._credits += math.ceil(len(urls) / 5)
        return self._post("extract", {"api_key": self._api_key, "urls": urls})
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_tavily_client.py -q` — Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
cd /Users/roman/Projects/clouder-projects/clouder-core
git add experiments/enrichment_split
git commit -m "feat(experiments): tavily client with credit counter"
```

---

### Task 5: Facts pass — 3 tiers + numeric extraction

**Files:**
- Create: `experiments/enrichment_split/src/splitlab/facts_pass.py`
- Test: `experiments/enrichment_split/tests/test_facts_pass.py`

**Interfaces:**
- Consumes: `TavilyClient` (Task 4), `extract_profiles`/`extract_instagram`/`validate_instagram_handle`/`handle_of` (Task 3), `LabelFacts`/`ArtistFacts` (Task 2).
- Produces: `run_facts_pass(entity: dict, kind: str, tavily: TavilyClient, llm, model: str) -> FactsResult` where `entity` is a sample row (`{"name": ..., "style": ..., "baseline": {...}}`), `kind` is `"label" | "artist"`, `llm` is an OpenAI-compatible client (`llm.responses.parse(...)`).
  `FactsResult` dataclass: `facts: dict` (LabelFacts/ArtistFacts dump), `profiles: dict[str, str]`, `instagram_tier: int | None` (1/2/3 or None), `credits: int`, `llm_usage: dict`, `error: str | None`.

- [ ] **Step 1: Write the failing test**

`tests/test_facts_pass.py`:

```python
import json
from types import SimpleNamespace

from splitlab.facts_pass import FactsResult, run_facts_pass
from splitlab.schemas import LabelFacts
from splitlab.tavily_client import TavilyClient

ENTITY = {
    "name": "Anarkick Records",
    "style": "hard techno",
    "baseline": {"website": "https://www.anarkick.com", "bandcamp_url": None},
}


class FakeLLM:
    """Mimics client.responses.parse for the no-tools extraction call."""

    def __init__(self, parsed):
        self._parsed = parsed
        self.last_kwargs = None

    @property
    def responses(self):
        return self

    def parse(self, **kwargs):
        self.last_kwargs = kwargs
        usage = SimpleNamespace(input_tokens=1000, output_tokens=50)
        return SimpleNamespace(output_parsed=self._parsed, usage=usage, output=[])


def tavily_with(responses):
    """responses: list of dicts returned per POST in order."""
    it = iter(responses)
    return TavilyClient(api_key="k", post=lambda path, payload: next(it))


def test_tier1_instagram_from_raw_content():
    tavily = tavily_with([
        {"results": [{"url": "https://x.example",
                      "raw_content": "see https://www.instagram.com/anarkick_records ok",
                      "content": "Anarkick Records hard techno label"}]},
    ])
    llm = FakeLLM(LabelFacts(founded_year=2015))
    r = run_facts_pass(ENTITY, "label", tavily, llm, model="gpt-5.4-mini")
    assert isinstance(r, FactsResult)
    assert r.profiles["instagram_url"] == "https://www.instagram.com/anarkick_records"
    assert r.instagram_tier == 1
    assert r.facts["founded_year"] == 2015
    assert r.credits == 1  # search only
    assert r.llm_usage["input_tokens"] == 1000
    # extraction call must not use web_search tools
    assert "tools" not in llm.last_kwargs


def test_tier2_extract_known_pages():
    tavily = tavily_with([
        {"results": [{"url": "https://irrelevant.example", "raw_content": "nothing here"}]},
        {"results": [{"url": "https://www.anarkick.com",
                      "raw_content": "follow https://www.instagram.com/anarkick_records"}]},
    ])
    llm = FakeLLM(LabelFacts())
    r = run_facts_pass(ENTITY, "label", tavily, llm, model="m")
    assert r.instagram_tier == 2
    assert r.credits == 2  # search + extract
    assert r.profiles["instagram_url"].endswith("/anarkick_records")


def test_tier3_topup_with_validation():
    tavily = tavily_with([
        {"results": []},                       # tier1 search: nothing
        {"results": []},                       # tier2 extract on baseline website: nothing
        {"results": [                          # tier3 targeted search
            {"url": "https://www.instagram.com/ugra.music1111"},
            {"url": "https://www.instagram.com/anarkick_records"},
        ]},
    ])
    llm = FakeLLM(LabelFacts())
    r = run_facts_pass(ENTITY, "label", tavily, llm, model="m")
    assert r.instagram_tier == 3
    assert r.profiles["instagram_url"] == "https://www.instagram.com/anarkick_records"
    assert r.credits == 3


def test_no_instagram_anywhere_leaves_null():
    tavily = tavily_with([
        {"results": []},
        {"results": []},
        {"results": [{"url": "https://www.instagram.com/totally.unrelated9"}]},
    ])
    llm = FakeLLM(LabelFacts())
    r = run_facts_pass(ENTITY, "label", tavily, llm, model="m")
    assert r.instagram_tier is None
    assert "instagram_url" not in r.profiles


def test_llm_error_is_captured_not_raised():
    tavily = tavily_with([{"results": []}, {"results": []}, {"results": []}])

    class Boom:
        @property
        def responses(self):
            return self
        def parse(self, **kwargs):
            raise RuntimeError("api down")

    r = run_facts_pass(ENTITY, "label", tavily, Boom(), model="m")
    assert r.error is not None and "api down" in r.error
    assert r.facts == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_facts_pass.py -q` — Expected: FAIL (module missing).

- [ ] **Step 3: Implement**

`src/splitlab/facts_pass.py`:

```python
"""Facts pass: Tavily search -> regex profiles -> extract known pages ->
validated instagram top-up; numeric facts via LLM without tools."""

from __future__ import annotations

from dataclasses import dataclass, field

from .schemas import ArtistFacts, LabelFacts
from .social_regex import (
    extract_profiles,
    handle_of,
    validate_instagram_handle,
)
from .tavily_client import TavilyClient

_SNIPPET_CHARS = 4000
_TOP_RESULTS = 5

FACTS_SYSTEM = (
    "You extract verifiable facts about a music {kind} from the provided web "
    "search results. Use ONLY the provided text. Every non-null field must be "
    "supported by one of the result URLs listed in `sources`. If the text does "
    "not support a field, leave it null. Never guess."
)


@dataclass
class FactsResult:
    facts: dict = field(default_factory=dict)
    profiles: dict = field(default_factory=dict)
    instagram_tier: int | None = None
    credits: int = 0
    llm_usage: dict = field(default_factory=dict)
    error: str | None = None


def _results_text(results: list[dict]) -> str:
    parts = []
    for r in results:
        parts.append(
            f"URL: {r.get('url', '')}\n"
            f"{(r.get('content') or '')[:500]}\n"
            f"{(r.get('raw_content') or '')[:_SNIPPET_CHARS]}"
        )
    return "\n\n---\n\n".join(parts)


def _known_official_urls(entity: dict, profiles: dict) -> list[str]:
    urls = []
    baseline = entity.get("baseline") or {}
    for source in (profiles, baseline):
        for f in ("website", "bandcamp_url", "soundcloud_url"):
            v = source.get(f)
            if isinstance(v, str) and v.startswith("http") and v not in urls:
                urls.append(v)
    return urls[:5]


def run_facts_pass(
    entity: dict, kind: str, tavily: TavilyClient, llm, model: str
) -> FactsResult:
    name = entity["name"]
    style = entity.get("style") or "music"
    schema = LabelFacts if kind == "label" else ArtistFacts
    result = FactsResult()

    noun = "record label" if kind == "label" else "artist"
    search = tavily.search(
        f'"{name}" {style} {noun}', max_results=8, include_raw_content=True
    )
    results = search.get("results") or []
    all_text = _results_text(results)

    # profiles: regex over everything Tavily returned (tier 1)
    result.profiles = extract_profiles(all_text)
    if "instagram_url" in result.profiles:
        result.instagram_tier = 1

    # tier 2: extract known official pages
    if result.instagram_tier is None:
        known = _known_official_urls(entity, result.profiles)
        if known:
            extracted = tavily.extract(known)
            text2 = _results_text(extracted.get("results") or [])
            found = extract_profiles(text2)
            if "instagram_url" in found:
                result.profiles["instagram_url"] = found["instagram_url"]
                result.instagram_tier = 2
            for k, v in found.items():
                result.profiles.setdefault(k, v)

    # tier 3: targeted instagram search with validation
    if result.instagram_tier is None:
        topup = tavily.search(
            f"{name} {style}", max_results=5, include_domains=["instagram.com"]
        )
        for r in topup.get("results") or []:
            handle = handle_of(r.get("url") or "")
            if handle and validate_instagram_handle(handle, name, result.profiles):
                result.profiles["instagram_url"] = f"https://www.instagram.com/{handle}"
                result.instagram_tier = 3
                break

    result.credits = tavily.credits_used

    # numeric facts extraction — no tools, free tokens
    try:
        resp = llm.responses.parse(
            model=model,
            instructions=FACTS_SYSTEM.format(kind=kind),
            input=[{
                "role": "user",
                "content": (
                    f'Extract facts about the {noun} "{name}" (style: {style}) '
                    f"from these search results:\n\n{all_text}"
                ),
            }],
            text_format=schema,
        )
        parsed = getattr(resp, "output_parsed", None)
        result.facts = parsed.model_dump() if parsed is not None else {}
        usage = getattr(resp, "usage", None)
        if usage is not None:
            result.llm_usage = {
                "input_tokens": getattr(usage, "input_tokens", 0) or 0,
                "output_tokens": getattr(usage, "output_tokens", 0) or 0,
            }
    except Exception as exc:  # noqa: BLE001 — experiment must not crash the run
        result.error = f"{type(exc).__name__}: {exc}"
    return result
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_facts_pass.py -q` — Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
cd /Users/roman/Projects/clouder-projects/clouder-core
git add experiments/enrichment_split
git commit -m "feat(experiments): three-tier facts pass with llm extraction"
```

---

### Task 6: Narrative pass — capped agentic search

**Files:**
- Create: `experiments/enrichment_split/src/splitlab/narrative_pass.py`
- Test: `experiments/enrichment_split/tests/test_narrative_pass.py`

**Interfaces:**
- Consumes: `LabelNarrative`/`ArtistNarrative` (Task 2).
- Produces: `run_narrative_pass(entity: dict, kind: str, llm, model: str, max_tool_calls: int) -> NarrativeResult` — `NarrativeResult` dataclass: `narrative: dict`, `web_search_calls: int`, `llm_usage: dict`, `latency_ms: int`, `error: str | None`. Prompts contain NO AI-detection text, no URL/numeric asks.

- [ ] **Step 1: Write the failing test**

`tests/test_narrative_pass.py`:

```python
from types import SimpleNamespace

from splitlab.narrative_pass import (
    LABEL_SYSTEM,
    ARTIST_SYSTEM,
    NarrativeResult,
    run_narrative_pass,
)
from splitlab.schemas import LabelNarrative

LABEL_ENTITY = {"name": "Defiant", "style": "dnb", "baseline": {}}
ARTIST_ENTITY = {
    "name": "Vision", "style": "drum and bass", "baseline": {},
    "sample_tracks": ["Deep"], "known_labels": ["Hospital Records"],
}


class FakeLLM:
    def __init__(self):
        self.last_kwargs = None

    @property
    def responses(self):
        return self

    def parse(self, **kwargs):
        self.last_kwargs = kwargs
        parsed = LabelNarrative(label_name="Defiant", summary="s", confidence=0.5)
        usage = SimpleNamespace(input_tokens=10, output_tokens=5)
        output = [SimpleNamespace(type="web_search_call"),
                  SimpleNamespace(type="web_search_call"),
                  SimpleNamespace(type="message")]
        return SimpleNamespace(output_parsed=parsed, usage=usage, output=output)


def test_passes_cap_and_counts_searches():
    llm = FakeLLM()
    r = run_narrative_pass(LABEL_ENTITY, "label", llm, model="gpt-5.4-mini", max_tool_calls=2)
    assert isinstance(r, NarrativeResult)
    assert llm.last_kwargs["max_tool_calls"] == 2
    assert llm.last_kwargs["tools"] == [{"type": "web_search"}]
    assert r.web_search_calls == 2
    assert r.narrative["label_name"] == "Defiant"


def test_prompts_have_no_ai_or_url_or_numeric_asks():
    for text in (LABEL_SYSTEM, ARTIST_SYSTEM):
        low = text.lower()
        assert "ai-content" not in low and "ai_" not in low
        assert "instagram" not in low and "url" not in low.replace("source urls", "")
        assert "founded" not in low and "catalog" not in low


def test_artist_prompt_uses_context():
    llm = FakeLLM()
    run_narrative_pass(ARTIST_ENTITY, "artist", llm, model="m", max_tool_calls=1)
    user_msg = llm.last_kwargs["input"][0]["content"]
    assert "Hospital Records" in user_msg and "Deep" in user_msg


def test_error_captured():
    class Boom:
        @property
        def responses(self):
            return self
        def parse(self, **kwargs):
            raise RuntimeError("quota")

    r = run_narrative_pass(LABEL_ENTITY, "label", Boom(), model="m", max_tool_calls=2)
    assert r.error and "quota" in r.error
    assert r.narrative == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_narrative_pass.py -q` — Expected: FAIL (module missing).

- [ ] **Step 3: Implement**

`src/splitlab/narrative_pass.py`:

```python
"""Narrative pass: OpenAI Responses API + web_search capped by max_tool_calls.
Request schema is narrative-only, so the model spends its searches on the
description instead of URLs/numbers/AI-detection."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .schemas import ArtistNarrative, LabelNarrative

LABEL_SYSTEM = (
    "You research music record labels. Output structured facts only.\n"
    "Rules:\n"
    "- tagline: ONE punchy sentence (<=100 chars) capturing the label's identity.\n"
    "- summary: 2-4 factual sentences, no superlatives.\n"
    "- primary_styles: 2-5 specific genre tags, lowercase, no umbrella terms.\n"
    "- notable_artists: at most 5 recognizable names, not the full roster.\n"
    "- status: active if there is visible activity in the last ~18 months; "
    "inactive if none for >2 years; unknown otherwise.\n"
    "- If the name is ambiguous, pick the entity matching the style and "
    "explain in `notes`.\n"
    "- List supporting source URLs in `sources`. Never invent facts."
)

ARTIST_SYSTEM = (
    "You research electronic-music artists. Output structured facts only.\n"
    "Rules:\n"
    "- Use the disambiguation context (tracks, labels, style) to lock onto the "
    "CORRECT artist; many share a name. If unresolved, set confidence <= 0.4 "
    "and explain in `notes`.\n"
    "- tagline: ONE punchy sentence (<=100 chars). summary: 2-4 factual "
    "sentences. bio: 1-3 additional factual sentences.\n"
    "- primary_styles: 2-5 specific genre tags, no umbrella terms.\n"
    "- notable_collaborators: frequent co-authors and remixers, not one-offs.\n"
    "- notable_releases: at most 5 anchor tracks/EPs that confirm identity.\n"
    "- List supporting source URLs in `sources`. Never invent facts."
)


@dataclass
class NarrativeResult:
    narrative: dict = field(default_factory=dict)
    web_search_calls: int = 0
    llm_usage: dict = field(default_factory=dict)
    latency_ms: int = 0
    error: str | None = None


def _user_message(entity: dict, kind: str) -> str:
    name = entity["name"]
    style = entity.get("style") or "music"
    if kind == "label":
        return (
            f'Research the record label "{name}" (style: {style}). '
            "Describe its identity, primary styles, notable artists, "
            "status, country, and known aliases."
        )
    tracks = ", ".join(entity.get("sample_tracks") or []) or "unknown"
    labels = ", ".join(entity.get("known_labels") or []) or "unknown"
    return (
        f'Research the electronic-music artist "{name}" (style: {style}).\n'
        f"Disambiguation context — sample tracks: {tracks}; known labels: {labels}.\n"
        "Describe identity (type, members, real name), origin, styles, "
        "collaborators, notable releases, and status."
    )


def run_narrative_pass(
    entity: dict, kind: str, llm, model: str, max_tool_calls: int
) -> NarrativeResult:
    schema = LabelNarrative if kind == "label" else ArtistNarrative
    system = LABEL_SYSTEM if kind == "label" else ARTIST_SYSTEM
    result = NarrativeResult()
    started = time.monotonic()
    try:
        resp = llm.responses.parse(
            model=model,
            instructions=system,
            input=[{"role": "user", "content": _user_message(entity, kind)}],
            tools=[{"type": "web_search"}],
            max_tool_calls=max_tool_calls,
            text_format=schema,
        )
        parsed = getattr(resp, "output_parsed", None)
        result.narrative = parsed.model_dump() if parsed is not None else {}
        result.web_search_calls = sum(
            1
            for item in (getattr(resp, "output", None) or [])
            if "search" in (getattr(item, "type", "") or "").lower()
        )
        usage = getattr(resp, "usage", None)
        if usage is not None:
            result.llm_usage = {
                "input_tokens": getattr(usage, "input_tokens", 0) or 0,
                "output_tokens": getattr(usage, "output_tokens", 0) or 0,
            }
        if not result.narrative:
            result.error = "no output_parsed in response"
    except Exception as exc:  # noqa: BLE001 — experiment must not crash the run
        result.error = f"{type(exc).__name__}: {exc}"
    result.latency_ms = int((time.monotonic() - started) * 1000)
    return result
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_narrative_pass.py -q` — Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
cd /Users/roman/Projects/clouder-projects/clouder-core
git add experiments/enrichment_split
git commit -m "feat(experiments): capped narrative pass via responses api"
```

---

### Task 7: Merge + provenance

**Files:**
- Create: `experiments/enrichment_split/src/splitlab/merge.py`
- Test: `experiments/enrichment_split/tests/test_merge.py`

**Interfaces:**
- Consumes: `NarrativeResult` (Task 6), `FactsResult` (Task 5).
- Produces: `merge_passes(narrative: NarrativeResult, facts: FactsResult) -> tuple[dict, dict]` — `(merged, provenance)`. Merged = narrative fields ∪ facts fields ∪ profile URLs; provenance maps every non-null field to `"narrative"`, `"facts_llm"`, or `"profiles_tier{N}"`/`"profiles_regex"`.

- [ ] **Step 1: Write the failing test**

`tests/test_merge.py`:

```python
from splitlab.facts_pass import FactsResult
from splitlab.merge import merge_passes
from splitlab.narrative_pass import NarrativeResult


def test_merge_unions_all_three_sources():
    narrative = NarrativeResult(narrative={"tagline": "t", "summary": "s", "confidence": 0.8})
    facts = FactsResult(
        facts={"founded_year": 2015, "catalog_size_estimate": None},
        profiles={"instagram_url": "https://www.instagram.com/x", "website": "https://x.com"},
        instagram_tier=2,
    )
    merged, prov = merge_passes(narrative, facts)
    assert merged["tagline"] == "t"
    assert merged["founded_year"] == 2015
    assert merged["instagram_url"] == "https://www.instagram.com/x"
    assert merged["catalog_size_estimate"] is None
    assert prov["tagline"] == "narrative"
    assert prov["founded_year"] == "facts_llm"
    assert prov["instagram_url"] == "profiles_tier2"
    assert prov["website"] == "profiles_regex"
    assert "catalog_size_estimate" not in prov  # null fields get no provenance


def test_facts_never_overwrite_narrative_keys():
    narrative = NarrativeResult(narrative={"notes": "narrative note"})
    facts = FactsResult(facts={"notes": "facts note"})
    merged, prov = merge_passes(narrative, facts)
    assert merged["notes"] == "narrative note"
    assert prov["notes"] == "narrative"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_merge.py -q` — Expected: FAIL.

- [ ] **Step 3: Implement**

`src/splitlab/merge.py`:

```python
"""Union-merge of the two passes. Fields are designed not to overlap;
on accidental overlap the narrative pass wins (it is the identity anchor)."""

from __future__ import annotations

from .facts_pass import FactsResult
from .narrative_pass import NarrativeResult


def merge_passes(narrative: NarrativeResult, facts: FactsResult) -> tuple[dict, dict]:
    merged: dict = {}
    prov: dict = {}

    for key, value in narrative.narrative.items():
        merged[key] = value
        if value not in (None, [], ""):
            prov[key] = "narrative"

    for key, value in facts.facts.items():
        if key in merged and prov.get(key):
            continue
        merged[key] = value
        if value not in (None, [], ""):
            prov[key] = "facts_llm"

    for key, value in facts.profiles.items():
        merged[key] = value
        if key == "instagram_url" and facts.instagram_tier is not None:
            prov[key] = f"profiles_tier{facts.instagram_tier}"
        else:
            prov[key] = "profiles_regex"

    return merged, prov
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_merge.py -q` — Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
cd /Users/roman/Projects/clouder-projects/clouder-core
git add experiments/enrichment_split
git commit -m "feat(experiments): union merge with provenance"
```

---

### Task 8: Sample models, prod puller, and the real sample

**Files:**
- Create: `experiments/enrichment_split/src/splitlab/sample.py`
- Create: `experiments/enrichment_split/src/splitlab/pull_sample.py`
- Create (generated): `experiments/enrichment_split/sample/sample.yaml`
- Test: `experiments/enrichment_split/tests/test_sample.py`
- Test: `experiments/enrichment_split/tests/test_pull_sample.py`

**Interfaces:**
- Produces:
  - `sample.load_sample(path: Path) -> dict[str, list[dict]]` — `{"labels": [...], "artists": [...]}`; each row: `{"id": str, "name": str, "style": str, "stratum": "ig_missing" | "random", "baseline": dict, "sample_tracks": list[str], "known_labels": list[str]}` (tracks/labels lists empty for labels).
  - `sample.save_sample(path: Path, data: dict) -> None`.
  - `pull_sample.pull(settings, execute=None, labels: int = 50, artists: int = 50) -> dict` — `execute(sql: str) -> list[dict]` injection for tests; default uses boto3 `rds-data`.
- Consumes: `Settings` (Task 1).

- [ ] **Step 1: Write the failing tests**

`tests/test_sample.py`:

```python
from pathlib import Path

from splitlab.sample import load_sample, save_sample

DATA = {
    "labels": [{
        "id": "l1", "name": "Defiant", "style": "dnb", "stratum": "ig_missing",
        "baseline": {"instagram_url": None, "website": "https://d.example"},
        "sample_tracks": [], "known_labels": [],
    }],
    "artists": [{
        "id": "a1", "name": "Vision", "style": "drum and bass", "stratum": "random",
        "baseline": {"instagram_url": "https://www.instagram.com/v"},
        "sample_tracks": ["Deep"], "known_labels": ["Hospital Records"],
    }],
}


def test_roundtrip(tmp_path: Path):
    p = tmp_path / "sample.yaml"
    save_sample(p, DATA)
    loaded = load_sample(p)
    assert loaded == DATA


def test_load_validates_required_keys(tmp_path: Path):
    p = tmp_path / "sample.yaml"
    p.write_text("labels:\n  - name: NoId\nartists: []\n")
    try:
        load_sample(p)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "id" in str(exc)
```

`tests/test_pull_sample.py`:

```python
from splitlab.config import Settings
from splitlab.pull_sample import pull

SETTINGS = Settings(openai_api_key="x", tavily_api_key="y")


def fake_execute_factory(rows_by_marker):
    calls = []

    def execute(sql: str):
        calls.append(sql)
        for marker, rows in rows_by_marker.items():
            if marker in sql:
                return rows
        return []

    return execute, calls


def test_pull_builds_strata_and_baseline():
    label_row = {
        "id": "l1", "name": "Defiant", "style": "dnb",
        "merged": '{"instagram_url": null, "website": "https://d.example"}',
    }
    artist_row = {
        "id": "a1", "name": "Vision", "style": "dnb",
        "merged": '{"instagram_url": "https://www.instagram.com/v"}',
        "sample_tracks": "Deep|Deeper", "known_labels": "Hospital Records",
    }
    execute, calls = fake_execute_factory({
        "clouder_label_info": [label_row],
        "clouder_artist_info": [artist_row],
    })
    data = pull(SETTINGS, execute=execute, labels=2, artists=2)
    assert data["labels"][0]["name"] == "Defiant"
    assert data["labels"][0]["baseline"]["website"] == "https://d.example"
    assert data["artists"][0]["sample_tracks"] == ["Deep", "Deeper"]
    assert data["artists"][0]["known_labels"] == ["Hospital Records"]
    # two strata per kind -> 4 SELECTs
    assert sum("instagram_url" in c for c in calls) >= 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_sample.py tests/test_pull_sample.py -q` — Expected: FAIL.

- [ ] **Step 3: Implement**

`src/splitlab/sample.py`:

```python
"""sample.yaml load/save with minimal validation."""

from __future__ import annotations

from pathlib import Path

import yaml

REQUIRED = ("id", "name", "style", "stratum", "baseline", "sample_tracks", "known_labels")


def save_sample(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))


def load_sample(path: Path) -> dict:
    data = yaml.safe_load(path.read_text())
    for kind in ("labels", "artists"):
        for row in data.get(kind) or []:
            missing = [k for k in REQUIRED if k not in row]
            if missing:
                raise ValueError(f"{kind} row missing keys: {missing} ({row.get('name')})")
    return data
```

`src/splitlab/pull_sample.py`:

```python
"""Stratified sample from prod: per kind, N/2 instagram-missing + N/2 random
with instagram present. Baseline = the existing prod merged payload."""

from __future__ import annotations

import json
from typing import Callable

from .config import Settings

_IG_NULL = "(merged->>'instagram_url' IS NULL OR merged->>'instagram_url' = '')"

_LABEL_SQL = """
SELECT l.id::text AS id, l.name AS name,
       coalesce((
           SELECT s.name FROM clouder_albums a
           JOIN clouder_tracks t ON t.album_id = a.id
           JOIN clouder_styles s ON s.id = t.style_id
           WHERE a.label_id = l.id
           GROUP BY s.name ORDER BY count(*) DESC LIMIT 1
       ), 'electronic music') AS style,
       li.merged::text AS merged
FROM clouder_label_info li
JOIN clouder_labels l ON l.id = li.label_id
WHERE {where}
ORDER BY random() LIMIT {limit}
"""

_ARTIST_SQL = """
SELECT ar.id::text AS id, ar.name AS name,
       coalesce((
           SELECT s.name FROM clouder_track_artists ta
           JOIN clouder_tracks t ON t.id = ta.track_id
           JOIN clouder_styles s ON s.id = t.style_id
           WHERE ta.artist_id = ar.id
           GROUP BY s.name ORDER BY count(*) DESC LIMIT 1
       ), 'electronic music') AS style,
       ai.merged::text AS merged,
       coalesce((
           SELECT string_agg(title, '|') FROM (
               SELECT t.title FROM clouder_track_artists ta
               JOIN clouder_tracks t ON t.id = ta.track_id
               WHERE ta.artist_id = ar.id
               ORDER BY t.publish_date DESC NULLS LAST LIMIT 3
           ) x
       ), '') AS sample_tracks,
       coalesce((
           SELECT string_agg(DISTINCT l.name, '|') FROM clouder_track_artists ta
           JOIN clouder_tracks t ON t.id = ta.track_id
           JOIN clouder_albums a ON a.id = t.album_id
           JOIN clouder_labels l ON l.id = a.label_id
           WHERE ta.artist_id = ar.id
       ), '') AS known_labels
FROM clouder_artist_info ai
JOIN clouder_artists ar ON ar.id = ai.artist_id
WHERE {where}
ORDER BY random() LIMIT {limit}
"""


def _default_execute(settings: Settings) -> Callable[[str], list[dict]]:
    import boto3

    client = boto3.client("rds-data", region_name="us-east-1")

    def execute(sql: str) -> list[dict]:
        resp = client.execute_statement(
            resourceArn=settings.cluster_arn,
            secretArn=settings.secret_arn,
            database=settings.database,
            sql=sql,
            formatRecordsAs="JSON",
        )
        return json.loads(resp.get("formattedRecords") or "[]")

    return execute


def _rows_to_entities(rows: list[dict], stratum: str, kind: str) -> list[dict]:
    out = []
    for r in rows:
        merged = r.get("merged")
        baseline = json.loads(merged) if isinstance(merged, str) else (merged or {})
        out.append({
            "id": str(r["id"]),
            "name": r["name"],
            "style": r.get("style") or "electronic music",
            "stratum": stratum,
            "baseline": baseline,
            "sample_tracks": [t for t in (r.get("sample_tracks") or "").split("|") if t],
            "known_labels": [t for t in (r.get("known_labels") or "").split("|") if t],
        })
    return out


def pull(
    settings: Settings,
    execute: Callable[[str], list[dict]] | None = None,
    labels: int = 50,
    artists: int = 50,
) -> dict:
    execute = execute or _default_execute(settings)
    data: dict = {"labels": [], "artists": []}
    for kind, sql, total in (("labels", _LABEL_SQL, labels), ("artists", _ARTIST_SQL, artists)):
        half = total // 2
        for stratum, where, limit in (
            ("ig_missing", _IG_NULL, half),
            ("random", f"NOT {_IG_NULL}", total - half),
        ):
            rows = execute(sql.format(where=where, limit=limit))
            data[kind].extend(_rows_to_entities(rows, stratum, kind))
    return data
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_sample.py tests/test_pull_sample.py -q` — Expected: `3 passed`.

- [ ] **Step 5: Wire `pull-sample` into a minimal CLI**

`src/splitlab/cli.py` (first version; `run`/`report` are added in Task 9):

```python
"""splitlab CLI: pull-sample | run | report."""

from __future__ import annotations

import argparse
from pathlib import Path

from .config import load_settings
from .sample import save_sample

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(prog="splitlab")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_pull = sub.add_parser("pull-sample", help="pull stratified 50+50 sample from prod")
    p_pull.add_argument("--labels", type=int, default=50)
    p_pull.add_argument("--artists", type=int, default=50)

    args = parser.parse_args()
    if args.cmd == "pull-sample":
        from .pull_sample import pull

        settings = load_settings()
        data = pull(settings, labels=args.labels, artists=args.artists)
        out = ROOT / "sample" / "sample.yaml"
        save_sample(out, data)
        print(f"labels={len(data['labels'])} artists={len(data['artists'])} -> {out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: LIVE — generate the real sample from prod**

```bash
cd experiments/enrichment_split
PATH="/opt/homebrew/bin:$PATH" .venv/bin/splitlab pull-sample
```

Expected output: `labels=50 artists=50 -> .../sample/sample.yaml`. If Aurora returns `DatabaseResumingException` (auto-pause), wait 15 s and rerun. Sanity-check the file: `grep -c "stratum: ig_missing" sample/sample.yaml` → 50 (25 per kind).

- [ ] **Step 7: Commit (including the generated sample)**

```bash
cd /Users/roman/Projects/clouder-projects/clouder-core
git add experiments/enrichment_split
git commit -m "feat(experiments): prod sample puller + 50+50 stratified sample"
```

---

### Task 9: Runner, metrics, report, full CLI

**Files:**
- Create: `experiments/enrichment_split/src/splitlab/runner.py`
- Create: `experiments/enrichment_split/src/splitlab/metrics.py`
- Create: `experiments/enrichment_split/src/splitlab/report.py`
- Modify: `experiments/enrichment_split/src/splitlab/cli.py` (add `run`, `report`)
- Test: `experiments/enrichment_split/tests/test_runner.py`, `tests/test_metrics.py`, `tests/test_report.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `runner.run_experiment(sample: dict, settings, cap: int, kinds: list[str], limit: int | None, outputs_root: Path, narrative_fn=run_narrative_pass, facts_fn=run_facts_pass, llm=None, tavily_factory=None) -> str` (returns `run_id`; injection points default to real implementations). Writes per entity `outputs/<run_id>/<kind>__<id>.json` with `{entity, narrative, facts, merged, provenance, cost_usd, latency_ms}` and `outputs/<run_id>/manifest.json` with `{run_id, cap, totals: {entities, ok, errors, web_search_calls, tavily_credits, cost_usd}}`.
  - `metrics.summarize(run_dir: Path) -> dict` — per kind: field fill-rates (new vs baseline), instagram `found_rate`, `found_rate_ig_missing_stratum`, `regression_lost` (had IG in baseline, lost it), tier fire-rates, avg cost, latency p50.
  - `report.render(summary: dict, manifest: dict) -> str` — markdown with the gate table (thresholds from Global Constraints) and PASS/FAIL verdict per criterion.
- Cost per entity: `web_search_calls × 0.01 + tavily_credits × 0.008`.

- [ ] **Step 1: Write the failing tests**

`tests/test_runner.py`:

```python
import json
from pathlib import Path

from splitlab.config import Settings
from splitlab.facts_pass import FactsResult
from splitlab.narrative_pass import NarrativeResult
from splitlab.runner import run_experiment

SETTINGS = Settings(openai_api_key="x", tavily_api_key="y")

SAMPLE = {
    "labels": [
        {"id": "l1", "name": "Defiant", "style": "dnb", "stratum": "ig_missing",
         "baseline": {"instagram_url": None}, "sample_tracks": [], "known_labels": []},
    ],
    "artists": [],
}


def fake_narrative(entity, kind, llm, model, max_tool_calls):
    return NarrativeResult(narrative={"tagline": "t", "summary": "s"}, web_search_calls=2)


def fake_facts(entity, kind, tavily, llm, model):
    return FactsResult(facts={"founded_year": 2001},
                       profiles={"instagram_url": "https://www.instagram.com/d"},
                       instagram_tier=1, credits=1)


class FakeTavily:
    credits_used = 1


def test_run_experiment_writes_cells_and_manifest(tmp_path: Path):
    run_id = run_experiment(
        SAMPLE, SETTINGS, cap=2, kinds=["label", "artist"], limit=None,
        outputs_root=tmp_path, narrative_fn=fake_narrative, facts_fn=fake_facts,
        llm=object(), tavily_factory=lambda: FakeTavily(),
    )
    run_dir = tmp_path / run_id
    cell = json.loads((run_dir / "label__l1.json").read_text())
    assert cell["merged"]["tagline"] == "t"
    assert cell["merged"]["instagram_url"] == "https://www.instagram.com/d"
    assert abs(cell["cost_usd"] - (2 * 0.01 + 1 * 0.008)) < 1e-9
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["cap"] == 2
    assert manifest["totals"]["entities"] == 1
    assert manifest["totals"]["web_search_calls"] == 2
    assert manifest["totals"]["tavily_credits"] == 1
```

`tests/test_metrics.py`:

```python
import json
from pathlib import Path

from splitlab.metrics import summarize


def write_cell(run_dir: Path, name: str, payload: dict):
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / name).write_text(json.dumps(payload))


def test_summarize_fill_and_instagram_rates(tmp_path: Path):
    run_dir = tmp_path / "r1"
    write_cell(run_dir, "label__l1.json", {
        "entity": {"stratum": "ig_missing", "baseline": {"tagline": "x", "instagram_url": None}},
        "merged": {"tagline": "t", "instagram_url": "https://www.instagram.com/a"},
        "provenance": {"instagram_url": "profiles_tier2"},
        "cost_usd": 0.03, "latency_ms": 1000, "kind": "label", "error": None,
    })
    write_cell(run_dir, "label__l2.json", {
        "entity": {"stratum": "random",
                   "baseline": {"tagline": "y", "instagram_url": "https://www.instagram.com/b"}},
        "merged": {"tagline": None, "instagram_url": None},
        "provenance": {},
        "cost_usd": 0.02, "latency_ms": 2000, "kind": "label", "error": None,
    })
    s = summarize(run_dir)
    lab = s["label"]
    assert lab["fill_rates"]["tagline"]["new"] == 0.5
    assert lab["fill_rates"]["tagline"]["baseline"] == 1.0
    assert lab["instagram"]["found_rate"] == 0.5
    assert lab["instagram"]["found_rate_ig_missing_stratum"] == 1.0
    assert lab["instagram"]["regression_lost"] == 1
    assert lab["instagram"]["tiers"] == {"tier2": 1}
    assert abs(lab["avg_cost_usd"] - 0.025) < 1e-9
```

`tests/test_report.py`:

```python
from splitlab.report import render


def test_render_contains_gate_verdicts():
    summary = {
        "label": {
            "fill_rates": {"tagline": {"new": 0.98, "baseline": 0.99},
                           "notable_artists": {"new": 0.92, "baseline": 0.95},
                           "founded_year": {"new": 0.70, "baseline": 0.67},
                           "catalog_size_estimate": {"new": 0.55, "baseline": 0.52}},
            "instagram": {"found_rate": 0.7, "found_rate_ig_missing_stratum": 0.6,
                          "regression_lost": 0, "tiers": {"tier1": 10}},
            "avg_cost_usd": 0.021, "latency_p50_ms": 9000, "errors": 0, "entities": 50,
        },
        "artist": {
            "fill_rates": {"tagline": {"new": 0.99, "baseline": 0.99},
                           "notable_releases": {"new": 0.9, "baseline": 0.9}},
            "instagram": {"found_rate": 0.65, "found_rate_ig_missing_stratum": 0.5,
                          "regression_lost": 1, "tiers": {"tier3": 5}},
            "avg_cost_usd": 0.019, "latency_p50_ms": 8000, "errors": 0, "entities": 50,
        },
    }
    manifest = {"run_id": "r1", "cap": 2,
                "totals": {"cost_usd": 2.0, "web_search_calls": 100, "tavily_credits": 80}}
    md = render(summary, manifest)
    assert "PASS" in md and "gate" in md.lower()
    assert "0.70" in md or "70" in md   # ig found-rate visible
    assert "tier1" in md
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_runner.py tests/test_metrics.py tests/test_report.py -q` — Expected: FAIL.

- [ ] **Step 3: Implement runner**

`src/splitlab/runner.py`:

```python
"""Run the two-pass pipeline over the sample; one JSON cell per entity."""

from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from .config import Settings
from .facts_pass import run_facts_pass
from .merge import merge_passes
from .narrative_pass import run_narrative_pass
from .tavily_client import TavilyClient


def _real_llm(settings: Settings):
    from openai import OpenAI

    return OpenAI(api_key=settings.openai_api_key, timeout=180.0, max_retries=0)


def run_experiment(
    sample: dict,
    settings: Settings,
    cap: int,
    kinds: list[str],
    limit: int | None,
    outputs_root: Path,
    narrative_fn=run_narrative_pass,
    facts_fn=run_facts_pass,
    llm=None,
    tavily_factory=None,
    concurrency: int = 4,
) -> str:
    llm = llm or _real_llm(settings)
    tavily_factory = tavily_factory or (lambda: TavilyClient(settings.tavily_api_key))
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    run_dir = outputs_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    jobs = []
    for kind_plural, kind in (("labels", "label"), ("artists", "artist")):
        if kind not in kinds:
            continue
        rows = sample.get(kind_plural) or []
        jobs.extend((kind, e) for e in (rows[:limit] if limit else rows))

    totals = {"entities": 0, "ok": 0, "errors": 0,
              "web_search_calls": 0, "tavily_credits": 0, "cost_usd": 0.0}

    def process(kind: str, entity: dict) -> dict:
        tavily = tavily_factory()
        narrative = narrative_fn(entity, kind, llm, settings.openai_model, cap)
        facts = facts_fn(entity, kind, tavily, llm, settings.openai_model)
        merged, prov = merge_passes(narrative, facts)
        cost = (narrative.web_search_calls * settings.web_search_usd_per_call
                + facts.credits * settings.tavily_usd_per_credit)
        return {
            "kind": kind,
            "entity": entity,
            "narrative": narrative.narrative,
            "facts": facts.facts,
            "merged": merged,
            "provenance": prov,
            "web_search_calls": narrative.web_search_calls,
            "tavily_credits": facts.credits,
            "cost_usd": cost,
            "latency_ms": narrative.latency_ms,
            "error": narrative.error or facts.error,
        }

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(process, k, e): (k, e) for k, e in jobs}
        done = 0
        for fut in as_completed(futures):
            kind, entity = futures[fut]
            done += 1
            cell = fut.result()
            (run_dir / f"{kind}__{entity['id']}.json").write_text(
                json.dumps(cell, ensure_ascii=False, indent=1)
            )
            totals["entities"] += 1
            totals["ok" if not cell["error"] else "errors"] += 1
            totals["web_search_calls"] += cell["web_search_calls"]
            totals["tavily_credits"] += cell["tavily_credits"]
            totals["cost_usd"] += cell["cost_usd"]
            print(f"[{done}/{len(jobs)}] {kind}:{entity['name']} "
                  f"{'ok' if not cell['error'] else 'ERR: ' + str(cell['error'])[:80]} "
                  f"(${cell['cost_usd']:.4f})")

    (run_dir / "manifest.json").write_text(json.dumps({
        "run_id": run_id, "cap": cap, "kinds": kinds, "totals": totals,
    }, indent=1))
    return run_id
```

- [ ] **Step 4: Implement metrics**

`src/splitlab/metrics.py`:

```python
"""Fill-rates, instagram coverage/tiers, cost/latency per kind vs baseline."""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

TRACKED_FIELDS = {
    "label": ["tagline", "summary", "country", "status", "primary_styles",
              "notable_artists", "founded_year", "catalog_size_estimate",
              "releases_last_12_months", "distribution",
              "website", "bandcamp_url", "discogs_url", "instagram_url"],
    "artist": ["tagline", "summary", "bio", "country", "primary_styles",
               "notable_collaborators", "notable_releases", "active_since",
               "labels", "website", "soundcloud_url", "instagram_url"],
}


def _filled(value) -> bool:
    return value not in (None, "", [], {})


def summarize(run_dir: Path) -> dict:
    cells = defaultdict(list)
    for path in sorted(run_dir.glob("*__*.json")):
        cell = json.loads(path.read_text())
        cells[cell["kind"]].append(cell)

    out: dict = {}
    for kind, rows in cells.items():
        n = len(rows)
        fill: dict = {}
        for field in TRACKED_FIELDS[kind]:
            new = sum(_filled(c["merged"].get(field)) for c in rows) / n
            base = sum(_filled(c["entity"]["baseline"].get(field)) for c in rows) / n
            fill[field] = {"new": round(new, 4), "baseline": round(base, 4)}

        ig_found = [c for c in rows if _filled(c["merged"].get("instagram_url"))]
        missing_stratum = [c for c in rows if c["entity"].get("stratum") == "ig_missing"]
        found_in_missing = [c for c in missing_stratum
                            if _filled(c["merged"].get("instagram_url"))]
        lost = sum(
            1 for c in rows
            if _filled(c["entity"]["baseline"].get("instagram_url"))
            and not _filled(c["merged"].get("instagram_url"))
        )
        tiers = Counter(
            c["provenance"].get("instagram_url", "").replace("profiles_", "")
            for c in ig_found if c["provenance"].get("instagram_url")
        )
        out[kind] = {
            "entities": n,
            "errors": sum(1 for c in rows if c.get("error")),
            "fill_rates": fill,
            "instagram": {
                "found_rate": round(len(ig_found) / n, 4),
                "found_rate_ig_missing_stratum": (
                    round(len(found_in_missing) / len(missing_stratum), 4)
                    if missing_stratum else None
                ),
                "regression_lost": lost,
                "tiers": dict(tiers),
            },
            "avg_cost_usd": round(sum(c["cost_usd"] for c in rows) / n, 5),
            "latency_p50_ms": int(statistics.median(c["latency_ms"] for c in rows)),
        }
    return out
```

- [ ] **Step 5: Implement report**

`src/splitlab/report.py`:

```python
"""Markdown report with the spec §5 gate table."""

from __future__ import annotations

GATES = [
    ("tagline fill", lambda s: min(k["fill_rates"]["tagline"]["new"] for k in s.values()), 0.95, ">="),
    ("notable fill", lambda s: min(
        s["label"]["fill_rates"]["notable_artists"]["new"] if "label" in s else 1.0,
        s["artist"]["fill_rates"]["notable_releases"]["new"] if "artist" in s else 1.0,
    ), 0.90, ">="),
    ("instagram found", lambda s: min(k["instagram"]["found_rate"] for k in s.values()), 0.60, ">="),
    ("avg cost/run", lambda s: max(k["avg_cost_usd"] for k in s.values()), 0.025, "<="),
]


def render(summary: dict, manifest: dict) -> str:
    lines = [
        f"# Enrichment split experiment — run {manifest['run_id']} (cap={manifest['cap']})",
        "",
        f"Totals: {manifest['totals']}",
        "",
        "## Gate (spec §5)",
        "",
        "| criterion | measured | threshold | verdict |",
        "|---|---:|---:|---|",
    ]
    for name, fn, threshold, op in GATES:
        value = fn(summary)
        ok = value >= threshold if op == ">=" else value <= threshold
        lines.append(f"| {name} | {value:.3f} | {op} {threshold} | {'PASS' if ok else 'FAIL'} |")

    for kind, s in summary.items():
        lines += [
            "",
            f"## {kind} ({s['entities']} entities, {s['errors']} errors)",
            "",
            f"instagram: found={s['instagram']['found_rate']:.0%}, "
            f"ig-missing stratum={s['instagram']['found_rate_ig_missing_stratum']}, "
            f"lost vs baseline={s['instagram']['regression_lost']}, "
            f"tiers={s['instagram']['tiers']}",
            f"avg cost=${s['avg_cost_usd']}, latency p50={s['latency_p50_ms']}ms",
            "",
            "| field | new | baseline |",
            "|---|---:|---:|",
        ]
        for field, v in s["fill_rates"].items():
            lines.append(f"| {field} | {v['new']:.0%} | {v['baseline']:.0%} |")

    lines += ["", "## Instagram handles for manual spot-check", ""]
    return "\n".join(lines)
```

Note for the implementer: after the live run, append the spot-check list by reading merged instagram URLs from cells (the CLI does it — Step 6).

- [ ] **Step 6: Extend CLI with `run` and `report`**

Replace the `main()` body in `src/splitlab/cli.py` with:

```python
def main() -> None:
    parser = argparse.ArgumentParser(prog="splitlab")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_pull = sub.add_parser("pull-sample")
    p_pull.add_argument("--labels", type=int, default=50)
    p_pull.add_argument("--artists", type=int, default=50)

    p_run = sub.add_parser("run")
    p_run.add_argument("--cap", type=int, default=2)
    p_run.add_argument("--kind", choices=["label", "artist"], default=None)
    p_run.add_argument("--limit", type=int, default=None)

    p_rep = sub.add_parser("report")
    p_rep.add_argument("run_id")

    args = parser.parse_args()
    settings = load_settings()

    if args.cmd == "pull-sample":
        from .pull_sample import pull

        data = pull(settings, labels=args.labels, artists=args.artists)
        out = ROOT / "sample" / "sample.yaml"
        save_sample(out, data)
        print(f"labels={len(data['labels'])} artists={len(data['artists'])} -> {out}")

    elif args.cmd == "run":
        import json as _json

        from .runner import run_experiment
        from .sample import load_sample

        sample = load_sample(ROOT / "sample" / "sample.yaml")
        kinds = [args.kind] if args.kind else ["label", "artist"]
        run_id = run_experiment(sample, settings, cap=args.cap, kinds=kinds,
                                limit=args.limit, outputs_root=ROOT / "outputs")
        print(f"run_id={run_id}")

    elif args.cmd == "report":
        import json as _json

        from .metrics import summarize
        from .report import render

        run_dir = ROOT / "outputs" / args.run_id
        summary = summarize(run_dir)
        manifest = _json.loads((run_dir / "manifest.json").read_text())
        md = render(summary, manifest)
        ig_lines = []
        for path in sorted(run_dir.glob("*__*.json")):
            cell = _json.loads(path.read_text())
            url = cell["merged"].get("instagram_url")
            if url:
                tier = cell["provenance"].get("instagram_url", "?")
                ig_lines.append(f"- {cell['kind']} **{cell['entity']['name']}** -> {url} ({tier})")
        md += "\n" + "\n".join(ig_lines) + "\n"
        out = ROOT / "outputs" / f"{args.run_id}-report.md"
        out.write_text(md)
        print(md[:2000])
        print(f"\nfull report -> {out}")
```

(Keep the module imports at top: `argparse`, `Path`, `load_settings`, `save_sample`, `ROOT`.)

- [ ] **Step 7: Run all tests**

Run: `.venv/bin/pytest -q` — Expected: all pass (≈25 tests).

- [ ] **Step 8: Commit**

```bash
cd /Users/roman/Projects/clouder-projects/clouder-core
git add experiments/enrichment_split
git commit -m "feat(experiments): runner, metrics, gate report, full cli"
```

---

### Task 10: LIVE runs + experiment report + go/no-go

**Files:**
- Create: `docs/superpowers/specs/<run-date>-enrichment-split-experiment-report.md` (use the actual date)

**Interfaces:**
- Consumes: the full CLI (Task 9), sample (Task 8).

- [ ] **Step 1: Smoke run (3 entities, ~$0.15)**

```bash
cd experiments/enrichment_split
.venv/bin/splitlab run --cap 2 --limit 3
```

Expected: 6 lines `[n/6] ... ok`, `run_id=<id>` printed. Inspect one cell:
`python3 -m json.tool outputs/<id>/label__*.json | head -50` — merged has narrative + facts + profile URLs; `cost_usd` ≈ 0.02–0.04. Fix issues before proceeding (this is the only checkpoint where live-API surprises surface — SDK param names, Tavily response shapes).

- [ ] **Step 2: Full run at cap 2 (~$3)**

```bash
.venv/bin/splitlab run --cap 2
.venv/bin/splitlab report <run_id_cap2>
```

Expected: 100 entities, errors ≤ 5. Report prints the gate table.

- [ ] **Step 3: Full run at cap 1 (~$2)**

```bash
.venv/bin/splitlab run --cap 1
.venv/bin/splitlab report <run_id_cap1>
```

- [ ] **Step 4: Instagram spot-check (manual)**

From each report's handle list take ~20 (mix of tiers and kinds), open profiles, mark correct/wrong. Correctness = the account plausibly belongs to the entity (name/content match). Record the tally — it feeds the ≥90% gate criterion.

- [ ] **Step 5: Tavily credit reconciliation**

```bash
python3 - <<'EOF'
import json, urllib.request
from pathlib import Path
key = [l.split("=",1)[1].strip() for l in Path("experiments/enrichment_split/.env").read_text().splitlines() if l.startswith("TAVILY_API_KEY=")][0]
req = urllib.request.Request("https://api.tavily.com/usage", headers={"Authorization": f"Bearer {key}"})
print(json.load(urllib.request.urlopen(req, timeout=30))["account"])
EOF
```

Compare `plan_usage` delta with the sum of `tavily_credits` from both manifests (the endpoint lags — note the discrepancy rather than blocking on it).

- [ ] **Step 6: Write the experiment report doc**

Create `docs/superpowers/specs/<run-date>-enrichment-split-experiment-report.md` containing: both gate tables (cap 2, cap 1), per-kind fill-rate tables vs baseline, instagram tier fire-rates and spot-check tally, measured avg credits/entity and cost/run, latency, error list, credit reconciliation note, and an explicit **GO / NO-GO** verdict against spec §5 thresholds plus a cap-1 vs cap-2 recommendation. If NO-GO: state which criterion failed and recommend the fallback (mono-OpenAI cap 3 + Tavily IG top-up only, per spec §5).

- [ ] **Step 7: Commit the report**

```bash
cd /Users/roman/Projects/clouder-projects/clouder-core
git add docs/superpowers/specs/*enrichment-split-experiment-report.md
git commit -m "docs(specs): enrichment split experiment report with go/no-go"
```

- [ ] **Step 8: Hand off**

Report the verdict to the owner. On GO — the prod implementation gets its own plan (spec §§1–4, 6–7, rollout 3–6). On NO-GO — plan the fallback instead.

---

## Self-Review Notes

- Spec §5 coverage: sample (Task 8), pipeline (Tasks 2–7), variants cap 1/2 (Task 10), metrics incl. tier fire-rates (Task 9), thresholds (report GATES + Task 10 verdict), budget ≤$8, report doc (Task 10). Spec §§1–4/6–7 are prod scope — intentionally NOT in this plan (separate plan after the gate).
- founded_year/catalog_size "not worse" gate is checked manually in the Task 10 report (baseline columns are in the report tables); the automated GATES list covers the four hard numeric thresholds.
- Type consistency: `FactsResult`/`NarrativeResult` shapes match across Tasks 5–7 and 9; `Settings` fields match Task 1 across Tasks 8–9; sample row schema matches between Tasks 8 and 9.
