from __future__ import annotations

from collector.settings import reset_settings_cache
from collector.worker_handler import lambda_handler


class FakeRepo:
    def set_run_completed(self, run_id: str, processed_count: int, finished_at) -> None:
        del run_id, processed_count, finished_at

    def set_run_failed(self, run_id: str, error_code: str, error_message: str, finished_at) -> None:
        del run_id, error_code, error_message, finished_at


def test_invalid_sqs_json_payload_is_skipped(monkeypatch) -> None:
    reset_settings_cache()
    monkeypatch.setenv("RAW_BUCKET_NAME", "test-bucket")
    monkeypatch.setenv("RAW_PREFIX", "raw/bp/releases")
    monkeypatch.setattr("collector.worker_handler.create_clouder_repository_from_env", lambda: FakeRepo())
    monkeypatch.setattr("collector.worker_handler.create_default_s3_client", lambda: object())

    event = {
        "Records": [
            {
                "body": "{bad-json}",
                "messageAttributes": {},
            }
        ]
    }

    response = lambda_handler(event, context=None)

    assert response == {"processed": 0}
    reset_settings_cache()
