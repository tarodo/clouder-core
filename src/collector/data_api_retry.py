"""Retry wrapper for RDS Data API transient errors.

Aurora Serverless v2 with min_acu=0 pauses after idle; first call after
wake throws DatabaseResumingException. Wrap Data API calls with exp backoff.
"""
from __future__ import annotations

import functools
import random
import time
from typing import Any, Callable, TypeVar

from botocore.exceptions import ClientError

from .logging_utils import log_event

TRANSIENT_ERROR_CODES = frozenset(
    {
        "DatabaseResumingException",
        "StatementTimeoutException",
        "InternalServerErrorException",
        "ServiceUnavailableError",
        "ThrottlingException",
    }
)

PRE_EXECUTION_ERROR_CODES = frozenset(
    {
        "DatabaseResumingException",
        "ServiceUnavailableError",
        "ThrottlingException",
    }
)

F = TypeVar("F", bound=Callable[..., Any])


def retry_data_api(
    max_attempts: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
) -> Callable[[F], F]:
    """Retry decorator for RDS Data API client methods.

    Retries only on transient error codes in ``TRANSIENT_ERROR_CODES``.

    IDEMPOTENCY CONTRACT: Some transient codes (``StatementTimeoutException``,
    ``InternalServerErrorException``) can occur after the server has partially
    applied the statement. Callers MUST ensure retried operations are
    idempotent — use within an explicit transaction (begin/commit/rollback)
    so a retried ``execute`` with ``transaction_id`` is replayed atomically,
    OR use UPSERT/ON CONFLICT semantics for writes outside transactions.

    Pre-execution codes (``DatabaseResumingException``, ``ServiceUnavailableError``,
    ``ThrottlingException``) are always safe to retry.
    """
    return _retry(TRANSIENT_ERROR_CODES, max_attempts, base_delay, max_delay)


def retry_data_api_pre_execution(
    max_attempts: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
) -> Callable[[F], F]:
    """Retry decorator for RDS Data API calls where the operation must
    not be re-executed if it may have already succeeded server-side.

    Narrower than ``retry_data_api``: only retries codes that signal the
    request never reached the engine (Aurora resuming, throttling,
    service unavailable). Use for ``commit_transaction`` /
    ``rollback_transaction`` where a retry after partial completion
    would corrupt state.
    """
    return _retry(PRE_EXECUTION_ERROR_CODES, max_attempts, base_delay, max_delay)


def _retry(
    codes: frozenset[str],
    max_attempts: int,
    base_delay: float,
    max_delay: float,
) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            attempt = 0
            while True:
                attempt += 1
                try:
                    return func(*args, **kwargs)
                except ClientError as exc:
                    code = exc.response.get("Error", {}).get("Code", "")
                    if code not in codes or attempt >= max_attempts:
                        raise
                    cap = min(max_delay, base_delay * (2 ** (attempt - 1)))
                    # Full jitter (AWS recommendation) — spreads retries
                    # across a thundering herd of resuming DB connections.
                    sleep_seconds = random.uniform(0, cap)
                    log_event(
                        "WARN",
                        "data_api_retry",
                        error_code=code,
                        error_type=exc.__class__.__name__,
                        attempt=attempt,
                        sleep_seconds=round(sleep_seconds, 3),
                    )
                    time.sleep(sleep_seconds)

        return wrapper  # type: ignore[return-value]

    return decorator
