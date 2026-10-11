"""AWS SSM Parameter Store fetch helpers.

Service-level API keys and OAuth client creds live as SSM SecureString
parameters. The Standard tier is free (up to 10 000 parameters, 4 KB each,
KMS-encrypted via the AWS-managed key). `_fetch_ssm_parameter` caches for the
container's life; the JWT signing key uses `fetch_ssm_parameter` with its own
short TTL so a rotation needs no deploy (collector.auth.auth_settings).
"""

from __future__ import annotations

import functools


def _ssm_client():
    import boto3

    return boto3.client("ssm")


def fetch_ssm_parameter(name: str) -> str:
    response = _ssm_client().get_parameter(Name=name, WithDecryption=True)
    parameter = response.get("Parameter")
    if not isinstance(parameter, dict):
        raise RuntimeError(f"ssm response malformed, missing Parameter field (name={name})")
    value = parameter.get("Value")
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"ssm parameter is empty or not a string (name={name})")
    return value


@functools.lru_cache(maxsize=64)
def _fetch_ssm_parameter(name: str) -> str:
    return fetch_ssm_parameter(name)


def reset_cache() -> None:
    if hasattr(_fetch_ssm_parameter, "cache_clear"):
        _fetch_ssm_parameter.cache_clear()
