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
        super().__init__(
            status_code=400, error_code="validation_error", message=message
        )


class UpstreamAuthError(AppError):
    def __init__(self, message: str = "Beatport authentication failed") -> None:
        super().__init__(
            status_code=403, error_code="beatport_auth_failed", message=message
        )


class UpstreamUnavailableError(AppError):
    def __init__(self, message: str = "Beatport API unavailable") -> None:
        super().__init__(
            status_code=502, error_code="beatport_unavailable", message=message
        )


class StorageError(AppError):
    def __init__(self, message: str = "Failed to persist artifacts") -> None:
        super().__init__(status_code=500, error_code="storage_error", message=message)


class SpotifyAuthError(AppError):
    def __init__(self, message: str = "Spotify authentication failed") -> None:
        super().__init__(
            status_code=403, error_code="spotify_auth_failed", message=message
        )


class SpotifyUnavailableError(AppError):
    def __init__(self, message: str = "Spotify API unavailable") -> None:
        super().__init__(
            status_code=502, error_code="spotify_unavailable", message=message
        )


class VendorUnavailableError(AppError):
    def __init__(self, vendor: str, reason: str = "") -> None:
        super().__init__(
            status_code=502,
            error_code="vendor_unavailable",
            message=f"vendor {vendor} unavailable: {reason}",
        )
        self.vendor = vendor
        self.reason = reason


class VendorAuthError(AppError):
    def __init__(self, vendor: str) -> None:
        super().__init__(
            status_code=403,
            error_code="vendor_auth_failed",
            message=f"vendor {vendor} auth failed",
        )
        self.vendor = vendor


class VendorQuotaError(AppError):
    def __init__(self, vendor: str, retry_after: int | None = None) -> None:
        super().__init__(
            status_code=429,
            error_code="vendor_quota",
            message=f"vendor {vendor} quota exceeded",
        )
        self.vendor = vendor
        self.retry_after = retry_after


class MatchFailedError(Exception):
    """Worker-internal non-fatal: trigger review queue routing. Not an AppError."""

    error_code = "match_failed"

    def __init__(self, vendor: str, reason: str) -> None:
        super().__init__(f"match failed for {vendor}: {reason}")
        self.vendor = vendor
        self.reason = reason


class UserTokenMissingError(AppError):
    def __init__(self, user_id: str, vendor: str) -> None:
        super().__init__(
            status_code=400,
            error_code="user_token_missing",
            message=f"user {user_id} has no token for vendor {vendor}",
        )
        self.user_id = user_id
        self.vendor = vendor


class VendorDisabledError(AppError):
    """Raised when a registry lookup cannot be served. The .reason attribute
    discriminates: 'disabled' (env flag), 'unrouted' (no enricher for prompt),
    'not_implemented' (stub or missing role on bundle).
    """

    def __init__(self, vendor: str, reason: str = "disabled") -> None:
        super().__init__(
            status_code=400,
            error_code="vendor_disabled",
            message=f"vendor is disabled or not implemented: {vendor} (reason={reason})",
        )
        self.vendor = vendor
        self.reason = reason


class PremiumRequiredError(AppError):
    def __init__(
        self,
        *,
        upgrade_url: str = "https://www.spotify.com/premium/",
        message: str = "Spotify Premium required",
    ) -> None:
        super().__init__(
            status_code=403, error_code="premium_required", message=message
        )
        self.upgrade_url = upgrade_url


class CsrfStateMismatchError(AppError):
    def __init__(self, message: str = "OAuth state mismatch") -> None:
        super().__init__(
            status_code=400, error_code="csrf_state_mismatch", message=message
        )


class OAuthExchangeFailedError(AppError):
    def __init__(self, message: str = "OAuth code exchange failed") -> None:
        super().__init__(
            status_code=502, error_code="oauth_exchange_failed", message=message
        )


class SpotifyRevokedError(AppError):
    def __init__(
        self, message: str = "Spotify refresh token revoked, re-authentication required"
    ) -> None:
        super().__init__(
            status_code=401, error_code="spotify_revoked", message=message
        )


class RefreshInvalidError(AppError):
    def __init__(self, message: str = "Refresh token missing or invalid") -> None:
        super().__init__(
            status_code=401, error_code="refresh_invalid", message=message
        )


class RefreshReplayDetectedError(AppError):
    def __init__(
        self, message: str = "Refresh-token replay detected, session revoked"
    ) -> None:
        super().__init__(
            status_code=401,
            error_code="refresh_replay_detected",
            message=message,
        )


class AdminRequiredError(AppError):
    def __init__(self, message: str = "Admin privileges required") -> None:
        super().__init__(
            status_code=403, error_code="admin_required", message=message
        )


class CannotRevokeCurrentSessionError(AppError):
    def __init__(
        self, message: str = "Cannot revoke the current session — use logout"
    ) -> None:
        super().__init__(
            status_code=400,
            error_code="cannot_revoke_current",
            message=message,
        )
