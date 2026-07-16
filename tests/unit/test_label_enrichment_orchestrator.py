from types import SimpleNamespace
from unittest.mock import MagicMock

from collector.label_enrichment.orchestrator import (
    enrich_label_for_run,
    run_vendors_parallel,
)
from collector.label_enrichment.prompts import (
    PROMPTS, load_builtin_prompts, get_prompt,
)
from collector.label_enrichment.schemas import LabelInfo
from collector.label_enrichment.vendors.base import VendorResponse


def setup_function(_):
    PROMPTS.clear()
    load_builtin_prompts()


def _ok(vendor: str, model: str) -> VendorResponse:
    return VendorResponse(
        parsed=LabelInfo(
            label_name="Drumcode",
            ai_reasoning="none",
            summary="techno",
            confidence=0.9,
        ),
        raw={}, citations=[],
        usage={"input_tokens": 100, "output_tokens": 50, "cost_usd": 0.002},
        latency_ms=200, model=model,
    )


def _err(vendor: str, model: str) -> VendorResponse:
    return VendorResponse(
        parsed=None, raw={}, citations=[],
        usage={"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
        latency_ms=50, model=model, error="boom",
    )


def _make_adapter(name: str, model: str, response: VendorResponse) -> MagicMock:
    adapter = MagicMock()
    adapter.name = name
    adapter.default_model = model
    adapter.run.return_value = response
    return adapter


def test_run_vendors_parallel_returns_one_cell_per_vendor():
    adapters = [
        _make_adapter("gemini", "g", _ok("gemini", "g")),
        _make_adapter("openai", "o", _err("openai", "o")),
    ]
    prompt = get_prompt("label_v3_app_fields")
    cells = run_vendors_parallel(
        adapters=adapters,
        label_name="Drumcode",
        style="techno",
        prompt=prompt,
    )
    assert len(cells) == 2
    by_vendor = {c["vendor"]["name"]: c for c in cells}
    assert by_vendor["gemini"]["error"] is None
    assert by_vendor["openai"]["error"] == "boom"
    assert by_vendor["openai"]["response"]["parsed"] is None


def test_enrich_label_for_run_writes_cells_upserts_info_and_increments():
    adapters = [
        _make_adapter("gemini", "g", _ok("gemini", "g")),
        _make_adapter("openai", "o", _ok("openai", "o")),
    ]
    prompt = get_prompt("label_v3_app_fields")
    repo = MagicMock()
    merge_client = MagicMock()
    merge_client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"tagline":"t","summary":"s","ai_reasoning":"r","notes":null}'))],
        usage=SimpleNamespace(prompt_tokens=200, completion_tokens=80),
    )

    enrich_label_for_run(
        run_id="run-1",
        label_id="lbl-1",
        label_name="Drumcode",
        style="techno",
        adapters=adapters,
        merge_client=merge_client,
        merge_model="deepseek-v4-flash",
        prompt=prompt,
        repository=repo,
        ai_flag_threshold=0.5,
    )

    # mark_run_running was called once
    repo.mark_run_running.assert_called_once_with("run-1")
    # insert_cell called exactly once per vendor (the invariant)
    assert repo.insert_cell.call_count == 2
    # upsert_label_info called once
    repo.upsert_label_info.assert_called_once()
    # project_ai_suspected called once
    repo.project_ai_suspected.assert_called_once()
    # increment_run_counters called once with the full deltas
    repo.increment_run_counters.assert_called_once()
    kwargs = repo.increment_run_counters.call_args.kwargs
    assert kwargs["run_id"] == "run-1"
    assert kwargs["ok_delta"] == 2
    assert kwargs["error_delta"] == 0


def test_enrich_label_for_run_counts_mixed_outcomes():
    adapters = [
        _make_adapter("gemini", "g", _ok("gemini", "g")),
        _make_adapter("openai", "o", _err("openai", "o")),
        _make_adapter("tavily_deepseek", "d", _ok("tavily_deepseek", "d")),
    ]
    prompt = get_prompt("label_v3_app_fields")
    repo = MagicMock()
    merge_client = MagicMock()
    merge_client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"tagline":"t","summary":"s","ai_reasoning":"r","notes":null}'))],
        usage=SimpleNamespace(prompt_tokens=200, completion_tokens=80),
    )
    enrich_label_for_run(
        run_id="run-1",
        label_id="lbl-1",
        label_name="X",
        style="y",
        adapters=adapters,
        merge_client=merge_client,
        merge_model="deepseek-v4-flash",
        prompt=prompt,
        repository=repo,
        ai_flag_threshold=0.5,
    )
    kwargs = repo.increment_run_counters.call_args.kwargs
    assert kwargs["ok_delta"] == 2
    assert kwargs["error_delta"] == 1
    # cost = 0.002 + 0.0 + 0.002 + (deepseek narrative cost)
    assert kwargs["cost_delta"] > 0.003


