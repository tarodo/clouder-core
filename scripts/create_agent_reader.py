"""Give a coding agent read-only access to production through the RDS Data API.

Run as the master user before migration 20261021_41 reaches production (the
migrator owns the tables but cannot create roles), and again to rotate:

    PYTHONPATH=src .venv/bin/python scripts/create_agent_reader.py

It creates the role, makes its transactions read-only with a statement
timeout, sets a fresh random password and stores {username, password} in
Secrets Manager under SECRET_NAME. The migration then grants SELECT (token
tables, sessions and users.email closed). The password goes to the database as
a SCRAM verifier, so the plaintext never reaches it or its logs; it is never
printed. The output is the secret ARN for `aws rds-data ... --secret-arn`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets

ROLE = "clouder_agent_ro"
SECRET_NAME = "clouder/agent/aurora-readonly"


def scram_verifier(password: str, *, iterations: int = 4096) -> str:
    """What Postgres stores for SCRAM-SHA-256; ALTER ROLE accepts it as is."""
    salt = os.urandom(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    stored_key = hashlib.sha256(hmac.digest(salted, b"Client Key", "sha256")).digest()
    server_key = hmac.digest(salted, b"Server Key", "sha256")

    def b64(b: bytes) -> str:
        return base64.b64encode(b).decode()

    return f"SCRAM-SHA-256${iterations}:{b64(salt)}${b64(stored_key)}:{b64(server_key)}"


def password_sql(password: str) -> str:
    # ponytail: ':' written as \x3a so neither the Data API nor the test adapter
    # reads ":<base64>" as a named parameter.
    literal = scram_verifier(password).replace(":", "\\x3a")
    return f"ALTER ROLE {ROLE} PASSWORD E'{literal}'"


def role_sql() -> list[str]:
    return [
        f"""DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
                CREATE ROLE {ROLE} LOGIN;
            END IF;
        END $$""",
        # The migration's grants are the guard; these are the seatbelt.
        f"ALTER ROLE {ROLE} SET default_transaction_read_only = on",
        f"ALTER ROLE {ROLE} SET statement_timeout = '30s'",
    ]


def main() -> None:
    import boto3

    from collector.data_api import create_default_data_api_client

    cluster = boto3.client("rds").describe_db_clusters(
        DBClusterIdentifier=os.environ.get("CLUSTER", "clouder-prod-aurora")
    )["DBClusters"][0]
    client = create_default_data_api_client(
        resource_arn=cluster["DBClusterArn"],
        secret_arn=cluster["MasterUserSecret"]["SecretArn"],
        database=cluster["DatabaseName"],
    )
    for sql in role_sql():
        client.execute(sql)
    password = secrets.token_urlsafe(32)
    value = json.dumps({"username": ROLE, "password": password})
    sm = boto3.client("secretsmanager")
    try:
        arn = sm.create_secret(
            Name=SECRET_NAME,
            SecretString=value,
            Description=f"Read-only Aurora login for a coding agent ({ROLE})",
        )["ARN"]
    except sm.exceptions.ResourceExistsException:
        arn = sm.put_secret_value(SecretId=SECRET_NAME, SecretString=value)["ARN"]
    # Secret first: if this fails, a rerun stores a new password and sets it.
    client.execute(password_sql(password))
    print(arn)


if __name__ == "__main__":
    main()
