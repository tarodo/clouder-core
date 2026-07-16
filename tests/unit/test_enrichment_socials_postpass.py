"""Socials post-pass integration: label + artist enrichment orchestrators.

Covers the 4 label cases (a)-(d) from task-5-brief.md plus one artist mirror:
  (a) resolver NOT called when merged already has instagram_url
  (b) called, updates applied, provenance `socials_tierN`, credits -> cost_delta
  (c) resolver returning updates={} leaves merged/provenance untouched (but the
      tavily credit cost is still charged — resolve() ran)
  (d) socials_resolver=None keeps old behavior byte-for-byte
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from collector.artist_enrichment.orchestrator import enrich_artist_for_run
from collector.artist_enrichment.repository import ArtistContext
from collector.artist_enrichment.prompts import get_prompt as get_artist_prompt
from collector.artist_enrichment.prompts import load_builtin_prompts as load_artist_prompts
from collector.artist_enrichment.schemas import ArtistInfo
from collector.label_enrichment.orchestrator import enrich_label_for_run
from collector.label_enrichment.prompts import PROMPTS, get_prompt, load_builtin_prompts
from collector.label_enrichment.schemas import LabelInfo
from collector.label_enrichment.vendors.base import VendorResponse
from collector.label_enrichment.vendors.pricing import TAVILY_USD_PER_CREDIT
from collector.social_links import SocialsResult


def setup_function(_):
    PROMPTS.clear()
    load_builtin_prompts()
    load_artist_prompts()


class FakeSocialsResolver:
    """Records calls; returns a preset SocialsResult."""

    def __init__(self, result: SocialsResult):
        self.result = result
        self.calls: list[dict] = []

    def resolve(self, *, kind, name, style, merged):
        self.calls.append({"kind": kind, "name": name, "style": style, "merged": merged})
        return self.result


def _label_adapter(instagram_url: str | None) -> MagicMock:
    adapter = MagicMock()
    adapter.name = "gemini"
    adapter.default_model = "g"
    adapter.run.return_value = VendorResponse(
        parsed=LabelInfo(
            label_name="Drumcode",
            ai_reasoning="none",
            summary="techno",
            confidence=0.9,
            instagram_url=instagram_url,
        ),
        raw={}, citations=[],
        usage={"input_tokens": 100, "output_tokens": 50, "cost_usd": 0.002},
        latency_ms=200, model="g",
    )
    return adapter


def _run_label_enrich(*, adapter, repo, socials_resolver, style="techno"):
    prompt = get_prompt("label_v3_app_fields")
    merge_client = MagicMock()  # single parseable cell -> merge_cells never calls it
    enrich_label_for_run(
        run_id="run-1",
        label_id="lbl-1",
        label_name="Drumcode",
        style=style,
        adapters=[adapter],
        merge_client=merge_client,
        merge_model="deepseek-v4-flash",
        prompt=prompt,
        repository=repo,
        ai_flag_threshold=0.5,
        socials_resolver=socials_resolver,
    )


# --- (a) resolver NOT called when merged already has instagram ---


def test_label_resolver_not_called_when_instagram_present():
    adapter = _label_adapter(instagram_url="https://www.instagram.com/drumcode")
    repo = MagicMock()
    resolver = FakeSocialsResolver(
        SocialsResult(updates={}, instagram_tier=None, tavily_credits=0)
    )

    _run_label_enrich(adapter=adapter, repo=repo, socials_resolver=resolver)

    assert resolver.calls == []
    merged = repo.upsert_label_info.call_args.kwargs["merged"]
    assert merged.instagram_url == "https://www.instagram.com/drumcode"


# --- (b) called, updates applied, provenance socials_tier3, credits -> cost_delta ---


def test_label_resolver_applies_updates_and_provenance_and_cost():
    adapter = _label_adapter(instagram_url=None)
    repo = MagicMock()
    resolver = FakeSocialsResolver(
        SocialsResult(
            updates={
                "instagram_url": "https://www.instagram.com/drumcode",
                "twitter_url": "https://x.com/drumcode",
            },
            instagram_tier=3,
            tavily_credits=5,
        )
    )

    _run_label_enrich(adapter=adapter, repo=repo, socials_resolver=resolver, style="techno")

    assert len(resolver.calls) == 1
    call = resolver.calls[0]
    assert call["kind"] == "label"
    assert call["name"] == "Drumcode"
    assert call["style"] == "techno"

    merged = repo.upsert_label_info.call_args.kwargs["merged"]
    assert merged.instagram_url == "https://www.instagram.com/drumcode"
    assert merged.twitter_url == "https://x.com/drumcode"

    provenance = repo.upsert_label_info.call_args.kwargs["provenance"]
    assert provenance["instagram_url"] == "socials_tier3"
    assert provenance["twitter_url"] == "socials_tier3"

    cost_delta = repo.increment_run_counters.call_args.kwargs["cost_delta"]
    # single-source cell cost (0.002) + narrative (0.0, single source) + 5 credits
    expected = 0.002 + 5 * TAVILY_USD_PER_CREDIT
    assert cost_delta == pytest.approx(expected)


# --- provenance falls back to "socials_regex" when instagram_tier is None ---


def test_label_resolver_provenance_regex_label_when_instagram_tier_none():
    """updates exist (e.g. only twitter found) but instagram_tier is None ->
    provenance must be "socials_regex", not the literal "socials_tierNone"."""
    adapter = _label_adapter(instagram_url=None)
    repo = MagicMock()
    resolver = FakeSocialsResolver(
        SocialsResult(
            updates={"twitter_url": "https://x.com/drumcode"},
            instagram_tier=None,
            tavily_credits=1,
        )
    )

    _run_label_enrich(adapter=adapter, repo=repo, socials_resolver=resolver)

    provenance = repo.upsert_label_info.call_args.kwargs["provenance"]
    assert provenance["twitter_url"] == "socials_regex"


# --- (c) resolver returning updates={} leaves merged/provenance untouched ---


def test_label_resolver_empty_updates_leaves_merged_and_provenance_untouched():
    adapter = _label_adapter(instagram_url=None)
    repo = MagicMock()
    resolver = FakeSocialsResolver(
        SocialsResult(updates={}, instagram_tier=None, tavily_credits=2)
    )

    _run_label_enrich(adapter=adapter, repo=repo, socials_resolver=resolver)

    assert len(resolver.calls) == 1
    merged = repo.upsert_label_info.call_args.kwargs["merged"]
    assert merged.instagram_url is None

    provenance = repo.upsert_label_info.call_args.kwargs["provenance"]
    # single-source provenance from merge_cells, untouched by socials
    assert provenance == {"tagline": "single source", "summary": "single source"}

    # cost still reflects the tavily credits spent on the (unsuccessful) lookup
    cost_delta = repo.increment_run_counters.call_args.kwargs["cost_delta"]
    expected = 0.002 + 2 * TAVILY_USD_PER_CREDIT
    assert cost_delta == pytest.approx(expected)


# --- (d) socials_resolver=None keeps old behavior byte-for-byte ---


def test_label_resolver_none_keeps_old_behavior():
    repo_with_none = MagicMock()
    _run_label_enrich(
        adapter=_label_adapter(instagram_url=None), repo=repo_with_none, socials_resolver=None
    )

    repo_default = MagicMock()
    prompt = get_prompt("label_v3_app_fields")
    merge_client = MagicMock()
    enrich_label_for_run(
        run_id="run-1",
        label_id="lbl-1",
        label_name="Drumcode",
        style="techno",
        adapters=[_label_adapter(instagram_url=None)],
        merge_client=merge_client,
        merge_model="deepseek-v4-flash",
        prompt=prompt,
        repository=repo_default,
        ai_flag_threshold=0.5,
        # socials_resolver omitted entirely
    )

    merged_none = repo_with_none.upsert_label_info.call_args.kwargs["merged"]
    merged_default = repo_default.upsert_label_info.call_args.kwargs["merged"]
    assert merged_none == merged_default
    assert merged_none.instagram_url is None

    provenance_none = repo_with_none.upsert_label_info.call_args.kwargs["provenance"]
    provenance_default = repo_default.upsert_label_info.call_args.kwargs["provenance"]
    assert provenance_none == provenance_default

    cost_none = repo_with_none.increment_run_counters.call_args.kwargs["cost_delta"]
    cost_default = repo_default.increment_run_counters.call_args.kwargs["cost_delta"]
    assert cost_none == cost_default == pytest.approx(0.002)


# --- artist mirror of (b) ---


class _ArtistStubAdapter:
    def __init__(self):
        self.name = "openai"
        self.default_model = "stub-model"
        self.supports_web_search = True

    def run(self, *, system, user, schema, model=None):
        parsed = schema.model_validate(
            {
                "artist_name": "ANNA",
                "ai_reasoning": "x",
                "summary": "x",
                "confidence": 0.8,
                "instagram_url": None,
            }
        )
        return VendorResponse(
            parsed=parsed, raw={}, citations=["u"],
            usage={"cost_usd": 0.001}, latency_ms=3,
            model=model or self.default_model, error=None,
        )


def test_artist_resolver_applies_updates_and_provenance_and_cost():
    repo = MagicMock()
    repo.derive_artist_context.return_value = ArtistContext(
        style="techno", sample_tracks=["Hidden Beauties"], known_labels=["Drumcode"]
    )
    adapters = [_ArtistStubAdapter()]
    prompt = get_artist_prompt("artist_v1")
    resolver = FakeSocialsResolver(
        SocialsResult(
            updates={"instagram_url": "https://www.instagram.com/anna"},
            instagram_tier=3,
            tavily_credits=4,
        )
    )

    enrich_artist_for_run(
        run_id="r",
        artist_id="a",
        artist_name="ANNA",
        adapters=adapters,
        merge_client=MagicMock(),
        merge_model="d",
        prompt=prompt,
        repository=repo,
        ai_flag_threshold=0.7,
        socials_resolver=resolver,
    )

    assert len(resolver.calls) == 1
    call = resolver.calls[0]
    assert call["kind"] == "artist"
    assert call["name"] == "ANNA"
    assert call["style"] == "techno"

    merged = repo.upsert_artist_info.call_args.kwargs["merged"]
    assert isinstance(merged, ArtistInfo)
    assert merged.instagram_url == "https://www.instagram.com/anna"

    provenance = repo.upsert_artist_info.call_args.kwargs["provenance"]
    assert provenance["instagram_url"] == "socials_tier3"

    cost_delta = repo.increment_run_counters.call_args.kwargs["cost_delta"]
    expected = 0.001 + 4 * TAVILY_USD_PER_CREDIT
    assert cost_delta == pytest.approx(expected)
