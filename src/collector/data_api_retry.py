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

F = TypeVar("F", bound=Callable[..., Any])


def retry_data_api(
    max_attempts: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
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
                    if code not in TRANSIENT_ERROR_CODES or attempt >= max_attempts:
                        raise
                    delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
                    jitter = delay * 0.1 * random.random()
                    log_event(
                        "WARN",
                        "data_api_retry",
                        error_code=code,
                        error_type=exc.__class__.__name__,
                    )
                    time.sleep(delay + jitter)

        return wrapper  # type: ignore[return-value]

    return decorator