def test_build_adapters_from_run_config_returns_three_adapters():
    from collector.label_enrichment.orchestrator import build_adapters_from_run_config
    from collector.label_enrichment.settings_provider import LabelEnrichmentSecrets

    adapters = build_adapters_from_run_config(
        vendor_names=["gemini", "openai", "tavily_deepseek"],
        models={
            "gemini": "gemini-3-flash-preview",
            "openai": "gpt-5.4-mini",
            "tavily_deepseek": "deepseek-v4-flash",
        },
        secrets=LabelEnrichmentSecrets(
            gemini_api_key="g", openai_api_key="o",
            tavily_api_key="t", deepseek_api_key="d",
        ),
        request_timeout_s=30.0,
    )
    names = {a.name for a in adapters}
    assert names == {"gemini", "openai", "tavily_deepseek"}
    by_name = {a.name: a for a in adapters}
    assert by_name["gemini"].default_model == "gemini-3-flash-preview"
    # Defaults when the caller doesn't pass openai knobs.
    assert by_name["openai"]._max_tool_calls == 3
    assert by_name["openai"]._reasoning_effort == ""


def test_build_adapters_forwards_openai_knobs():
    from collector.label_enrichment.orchestrator import build_adapters_from_run_config
    from collector.label_enrichment.settings_provider import LabelEnrichmentSecrets

    adapters = build_adapters_from_run_config(
        vendor_names=["openai"],
        models={"openai": "gpt-5.4-mini"},
        secrets=LabelEnrichmentSecrets(
            gemini_api_key="g", openai_api_key="o",
            tavily_api_key="t", deepseek_api_key="d",
        ),
        request_timeout_s=30.0,
        openai_max_tool_calls=5,
        openai_reasoning_effort="low",
    )
    assert adapters[0]._max_tool_calls == 5
    assert adapters[0]._reasoning_effort == "low"


def _run_enrich_label_for_run_with(on_outcome, all_vendors_ok: bool) -> None:
    """Helper that mirrors test_enrich_label_for_run_writes_cells_upserts_info_and_increments
    but controls whether adapters succeed or fail, and passes on_outcome."""
    from types import SimpleNamespace

    if all_vendors_ok:
        vendor_response = _ok("gemini", "g")
    else:
        vendor_response = _err("gemini", "g")

    adapters = [_make_adapter("gemini", "g", vendor_response)]
    prompt = get_prompt("label_v3_app_fields")
    repo = MagicMock()
    merge_client = MagicMock()
    merge_client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(
            content='{"tagline":"t","summary":"s","ai_reasoning":"r","notes":null}'
        ))],
        usage=SimpleNamespace(prompt_tokens=200, completion_tokens=80),
    )

    enrich_label_for_run(
        run_id="run-1",
        label_id="lbl-1",
        label_name="L",
        style="techno",
        adapters=adapters,
        merge_client=merge_client,
        merge_model="deepseek-v4-flash",
        prompt=prompt,
        repository=repo,
        ai_flag_threshold=0.5,
        on_outcome=on_outcome,
    )


def test_enrich_label_invokes_on_outcome_success():
    captured = []
    _run_enrich_label_for_run_with(
        on_outcome=lambda label_id, success: captured.append((label_id, success)),
        all_vendors_ok=True,
    )
    assert captured == [("lbl-1", True)]


def test_enrich_label_invokes_on_outcome_failure():
    captured = []
    _run_enrich_label_for_run_with(
        on_outcome=lambda label_id, success: captured.append((label_id, success)),
        all_vendors_ok=False,
    )
    assert captured == [("lbl-1", False)]


def test_enrich_label_without_on_outcome_does_not_crash():
    # on_outcome defaults to None — must work exactly as before
    _run_enrich_label_for_run_with(on_outcome=None, all_vendors_ok=True)


def test_build_adapters_rejects_unknown_vendor():
    import pytest
    from collector.label_enrichment.orchestrator import build_adapters_from_run_config
    from collector.label_enrichment.settings_provider import LabelEnrichmentSecrets

    with pytest.raises(ValueError, match="unknown vendor"):
        build_adapters_from_run_config(
            vendor_names=["anthropic"],
            models={"anthropic": "claude-opus"},
            secrets=LabelEnrichmentSecrets(
                gemini_api_key="g", openai_api_key="o",
                tavily_api_key="t", deepseek_api_key="d",
            ),
            request_timeout_s=30.0,
        )
