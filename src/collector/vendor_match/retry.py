"""Full-jitter retry decorator for transient vendor failures."""

from __future__ import annotations

import functools
import random
import time
from typing import Any, Callable, TypeVar

from ..errors import VendorQuotaError, VendorUnavailableError

F = TypeVar("F", bound=Callable[..., Any])

_TRANSIENT: tuple[type[Exception], ...] = (VendorUnavailableError, VendorQuotaError)


def retry_vendor(
    max_retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
) -> Callable[[F], F]:
    """Retry on VendorUnavailableError / VendorQuotaError with full jitter.

    VendorQuotaError.retry_after dominates jitter when set. Non-transient
    errors (VendorAuthError, VendorDisabledError, etc.) propagate immediately.
    """

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Exception | None = None
            for attempt in range(max_retries):
                try:
                    return fn(*args, **kwargs)
                except _TRANSIENT as exc:
                    last_exc = exc
                    if attempt == max_retries - 1:
                        break
                    delay = random.uniform(
                        0.0, min(max_delay, base_delay * (2**attempt))
                    )
                    if isinstance(exc, VendorQuotaError) and exc.retry_after:
                        delay = max(delay, float(exc.retry_after))
                    time.sleep(delay)
            assert last_exc is not None
            raise last_exc

        return wrapper  # type: ignore[return-value]

    return decorator
