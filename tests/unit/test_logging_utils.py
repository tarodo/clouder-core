from collector.logging_utils import redact_sensitive_data


def test_redact_sensitive_data_recursive() -> None:
    payload = {
        "bp_token": "secret",
        "nested": {
            "token": "secret-2",
            "safe": "value",
        },
    }

    redacted = redact_sensitive_data(payload)

    assert redacted["bp_token"] == "[REDACTED]"
    assert redacted["nested"]["token"] == "[REDACTED]"
    assert redacted["nested"]["safe"] == "value"


def test_beatport_url_is_not_allowed(capsys):
    from collector import logging_utils as lu

    assert "beatport_url" not in lu.ALLOWED_LOG_FIELDS
    assert "beatport_url_hash" in lu.ALLOWED_LOG_FIELDS


def test_beatport_url_value_is_dropped_from_logs(capsys):
    from collector import logging_utils as lu

    lu.log_event(
        "INFO",
        "test_event",
        beatport_url="https://api.beatport.com?token=SECRET",
        beatport_url_hash="abc123",
    )
    captured = capsys.readouterr().out
    assert "SECRET" not in captured
    assert '"beatport_url"' not in captured  # field name not present either
    assert "abc123" in captured
