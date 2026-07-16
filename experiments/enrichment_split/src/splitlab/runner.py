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
        try:
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
        except Exception as exc:  # noqa: BLE001 — a single entity must never kill the run
            return {
                "kind": kind,
                "entity": entity,
                "narrative": {},
                "facts": {},
                "merged": {},
                "provenance": {},
                "web_search_calls": 0,
                "tavily_credits": 0,
                "cost_usd": 0.0,
                "latency_ms": 0,
                "error": f"crashed: {type(exc).__name__}: {exc}",
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
