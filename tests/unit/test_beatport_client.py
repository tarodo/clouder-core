from collector.beatport_client import is_retryable_status


def test_retryable_status_matrix() -> None:
    assert is_retryable_status(429)
    assert is_retryable_status(503)
    assert not is_retryable_status(401)
    assert not is_retryable_status(403)
