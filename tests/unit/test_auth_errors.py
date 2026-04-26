from __future__ import annotations

from collector.errors import (
    AdminRequiredError,
    CannotRevokeCurrentSessionError,
    CsrfStateMismatchError,
    OAuthExchangeFailedError,
    PremiumRequiredError,
    RefreshInvalidError,
    RefreshReplayDetectedError,
    SpotifyRevokedError,
)


def test_premium_required_error_shape() -> None:
    err = PremiumRequiredError(upgrade_url="https://www.spotify.com/premium/")
    assert err.status_code == 403
    assert err.error_code == "premium_required"
    assert err.upgrade_url == "https://www.spotify.com/premium/"


def test_csrf_state_mismatch_is_400() -> None:
    err = CsrfStateMismatchError()
    assert err.status_code == 400
    assert err.error_code == "csrf_state_mismatch"


def test_oauth_exchange_failed_is_502() -> None:
    err = OAuthExchangeFailedError("Spotify down")
    assert err.status_code == 502
    assert err.error_code == "oauth_exchange_failed"


def test_refresh_invalid_is_401() -> None:
    err = RefreshInvalidError()
    assert err.status_code == 401
    assert err.error_code == "refresh_invalid"


def test_refresh_replay_detected_is_401() -> None:
    err = RefreshReplayDetectedError()
    assert err.status_code == 401
    assert err.error_code == "refresh_replay_detected"


def test_spotify_revoked_is_401() -> None:
    err = SpotifyRevokedError()
    assert err.status_code == 401
    assert err.error_code == "spotify_revoked"


def test_admin_required_is_403() -> None:
    err = AdminRequiredError()
    assert err.status_code == 403
    assert err.error_code == "admin_required"


def test_cannot_revoke_current_is_400() -> None:
    err = CannotRevokeCurrentSessionError()
    assert err.status_code == 400
    assert err.error_code == "cannot_revoke_current"
