"""Write a fresh JWT signing key to SSM (creates the parameter on a new account).

Signs every user out: access and refresh tokens are JWTs signed with this key. The value
goes straight from the CSPRNG to SSM and is never printed. Old tokens stop working within
10 minutes: the auth Lambdas re-read the key every 5 (auth_settings.JWT_KEY_TTL_SECONDS) and
API Gateway caches authorizer answers for 5 more (var.auth_authorizer_cache_ttl_seconds).

    .venv/bin/python scripts/rotate_jwt_key.py [--name /clouder/auth/jwt_signing_key]
"""

from __future__ import annotations

import argparse
import secrets
from typing import Any

DEFAULT_NAME = "/clouder/auth/jwt_signing_key"
REGION = "us-east-1"  # where production runs; a default profile region would miss it


def main(argv: list[str] | None = None, ssm: Any = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--name", default=DEFAULT_NAME)
    args = parser.parse_args(argv)
    if ssm is None:
        import boto3

        ssm = boto3.client("ssm", region_name=REGION)
    response = ssm.put_parameter(
        Name=args.name,
        Value=secrets.token_urlsafe(48),  # 64 characters, as the Terraform-made key had
        Type="SecureString",
        Overwrite=True,
        Description="HS256 secret used by auth_handler and auth_authorizer",
    )
    print(f"{REGION} {args.name}: version {response['Version']}; sessions end within 10 minutes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
