from pathlib import Path

from splitlab.config import load_settings


def test_load_settings_reads_env_file(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text(
        'OPENAI_API_KEY="sk-test-123"\n'
        "TAVILY_API_KEY=tvly-test-456\n"
        "IGNORED_LINE\n"
        "# comment\n"
    )
    s = load_settings(env)
    assert s.openai_api_key == "sk-test-123"
    assert s.tavily_api_key == "tvly-test-456"
    assert s.openai_model == "gpt-5.4-mini"
    assert s.web_search_usd_per_call == 0.01
    assert s.tavily_usd_per_credit == 0.008
    assert "clouder-prod-aurora" in s.cluster_arn
    assert s.database == "clouder"


def test_missing_keys_raise(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=x\n")
    try:
        load_settings(env)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "TAVILY_API_KEY" in str(exc)
