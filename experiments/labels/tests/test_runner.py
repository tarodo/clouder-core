import json
from pathlib import Path

import pytest

from lab.prompts import load_builtin_prompts, PROMPTS
from lab.runner import RunSpec, run_matrix
from tests.conftest import StubVendor, make_fixture


@pytest.fixture(autouse=True)
def _prompts_loaded():
    load_builtin_prompts()


def test_run_matrix_writes_cells_and_manifest(tmp_path):
    vendors = [StubVendor("anthropic"), StubVendor("xai")]
    fixtures = [make_fixture("drumcode", "Drumcode"), make_fixture("anjuna", "Anjunadeep", "progressive house")]
    prompts = ["label_v1_baseline", "label_v2_facts"]

    spec = RunSpec(
        prompts=prompts,
        vendors=vendors,
        fixtures=fixtures,
        outputs_root=tmp_path,
        concurrency=2,
    )
    result = run_matrix(spec)

    expected_cells = len(prompts) * len(vendors) * len(fixtures)
    assert result.totals["cells"] == expected_cells
    assert result.totals["ok"] == expected_cells
    assert result.totals["error"] == 0

    run_dir = tmp_path / result.run_id
    cell_files = sorted(p.name for p in run_dir.glob("*.json") if p.name != "manifest.json")
    assert len(cell_files) == expected_cells

    sample = json.loads((run_dir / cell_files[0]).read_text())
    assert sample["run_id"] == result.run_id
    assert "rendered_user_prompt" in sample
    assert sample["response"]["parsed"]["label_name"] == "Stubbed"

    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["run_id"] == result.run_id
    assert {p["slug"] for p in manifest["prompts"]} == set(prompts)
    assert {v["name"] for v in manifest["vendors"]} == {"anthropic", "xai"}
    assert sorted(manifest["fixtures"]) == ["anjuna", "drumcode"]


def test_run_matrix_filters_subset(tmp_path):
    vendors = [StubVendor("anthropic")]
    fixtures = [make_fixture("drumcode", "Drumcode")]
    prompts = ["label_v2_facts"]

    spec = RunSpec(
        prompts=prompts,
        vendors=vendors,
        fixtures=fixtures,
        outputs_root=tmp_path,
        concurrency=1,
    )
    result = run_matrix(spec)
    assert result.totals["cells"] == 1
    cell = next((tmp_path / result.run_id).glob("label_v2_facts__anthropic__drumcode.json"))
    payload = json.loads(cell.read_text())
    assert payload["prompt"]["slug"] == "label_v2_facts"
    assert payload["vendor"]["name"] == "anthropic"


def test_run_matrix_records_vendor_error(tmp_path):
    class FailingVendor(StubVendor):
        def run(self, system, user, schema, model=None):
            from lab.vendors.base import VendorResponse
            return VendorResponse(
                parsed=None,
                raw={},
                citations=[],
                usage={"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
                latency_ms=5,
                model=model or self.default_model,
                error="simulated failure",
            )

    spec = RunSpec(
        prompts=["label_v1_baseline"],
        vendors=[FailingVendor("xai")],
        fixtures=[make_fixture("drumcode", "Drumcode")],
        outputs_root=tmp_path,
        concurrency=1,
    )
    result = run_matrix(spec)
    assert result.totals["ok"] == 0
    assert result.totals["error"] == 1
    cell = next((tmp_path / result.run_id).glob("*.json"))
    payload = json.loads(cell.read_text())
    assert payload["error"] == "simulated failure"
    assert payload["response"]["parsed"] is None
