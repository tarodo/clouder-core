"""High-level wiring: run vendors in parallel, aggregate, persist."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from .aggregator import merge_cells
from .prompts.base import PromptConfig, render_user
from .repository import LabelEnrichmentRepository
from .settings_provider import LabelEnrichmentSecrets
from .vendors.base import VendorAdapter, VendorResponse


def _cell_payload(
    vendor: VendorAdapter,
    response: VendorResponse,
    label_name: str,
) -> dict:
    """Shape mirrors experiments/labels output so aggregator.merge_cells works unchanged."""
    return {
        "vendor": {"name": vendor.name, "model": response.model},
        "fixture": {"label_name": label_name},
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
    label_name: str,
    style: str,
    prompt: PromptConfig,
) -> list[dict]:
    """Dispatch all adapters concurrently. One call per adapter, one cell per result."""
    user = render_user(prompt, label_name=label_name, style=style)
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

    # Preserve original adapter order for deterministic provenance tie-breaks
    by_name = {a.name: r for a, r in results}
    return [_cell_payload(a, by_name[a.name], label_name) for a in adapters]


def enrich_label_for_run(
    *,
    run_id: str,
    label_id: str,
    label_name: str,
    style: str,
    adapters: list[VendorAdapter],
    merge_client: Any,
    merge_model: str,
    prompt: PromptConfig,
    repository: LabelEnrichmentRepository,
    ai_flag_threshold: float,
    on_outcome: "Callable[[str, bool], None] | None" = None,
) -> None:
    """End-to-end: flip run status, run vendors, persist cells + merged + counters.

    Invariant: writes exactly len(adapters) cell rows per call (ok or error).
    """
    repository.mark_run_running(run_id)

    cells = run_vendors_parallel(
        adapters=adapters,
        label_name=label_name,
        style=style,
        prompt=prompt,
    )

    ok = 0
    err = 0
    cost = 0.0
    for adapter, cell in zip(adapters, cells):
        response = _response_from_cell(cell, default_model=adapter.default_model)
        repository.insert_cell(
            run_id=run_id,
            label_id=label_id,
            vendor=adapter.name,
            response=response,
        )
        if cell["error"] is None and cell["response"]["parsed"] is not None:
            ok += 1
        else:
            err += 1
        cost += float(cell["response"]["usage"].get("cost_usd") or 0.0)

    merged_info, meta = merge_cells(cells, merge_client, merge_model)
    cost += float(meta.get("narrative_cost_usd") or 0.0)

    repository.upsert_label_info(
        label_id=label_id,
        last_run_id=run_id,
        prompt_slug=prompt.slug,
        prompt_version=prompt.version,
        merged=merged_info,
        provenance=meta.get("field_provenance") or {},
    )
    repository.project_ai_suspected(label_id, merged_info, ai_flag_threshold)
    repository.increment_run_counters(
        run_id=run_id,
        ok_delta=ok,
        error_delta=err,
        cost_delta=cost,
    )

    if on_outcome is not None:
        on_outcome(label_id, ok > 0)


def _response_from_cell(cell: dict, default_model: str) -> VendorResponse:
    """Rebuild a VendorResponse from a cell payload — used to keep repository's API stable."""
    from .schemas import LabelInfo

    parsed_payload = cell["response"]["parsed"]
    parsed = LabelInfo.model_validate(parsed_payload) if parsed_payload else None
    return VendorResponse(
        parsed=parsed,
        raw={},
        citations=cell["response"].get("citations") or [],
        usage=cell["response"].get("usage") or {
            "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
        },
        latency_ms=cell["response"].get("latency_ms") or 0,
        model=cell["vendor"].get("model") or default_model,
        error=cell.get("error"),
    )


def build_adapters_from_run_config(
    *,
    vendor_names: list[str],
    models: dict[str, str],
    secrets: "LabelEnrichmentSecrets",
    request_timeout_s: float,
    openai_max_tool_calls: int = 3,
    openai_reasoning_effort: str = "",
) -> list[VendorAdapter]:
    """Instantiate exactly the requested adapters with their per-run models."""
    from .vendors.gemini import GeminiAdapter
    from .vendors.openai_gpt import OpenAIAdapter
    from .vendors.tavily_deepseek import TavilyDeepSeekAdapter

    adapters: list[VendorAdapter] = []
    for name in vendor_names:
        model = models.get(name)
        if not model:
            raise ValueError(f"model missing for vendor {name!r}")
        if name == "gemini":
            adapters.append(GeminiAdapter(
                api_key=secrets.gemini_api_key,
                default_model=model,
                timeout_s=request_timeout_s,
            ))
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
