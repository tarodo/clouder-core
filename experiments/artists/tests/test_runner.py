import json

import pytest

from artlab.prompts import PROMPTS, load_builtin_prompts
from artlab.runner import RunSpec, run_matrix
from tests.conftest import StubVendor, make_fixture


@pytest.fixture(autouse=True)
def _prompts_loaded():
    load_builtin_prompts()


def test_run_matrix_writes_cells_and_manifest(tmp_path):
    vendors = [StubVendor("anthropic"), StubVendor("openai")]
    fixtures = [make_fixture("anna", "ANNA"), make_fixture("aphex", "Aphex Twin", "idm")]
    prompts = ["artist_v1"]

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
    assert sample["response"]["parsed"]["artist_name"] == "Stubbed"

    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert {v["name"] for v in manifest["vendors"]} == {"anthropic", "openai"}
    assert sorted(manifest["fixtures"]) == ["anna", "aphex"]


def test_run_matrix_renders_disambiguation_context(tmp_path):
    vendors = [StubVendor("openai")]
    fixtures = [
        make_fixture(
            "anna", "ANNA", "techno",
            sample_tracks=["Hidden Beauties"],
            known_labels=["Drumcode"],
        )
    ]
    spec = RunSpec(
        prompts=["artist_v1"],
        vendors=vendors,
        fixtures=fixtures,
        outputs_root=tmp_path,
        concurrency=1,
    )
    result = run_matrix(spec)
    cell = next(
        f for f in (tmp_path / result.run_id).glob("*.json") if f.name != "manifest.json"
    )
    payload = json.loads(cell.read_text())
    assert "Hidden Beauties" in payload["rendered_user_prompt"]
    assert "Drumcode" in payload["rendered_user_prompt"]


def test_run_matrix_records_vendor_error(tmp_path):
    class FailingVendor(StubVendor):
        def run(self, system, user, schema, model=None):
            from artlab.vendors.base import VendorResponse
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
        prompts=["artist_v1"],
        vendors=[FailingVendor("openai")],
        fixtures=[make_fixture("anna", "ANNA")],
        outputs_root=tmp_path,
        concurrency=1,
    )
    result = run_matrix(spec)
    assert result.totals["ok"] == 0
    assert result.totals["error"] == 1
    cell = next(
        f for f in (tmp_path / result.run_id).glob("*.json") if f.name != "manifest.json"
    )
    payload = json.loads(cell.read_text())
    assert payload["error"] == "simulated failure"
    assert payload["response"]["parsed"] is None
