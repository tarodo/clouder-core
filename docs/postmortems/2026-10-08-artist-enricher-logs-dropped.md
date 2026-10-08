# 2026-10-08 — Artist enricher logs dropped under the shared role

## Summary

The artist enricher worker ran under the shared Lambda role from the day it shipped (2026-05-27). That role's CloudWatch Logs statement listed the allowed log groups one by one, and the artist enricher's group was never added. Lambda cannot create log streams without that permission, so every log line was dropped silently. It surfaced during the 2026-10-08 audit: 181 invocations in 30 days, 0 log streams.

## Impact

Four months of artist-enrichment runs left no logs: errors, vendor failures and timings were invisible. The function itself worked; SQS, Lambda metrics and the enrichment results were unaffected.

## Timeline

- 2026-05-27 — `b46f2e1` adds the artist enrichment queue, worker Lambda and log group; the Lambda uses the shared role, whose logs statement is not touched.
- 2026-06-27, 2026-10-07 — two later edits to the shared role; neither adds the group.
- 2026-10-08 — the audit finds 0 log streams; `d0b4e54` adds error alarms to all 18 Lambdas (the artist enricher had none); `c40ee2b` gives every Lambda its own least-privilege role, which fixes the logs; PR #269 merges.

## Root cause

A hand-kept list of log-group ARNs in a role shared by ten functions. Adding a function meant remembering to edit a different file; nothing failed when that was forgotten.

## Fix

`c40ee2b`: a small Terraform module (`infra/modules/lambda_role`) builds each function's role from its own log group plus only the queues, prefixes and parameters its code uses (`infra/lambda_roles.tf`). The log permission now comes with the function. `tests/unit/test_iam_per_function_infra.py` checks that no function uses a shared role and that each role writes only its own logs.

## Detection gap

- No errors alarm covered this function until `d0b4e54` (the alarm set listed functions by hand too).
- Missing logs raise no error and no metric; nothing checked "invoked but has no log streams".

## Follow-ups

- Done: per-function roles, and errors alarms generated for every function in `local.all_lambdas`.
- Open: a check that every function invoked in the last day has a log stream would catch a regression of any kind (role, log group name, retention).
