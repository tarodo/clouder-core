# Operations

Deployment, runtime configuration, observability, and incident response.

- [Deploy](deploy.md) — CI/CD workflows, terraform apply order, migration Lambda invocation.
- [Environment variables](env-vars.md) — full runtime env table per Lambda.
- [Logs](logs.md) — structlog events, `aws logs tail`, enabling Aurora PostgreSQL logs.
- [Aurora](aurora.md) — Serverless v2 scaling, auto-pause, IAM auth quirks.
- [Runbook](runbook.md) — common incidents and their fixes.
- [Backfill](backfill.md) — replay the raw zone through the canonicalizer, dry run first.
- [Failure modes](failure-modes.md) — what breaks, the alarm that says so, recovery, RPO / RTO.

See also [`docs/architecture.md`](../architecture.md), [`docs/adr/`](../adr/).
