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
