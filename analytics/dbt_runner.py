"""dbt-runner Lambda handler. Runs ONE dbt command per invocation via the in-process
dbtRunner. The command is split on whitespace so MULTI-TOKEN commands like
'source freshness' (a distinct dbt subcommand, not covered by build/test) actually
execute as ['source','freshness',...]. The Step Functions DAG invokes this with
command='run', then 'source freshness', then 'test'.
"""
from __future__ import annotations

import os
from typing import Any, Callable


def run_dbt(command: str, project_dir: str, profiles_dir: str,
            invoke: Callable[[list[str]], Any]) -> dict[str, Any]:
    args = command.split() + [
        "--project-dir", project_dir,
        "--profiles-dir", profiles_dir,
    ]
    result = invoke(args)
    if not result.success:
        raise RuntimeError(f"dbt {command!r} failed")
    return {"command": command, "args": args, "success": True}


def _dbt_invoke(args: list[str]) -> Any:
    from dbt.cli.main import dbtRunner  # heavy; imported only in the real runtime

    return dbtRunner().invoke(args)


def lambda_handler(event: Any, context: Any) -> dict[str, Any]:
    command = (event or {}).get("command", "build")
    return run_dbt(
        command,
        os.environ.get("DBT_PROJECT_DIR", "/var/task/dbt"),
        os.environ.get("DBT_PROFILES_DIR", "/var/task/dbt"),
        _dbt_invoke,
    )
