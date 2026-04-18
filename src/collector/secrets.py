"""AWS SSM Parameter Store fetch helpers.

Service-level API keys and OAuth client creds live as SSM SecureString
parameters. The Standard tier is free (up to 10 000 parameters, 4 KB each,
KMS-encrypted via the AWS-managed key). Fetches are cached per container
lifetime — rotating a parameter requires a Lambda recycle, same trade-off
as the previous Secrets Manager-based implementation.
"""

from __future__ import annotations

import functools


def _ssm_client():
    import boto3

    return boto3.client("ssm")


@functools.lru_cache(maxsize=64)
def _fetch_ssm_parameter(name: str) -> str:
    response = _ssm_client().get_parameter(Name=name, WithDecryption=True)
    parameter = response.get("Parameter")
    if not isinstance(parameter, dict):
        raise RuntimeError(
            f"ssm response malformed, missing Parameter field (name={name})"
        )
    value = parameter.get("Value")
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"ssm parameter is empty or not a string (name={name})")
    return value


def reset_cache() -> None:
    if hasattr(_fetch_ssm_parameter, "cache_clear"):
        _fetch_ssm_parameter.cache_clear()
