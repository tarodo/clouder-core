# 2026-09-20 — API code shipped before its migration

## Summary

A feature made `GET /styles` personal: it joins and counts a new table, `clouder_user_style_prefs`, created by Alembic revision 32 in the same pull request. The deploy updated the API Lambda first and ran the migration afterwards, so for 2 minutes 40 seconds the new code queried a table that did not exist yet and `GET /styles` returned 500.

## Impact

`GET /styles` failed for 2 min 40 s (API Lambda updated at 15:45:58 UTC, migration finished at 15:48:38 UTC, from the deploy log). The route feeds the style picker on 13 screens. Request and user counts were not recorded.

## Timeline (UTC+4)

- 19:44 — PR #230 (user style selection, `dd0077f`) merges and the deploy starts: `terraform apply` (all Lambdas), then the migration step.
- During the deploy — 500s on `GET /styles` until the migration finishes.
- 21:03 — `2ba5ea2` reorders the deploy; 21:04 PR #231 merges.

## Root cause

The deploy ran one full `terraform apply`, which updated the API Lambda, before invoking the migration Lambda. Moving the migration step first does not work either: the migration Lambda ships from the same package and only gets the new revision through `apply`. The design note had warned that apply and migration were "two independent, unordered actions", but nothing enforced an order.

## Fix

A two-phase deploy (`.github/workflows/deploy.yml`):

1. `terraform apply -target=aws_lambda_function.db_migration` — only the migration Lambda gets the new code.
2. Invoke it with `upgrade head`; the step fails on a Lambda error or a non-`ok` status.
3. Full `terraform apply` — the API code ships against the migrated schema.

## Detection gap

CI tests code and SQL against a migrated test database; nothing exercised the deploy sequence against a schema one revision behind.

## Follow-ups

- Done (`b9dcf46`, 2026-10-08): the targeted apply had skipped each Lambda's inline IAM policy once roles became per-function; the role module's ARN output now depends on its policy, guarded by `test_role_arn_waits_for_its_policy`.
- Done (2026-10-08): `tests/unit/test_deploy_order.py` fails if the migration step stops sitting between the two applies, or if their `-var` lists drift apart.
- Open: migrations are not yet required to be expand-only (backward compatible with the code currently running); today the ordering alone protects the deploy.
