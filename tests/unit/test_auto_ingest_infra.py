"""Terraform and deploy-workflow contracts for auto-ingest."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_lambda_reads_only_the_beatport_credentials() -> None:
    tf = (ROOT / "infra" / "auto_ingest.tf").read_text()
    assert 'handler          = "collector.auto_ingest_handler.lambda_handler"' in tf
    block = re.search(r'sid\s*=\s*"ReadBeatportCredentials"(.*?)\n  \}', tf, re.S).group(1)
    assert '"ssm:GetParameter"' in block
    assert "local.beatport_username_ssm" in block and "local.beatport_password_ssm" in block
    assert '"/clouder/beatport/username"' in tf and '"/clouder/beatport/password"' in tf
    assert "alias/aws/ssm" in tf


def test_deploy_skips_beatport_sync_without_secrets() -> None:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "deploy.yml").read_text())
    steps = [s for job in workflow["jobs"].values() for s in job["steps"]]
    step = next(s for s in steps if "Beatport" in s.get("name", ""))
    assert step["env"] == {
        "BP_USER": "${{ secrets.BEATPORT_USERNAME }}",
        "BP_PASS": "${{ secrets.BEATPORT_PASSWORD }}",
    }
    script = step["run"]
    assert re.search(r'if \[ -z "\$BP_USER" \] \|\| \[ -z "\$BP_PASS" \]; then\s.*exit 0', script, re.S)
    for name in ("/clouder/beatport/username", "/clouder/beatport/password"):
        assert f"--name {name}" in script
    # `--value=...`: a password starting with "-" must not be parsed as an option.
    assert '--value="$BP_USER"' in script and '--value="$BP_PASS"' in script
    assert script.count("--type SecureString") == 2


def _tf(name: str) -> str:
    return (ROOT / "infra" / name).read_text()


def _block(tf: str, header: str) -> str:
    """Text of the top-level block that starts with `header` (up to the next top-level `}`)."""
    start = tf.index(header)
    return tf[start : tf.index("\n}\n", start)]


def _statement(tf: str, sid: str) -> str:
    return re.search(rf'sid\s*=\s*"{sid}"(.*?)\n  \}}', tf, re.S).group(1)


def test_daily_planner_schedule_runs_at_00_05_utc() -> None:
    tf = _tf("auto_ingest.tf")
    group = _block(tf, 'resource "aws_scheduler_schedule_group" "auto_ingest"')
    assert 'name = "${local.name_prefix}-auto-ingest"' in group
    plan = _block(tf, 'resource "aws_scheduler_schedule" "auto_ingest_plan"')
    assert "group_name                   = aws_scheduler_schedule_group.auto_ingest.name" in plan
    assert 'schedule_expression          = "cron(5 0 * * ? *)"' in plan
    assert 'schedule_expression_timezone = "UTC"' in plan
    assert 'input    = jsonencode({ action = "plan" })' in plan
    assert "arn      = aws_lambda_function.auto_ingest.arn" in plan
    # The planner deletes `run-*` schedules in this group; its own name must not match.
    assert not re.search(r'\bname\s*=\s*"run-', plan)


def test_scheduler_role_may_only_invoke_auto_ingest() -> None:
    tf = _tf("auto_ingest.tf")
    trust = _block(tf, 'data "aws_iam_policy_document" "auto_ingest_scheduler_assume"')
    assert '"scheduler.amazonaws.com"' in trust and "aws:SourceAccount" in trust
    policy = _block(tf, 'data "aws_iam_policy_document" "auto_ingest_scheduler"')
    assert policy.count("statement {") == 1
    assert 'actions   = ["lambda:InvokeFunction"]' in policy
    assert "resources = [aws_lambda_function.auto_ingest.arn]" in policy


def test_auto_ingest_role_can_ingest_and_schedule() -> None:
    tf = _tf("auto_ingest.tf")
    data_api = _statement(tf, "AllowRdsDataApi")
    for action in ("ExecuteStatement", "BatchExecuteStatement", "BeginTransaction", "CommitTransaction"):
        assert f'"rds-data:{action}"' in data_api
    assert "aws_rds_cluster.aurora.arn" in data_api
    assert "master_user_secret" in _statement(tf, "AllowReadDatabaseSecret")
    raw = _statement(tf, "AllowWriteRawReleases")
    assert '"s3:PutObject"' in raw and '"${aws_s3_bucket.raw.arn}/${var.raw_prefix}/*"' in raw
    sqs = _statement(tf, "AllowEnqueueCanonicalization")
    assert '"sqs:SendMessage"' in sqs and "aws_sqs_queue.canonicalization.arn" in sqs
    schedules = _statement(tf, "AllowManageRunSchedules")
    for action in ("CreateSchedule", "DeleteSchedule", "GetSchedule"):
        assert f'"scheduler:{action}"' in schedules
    assert "schedule/${aws_scheduler_schedule_group.auto_ingest.name}/*" in schedules
    assert '"scheduler:ListSchedules"' in _statement(tf, "AllowListSchedules")
    pass_role = _statement(tf, "AllowPassSchedulerRole")
    assert '"iam:PassRole"' in pass_role and "aws_iam_role.auto_ingest_scheduler.arn" in pass_role


def test_auto_ingest_lambda_env_matches_the_api_ingest() -> None:
    fn = _block(_tf("auto_ingest.tf"), 'resource "aws_lambda_function" "auto_ingest"')
    for key, value in {
        "RAW_BUCKET_NAME": "aws_s3_bucket.raw.bucket",
        "RAW_PREFIX": "var.raw_prefix",
        "BEATPORT_API_BASE_URL": "var.beatport_api_base_url",
        "CANONICALIZATION_QUEUE_URL": "aws_sqs_queue.canonicalization.url",
        "AURORA_CLUSTER_ARN": "aws_rds_cluster.aurora.arn",
        "AURORA_DATABASE": "var.aurora_database_name",
        "VENDORS_ENABLED": '"beatport"',
        "AUTO_INGEST_SCHEDULE_GROUP": "aws_scheduler_schedule_group.auto_ingest.name",
        "AUTO_INGEST_SCHEDULER_ROLE_ARN": "aws_iam_role.auto_ingest_scheduler.arn",
    }.items():
        assert re.search(rf"{key}\s*=\s*{re.escape(value)}", fn), key
    assert "CANONICALIZATION_ENABLED" in fn and "AURORA_SECRET_ARN" in fn


def test_api_lambda_can_start_auto_ingest() -> None:
    assert re.search(
        r"AUTO_INGEST_FUNCTION_NAME\s*=\s*local\.auto_ingest_lambda_name",
        _block(_tf("lambda.tf"), 'resource "aws_lambda_function" "collector"'),
    )
    role = _block(_tf("lambda_roles.tf"), 'module "role_collector"')
    invoke = next(line for line in role.splitlines() if '"InvokeAutoIngest"' in line)
    assert '"lambda:InvokeFunction"' in invoke and "aws_lambda_function.auto_ingest.arn" in invoke


def test_failed_runs_raise_an_alarm() -> None:
    tf = _tf("auto_ingest.tf")
    metric = _block(tf, 'resource "aws_cloudwatch_log_metric_filter" "auto_ingest_run_failed"')
    assert "aws_cloudwatch_log_group.auto_ingest.name" in metric
    assert '{ $.message = \\"auto_ingest_run_failed\\" }' in metric
    assert 'name      = "AutoIngestRunFailed"' in metric
    alarm = _block(tf, 'resource "aws_cloudwatch_metric_alarm" "auto_ingest_failed"')
    assert 'alarm_name          = "${local.name_prefix}-auto-ingest-failed"' in alarm
    assert 'metric_name         = "AutoIngestRunFailed"' in alarm
    assert "threshold           = 1" in alarm and "period              = 86400" in alarm


def test_deploy_can_be_started_by_hand() -> None:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "deploy.yml").read_text())
    triggers = workflow[True]  # YAML 1.1 reads the `on:` key as boolean True
    assert "workflow_dispatch" in triggers and triggers["push"]["branches"] == ["main"]


def test_auto_ingest_crashes_and_timeouts_raise_the_errors_alarm() -> None:
    # A crash in `plan` or a 900 s timeout writes no `auto_ingest_run_failed` event.
    workers = _block(_tf("alarms.tf"), "locals {")
    assert re.search(r"auto_ingest\s*=\s*aws_lambda_function\.auto_ingest\.function_name", workers)


def test_a_manual_deploy_only_ships_main() -> None:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "deploy.yml").read_text())
    assert workflow["jobs"]["deploy"]["if"] == "github.ref == 'refs/heads/main'"


def test_client_id_is_set_from_a_github_secret() -> None:
    # Beatport can rotate its public client id; a secret + manual deploy fixes it without code.
    fn = _block(_tf("auto_ingest.tf"), 'resource "aws_lambda_function" "auto_ingest"')
    assert re.search(r"BEATPORT_CLIENT_ID\s*=\s*var\.beatport_client_id", fn)
    variable = _block(_tf("variables.tf"), 'variable "beatport_client_id"')
    assert 'default     = ""' in variable  # unset secret: deploy passes, the login reports client_id
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "deploy.yml").read_text())
    apply = next(s for s in workflow["jobs"]["deploy"]["steps"] if s.get("name") == "Terraform apply")
    assert apply["env"]["TF_VAR_beatport_client_id"] == "${{ secrets.BEATPORT_CLIENT_ID }}"
