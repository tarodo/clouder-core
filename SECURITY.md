# Security policy

## Reporting a vulnerability

Report it privately through GitHub: **Security → Report a vulnerability** on this
repository (private vulnerability reporting). Please do not open a public issue or pull
request for a security problem.

Include what is affected (URL, API route, file), how to reproduce it, and the impact you
expect. Sign-up is closed to a small group, so a proof of concept against a local run
(`make demo`, see the README) is the best evidence; do not access other users' data.

## What to expect

CLOUDER is maintained by one person, so response is best effort:

- acknowledgement within 5 days;
- an assessment, and a fix plan for confirmed issues, within 14 days;
- a fix for a critical issue (auth bypass, data of another user, leaked credentials)
  deployed as soon as it is ready — every merge to `main` deploys to production.

You will be credited in the security advisory or the pull request that fixes the issue,
unless you prefer otherwise.

## Scope

In scope: the code in this repository and the production deployment it describes —
the HTTP API, the web app and the AWS configuration in `infra/`.

Out of scope:

- third-party services CLOUDER calls (Beatport, Spotify, YouTube, AWS) — report to them;
- denial-of-service and load testing, spam, social engineering;
- reports from automated scanners without a demonstrated impact;
- missing hardening that is already listed as a known gap in
  [`docs/security.md`](docs/security.md).

## Supported versions

Only the current `main` branch, which is what runs in production. Releases are milestones
of that branch, not separately maintained versions.

## How CLOUDER is secured

The threat model, IAM boundaries, secret handling and known gaps are in
[`docs/security.md`](docs/security.md).
