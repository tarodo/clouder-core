# Decisions I would revisit

Choices that were right for a closed group of DJs and one developer, and what I would do differently with more users, more people or hindsight.

## Data and storage

- **The Data API for batch work.** It removed connection management from Lambda, but every limit it has bit once: invisible writes without a transaction id ([postmortem](../postmortems/2026-04-15-identity-lookup-outside-transaction.md)), the 4 MiB request limit ([postmortem](../postmortems/2026-10-07-data-api-413.md)), per-call latency that dominates large runs. For the canonicalization worker I would use RDS Proxy with a pooled driver and keep the Data API for the API Lambdas.
- **Scale to zero on the request path.** `min_acu = 0` makes the first request after a pause take up to 30 seconds (see the latency panel in the README). For paying users I would keep a small floor during active hours and pause only at night.
- **Merging recordings by ISRC heuristics into one canonical row.** Merged rows made replays non-convergent ([postmortem](../postmortems/2026-10-07-backfill-merged-tracks.md)). I would keep one canonical row per source recording and link duplicates in a separate table that reads can follow.
- **Append-only bronze telemetry without per-user partitioning.** Deleting a user cannot reach it without rewriting Parquet ([privacy.md](../privacy.md)). I would encrypt or partition events per user from the start so erasure is a key deletion, and set an explicit bronze retention.

## Infrastructure and delivery

- **One Terraform root for everything.** Data, compute and the frontend share one state, so the deploy needs a targeted apply to run migrations first ([postmortem](../postmortems/2026-09-20-deploy-before-migration.md)). Separate stacks (network and data, then compute) would make the order natural.
- **Production as the only environment.** CI is thorough, but nothing runs the deploy against a schema one revision behind before production does. A staging stack, or at least an ephemeral one per release, would have caught the 2026-09-20 incident.
- **Shared IAM role and hand-kept lists.** One role for ten functions dropped a function's logs for four months ([postmortem](../postmortems/2026-10-08-artist-enricher-logs-dropped.md)). Per-function roles from day one, and alarms, roles and log groups generated from one registry of functions.
- **A deploy role with AdministratorAccess.** Convenient while the Terraform surface moves weekly; a scoped role is the right default ([security.md](../security.md#known-gaps)).

## Application

- **HS256 with one shared signing key.** Rotation signs everyone out. Asymmetric keys with a key id would allow overlap during rotation and let other services verify tokens without the secret.
- **YouTube Music through Google's OAuth Testing mode.** Tokens expire every 7 days and only listed users can connect. Fine for a closed group; a verified app is required before opening sign-up.
- **Admin ingest on the synchronous API path.** It works because the slowest download takes 16 s against the 29 s gateway limit. It should return `202 Accepted` and hand the work to the auto-ingest Lambda ([scalability](../scalability.md#ingest)).
