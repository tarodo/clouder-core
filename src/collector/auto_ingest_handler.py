"""Auto-ingest Lambda (docs/data/auto-ingest.md).

`auth_check`: log in to Beatport with the owner's credentials and report only
whether it worked — the gate before scheduling real ingests from AWS. The token
is obtained per invocation, kept in memory and never returned or logged.
"""

from __future__ import annotations

import os
from typing import Any, Mapping

from . import secrets
from .beatport_auth import BeatportAuthError, fetch_access_token
from .logging_utils import log_event


def _read_credentials() -> tuple[str, str]:
    return (
        secrets._fetch_ssm_parameter(os.environ["BEATPORT_USERNAME_SSM_PARAMETER"]),
        secrets._fetch_ssm_parameter(os.environ["BEATPORT_PASSWORD_SSM_PARAMETER"]),
    )


def auth_check() -> dict[str, Any]:
    try:
        username, password = _read_credentials()
    except Exception:  # missing parameter or env: report, do not echo anything
        log_event("WARNING", "auto_ingest_auth_check", passed=False, phase="credentials")
        return {"ok": False, "step": "credentials", "status": None}
    try:
        fetch_access_token(username, password)
    except BeatportAuthError as exc:
        log_event(
            "WARNING", "auto_ingest_auth_check", passed=False, phase=exc.step,
            status_code=exc.status,
        )
        return {"ok": False, "step": exc.step, "status": exc.status}
    log_event("INFO", "auto_ingest_auth_check", passed=True)
    return {"ok": True}


def lambda_handler(event: Mapping[str, Any] | None, context: Any) -> dict[str, Any]:
    del context
    action = (event or {}).get("action")
    if action == "auth_check":
        return auth_check()
    raise ValueError(f"unknown auto-ingest action: {action!r}")
