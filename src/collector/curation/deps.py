"""Repository and vendor-client factories for the curation routes.

Route modules call these through the module (`deps.X()`), so tests patch
`collector.curation.deps`.
"""

from __future__ import annotations

from typing import Any

from .categories_repository import (
    create_default_categories_repository,
)
from .playlists_repository import (
    create_default_playlists_repository,
)
from .tags_repository import (
    create_default_tags_repository,
)
from .triage_repository import (
    create_default_triage_repository,
)


# Each `_ROUTE_TABLE` entry names its factory explicitly — there is no
# silent fallback.
def _categories_factory() -> Any:
    return create_default_categories_repository()


def _triage_factory() -> Any:
    return create_default_triage_repository()


def _tags_factory() -> Any:
    return create_default_tags_repository()


def _comments_factory() -> Any:
    from collector.comments.repository import create_default_comments_repository

    return create_default_comments_repository()


def _playlists_factory() -> Any:
    return create_default_playlists_repository()


def _build_s3_storage():
    """Build an S3Storage for cover ops in the curation Lambda."""
    import boto3

    from collector.settings import get_api_settings
    from collector.storage import S3Storage

    settings = get_api_settings()
    return S3Storage(
        s3_client=boto3.client("s3"),
        bucket_name=settings.raw_bucket_name,
        raw_prefix=settings.raw_prefix,
    )


def _build_spotify_user_client(user_id: str, correlation_id: str):
    """Build a SpotifyUserClient with a freshly-resolved user access token.

    Lazy imports to keep cold-start lean. Token refresh + KMS decrypt go
    through SpotifyTokenResolver. Raises SpotifyNotAuthorizedError if the
    user has no token row or refresh fails — the handler's error envelope
    surfaces it as 412.
    """
    import boto3
    import requests as _requests

    from collector.auth.auth_settings import (
        get_auth_settings,
        resolve_oauth_client_credentials,
    )
    from collector.auth.kms_envelope import KmsEnvelope
    from collector.auth.spotify_oauth import SpotifyOAuthClient
    from collector.curation.spotify_token_resolver import SpotifyTokenResolver
    from collector.curation.spotify_user_client import SpotifyUserClient
    from collector.data_api import create_default_data_api_client
    from collector.settings import get_data_api_settings

    db = get_data_api_settings()
    auth = get_auth_settings()
    cid, csec = resolve_oauth_client_credentials()
    data_api = create_default_data_api_client(
        resource_arn=str(db.aurora_cluster_arn),
        secret_arn=str(db.aurora_secret_arn),
        database=db.aurora_database,
    )
    envelope = KmsEnvelope(
        kms_client=boto3.client("kms"),
        key_arn=auth.kms_user_tokens_key_arn,
    )
    oauth = SpotifyOAuthClient(
        client_id=cid, client_secret=csec,
        redirect_uri=auth.spotify_oauth_redirect_uri,
    )
    resolver = SpotifyTokenResolver(
        data_api=data_api, envelope=envelope, oauth_client=oauth,
    )
    token = resolver.resolve(user_id=user_id)
    return SpotifyUserClient(
        access_token=token.access_token,
        session=_requests.Session(),
    )


def _build_ytmusic_user_client(user_id: str, correlation_id: str):
    """Build a YouTube Data API v3 client bound to the user's OAuth token.

    Token refresh + KMS decrypt go through YtmusicTokenResolver. Raises
    YtmusicNotAuthorizedError (-> 412) if the user has not connected YT Music.
    Publishing uses the official Data API (not ytmusicapi) because ytmusicapi's
    OAuth path is rejected by YouTube on writes (HTTP 400).
    """
    import boto3
    import requests as _requests

    from collector.auth.auth_settings import (
        get_auth_settings,
        resolve_ytmusic_oauth_credentials,
    )
    from collector.auth.kms_envelope import KmsEnvelope
    from collector.auth.ytmusic_oauth import YtmusicOAuthClient
    from collector.curation.youtube_data_api_client import YoutubeDataApiClient
    from collector.curation.ytmusic_token_resolver import YtmusicTokenResolver
    from collector.data_api import create_default_data_api_client
    from collector.settings import get_data_api_settings

    db = get_data_api_settings()
    auth = get_auth_settings()
    cid, csec = resolve_ytmusic_oauth_credentials()
    data_api = create_default_data_api_client(
        resource_arn=str(db.aurora_cluster_arn),
        secret_arn=str(db.aurora_secret_arn),
        database=db.aurora_database,
    )
    envelope = KmsEnvelope(
        kms_client=boto3.client("kms"),
        key_arn=auth.kms_user_tokens_key_arn,
    )
    oauth = YtmusicOAuthClient(client_id=cid, client_secret=csec)
    resolver = YtmusicTokenResolver(
        data_api=data_api, envelope=envelope, oauth_client=oauth,
    )
    token = resolver.resolve(user_id=user_id)
    return YoutubeDataApiClient(
        access_token=token.token_dict["access_token"],
        session=_requests.Session(),
        correlation_id=correlation_id,
    )
