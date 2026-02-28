"""Application-level errors for the collector Lambda."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AppError(Exception):
    """Base typed error used to map to API responses."""

    status_code: int
    error_code: str
    message: str

    def __str__(self) -> str:  # pragma: no cover - inherited behavior is trivial
        return f"{self.error_code}: {self.message}"


class ValidationError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(status_code=400, error_code="validation_error", message=message)


class UpstreamAuthError(AppError):
    def __init__(self, message: str = "Beatport authentication failed") -> None:
        super().__init__(status_code=403, error_code="beatport_auth_failed", message=message)


class UpstreamUnavailableError(AppError):
    def __init__(self, message: str = "Beatport API unavailable") -> None:
        super().__init__(status_code=502, error_code="beatport_unavailable", message=message)


class StorageError(AppError):
    def __init__(self, message: str = "Failed to persist artifacts") -> None:
        super().__init__(status_code=500, error_code="storage_error", message=message)
