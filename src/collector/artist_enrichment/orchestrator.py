"""High-level wiring: derive context, run vendors in parallel, aggregate, persist."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from ..label_enrichment.vendors.base import VendorAdapter, VendorResponse
from ..label_enrichment.vendors.pricing import TAVILY_USD_PER_CREDIT
from ..logging_utils import log_event
from ..social_links import SocialsResolver
from .aggregator import merge_cells
from .prompts.base import PromptConfig, render_user
from .repository import ArtistEnrichmentRepository
from .settings_provider import ArtistEnrichmentSecrets


def _cell_payload(vendor: VendorAdapter, response: VendorResponse, artist_name: str) -> dict:
    """Shape mirrors the aggregator input so merge_cells works unchanged."""
    return {
        "vendor": {"name": vendor.name, "model": response.model},
        "fixture": {"artist_name": artist_name},
        "response": {
            "parsed": response.parsed.model_dump() if response.parsed is not None else None,
            "citations": response.citations,
            "usage": response.usage,
            "latency_ms": response.latency_ms,
        },
        "error": response.error,
    }


def run_vendors_parallel(
    *,
    adapters: list[VendorAdapter],
    artist_name: str,
    style: str,
    sample_tracks: list[str],
    known_labels: list[str],
    prompt: PromptConfig,
) -> list[dict]:
    user = render_user(
        prompt,
        artist_name=artist_name,
        style=style,
        sample_tracks=sample_tracks,
        known_labels=known_labels,
    )
    results: list[tuple[VendorAdapter, VendorResponse]] = []
    with ThreadPoolExecutor(max_workers=max(1, len(adapters))) as pool:
        future_to_adapter = {
            pool.submit(
                adapter.run,
                system=prompt.system,
                user=user,
                schema=prompt.schema,
                model=prompt.vendor_overrides.get(adapter.name),
            ): adapter
            for adapter in adapters
        }
        for fut in as_completed(future_to_adapter):
            adapter = future_to_adapter[fut]
            try:
                resp = fut.result()
            except Exception as exc:  # noqa: BLE001 — vendors must not raise, but be defensive
                resp = VendorResponse(
                    parsed=None, raw={}, citations=[],
                    usage={"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
                    latency_ms=0, model=adapter.default_model,
                    error=f"adapter raised: {type(exc).__name__}: {exc}",
                )
            results.append((adapter, resp))

    by_name = {a.name: r for a, r in results}
    return [_cell_payload(a, by_name[a.name], artist_name) for a in adapters]


def enrich_artist_for_run(
    *,
    run_id: str,
    artist_id: str,
    artist_name: str,
    adapters: list[VendorAdapter],
    merge_client: Any,
    merge_model: str,
    prompt: PromptConfig,
    repository: ArtistEnrichmentRepository,
    ai_flag_threshold: float,
    on_outcome: "Callable[[str, bool], None] | None" = None,
    socials_resolver: "SocialsResolver | None" = None,
) -> None:
    """End-to-end: derive context, flip status, run vendors, persist cells + merged + counters."""
    context = repository.derive_artist_context(artist_id)
    repository.mark_run_running(run_id)

    cells = run_vendors_parallel(
        adapters=adapters,
        artist_name=artist_name,
        style=context.style,
        sample_tracks=context.sample_tracks,
        known_labels=context.known_labels,
        prompt=prompt,
    )

    ok = 0
    err = 0
    cost = 0.0
    for adapter, cell in zip(adapters, cells):
        response = _response_from_cell(cell, default_model=adapter.default_model)
        repository.insert_cell(run_id=run_id, artist_id=artist_id, vendor=adapter.name, response=response)
        if cell["error"] is None and cell["response"]["parsed"] is not None:
            ok += 1
        else:
            err += 1
        cost += float(cell["response"]["usage"].get("cost_usd") or 0.0)

    merged_info, meta = merge_cells(cells, merge_client, merge_model)
    cost += float(meta.get("narrative_cost_usd") or 0.0)

    if socials_resolver is not None and not merged_info.instagram_url:
        socials = socials_resolver.resolve(
            kind="artist", name=artist_name, style=context.style, merged=merged_info.model_dump()
        )
        if socials.error is not None:
            log_event(
                "WARNING",
                "socials_resolver_error",
                run_id=run_id,
                entity_type="artist",
                entity=artist_name,
                error_message=socials.error[:500],
            )
        if socials.updates:
            merged_info = merged_info.model_copy(update=socials.updates)
            prov = meta.get("field_provenance") or {}
            tier_label = (
                f"socials_tier{socials.instagram_tier}"
                if socials.instagram_tier is not None
                else "socials_regex"
            )
            for field in socials.updates:
                prov[field] = tier_label
            meta["field_provenance"] = prov
        cost += socials.tavily_credits * TAVILY_USD_PER_CREDIT

    repository.upsert_artist_info(
        artist_id=artist_id,
        last_run_id=run_id,
        prompt_slug=prompt.slug,
        prompt_version=prompt.version,
        merged=merged_info,
        provenance=meta.get("field_provenance") or {},
    )
    repository.project_ai_suspected(artist_id, merged_info, ai_flag_threshold)
    repository.increment_run_counters(run_id=run_id, ok_delta=ok, error_delta=err, cost_delta=cost)

    if on_outcome is not None:
        on_outcome(artist_id, ok > 0)


def _response_from_cell(cell: dict, default_model: str) -> VendorResponse:
    from .schemas import ArtistInfo

    parsed_payload = cell["response"]["parsed"]
    parsed = ArtistInfo.model_validate(parsed_payload) if parsed_payload else None
    return VendorResponse(
        parsed=parsed,
        raw={},
        citations=cell["response"].get("citations") or [],
        usage=cell["response"].get("usage") or {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
        latency_ms=cell["response"].get("latency_ms") or 0,
        model=cell["vendor"].get("model") or default_model,
        error=cell.get("error"),
    )


def build_adapters_from_run_config(
    *,
    vendor_names: list[str],
    models: dict[str, str],
    secrets: "ArtistEnrichmentSecrets",
    request_timeout_s: float,
    openai_max_tool_calls: int = 3,
    openai_reasoning_effort: str = "",
) -> list[VendorAdapter]:
    """Instantiate the requested adapters (reused from label_enrichment.vendors) with per-run models."""
    from ..label_enrichment.vendors.gemini import GeminiAdapter
    from ..label_enrichment.vendors.openai_gpt import OpenAIAdapter
    from ..label_enrichment.vendors.tavily_deepseek import TavilyDeepSeekAdapter

    adapters: list[VendorAdapter] = []
    for name in vendor_names:
        model = models.get(name)
        if not model:
            raise ValueError(f"model missing for vendor {name!r}")
        if name == "gemini":
            adapters.append(GeminiAdapter(api_key=secrets.gemini_api_key, default_model=model, timeout_s=request_timeout_s))
        elif name == "openai":
            adapters.append(OpenAIAdapter(
                api_key=secrets.openai_api_key,
                default_model=model,
                timeout_s=request_timeout_s,
                max_tool_calls=openai_max_tool_calls,
                reasoning_effort=openai_reasoning_effort,
            ))
        elif name == "tavily_deepseek":
            adapters.append(TavilyDeepSeekAdapter(
                tavily_api_key=secrets.tavily_api_key,
                deepseek_api_key=secrets.deepseek_api_key,
                default_model=model,
                timeout_s=request_timeout_s,
            ))
        else:
            raise ValueError(f"unknown vendor {name!r}")
    return adapters
