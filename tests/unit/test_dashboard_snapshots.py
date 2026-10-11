"""scripts/dashboard_snapshots.py renders widgets of the live dashboard to PNG."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "dashboard_snapshots.py"


def _load():
    spec = importlib.util.spec_from_file_location("dashboard_snapshots", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeCloudWatch:
    def __init__(self) -> None:
        self.rendered: list[dict] = []

    def get_dashboard(self, *, DashboardName: str) -> dict:
        assert DashboardName == "clouder-prod-overview"
        widgets = [
            {
                "properties": {
                    "title": "Lambda errors",
                    "metrics": [["AWS/Lambda", "Errors"]],
                    "stat": "Sum",
                }
            },
            {
                "properties": {
                    "title": "DLQ depth",
                    "metrics": [["AWS/SQS", "X"]],
                    "stat": "Maximum",
                }
            },
        ]
        return {"DashboardBody": json.dumps({"widgets": widgets})}

    def get_metric_widget_image(self, *, MetricWidget: str, OutputFormat: str) -> dict:
        self.rendered.append(json.loads(MetricWidget))
        return {"MetricWidgetImage": b"\x89PNG"}


def test_renders_the_chosen_widgets_over_a_week(tmp_path) -> None:
    cw = FakeCloudWatch()

    written = _load().snapshot(cw, "clouder-prod-overview", ["Lambda errors"], tmp_path)

    assert written == [tmp_path / "dashboard-lambda-errors.png"]
    assert written[0].read_bytes() == b"\x89PNG"
    assert cw.rendered == [
        {
            "title": "Lambda errors",
            "metrics": [["AWS/Lambda", "Errors"]],
            "stat": "Sum",
            "start": "-P7D",
            "width": 800,
            "height": 300,
        }
    ]


def test_unknown_widget_title_fails_loudly(tmp_path) -> None:
    try:
        _load().snapshot(FakeCloudWatch(), "clouder-prod-overview", ["Nope"], tmp_path)
    except KeyError as exc:
        assert "Nope" in str(exc)
    else:
        raise AssertionError("expected KeyError")
