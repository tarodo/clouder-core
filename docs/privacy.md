# Privacy: personal data and user deletion

CLOUDER stores only what a signed-in DJ needs to curate and publish tracks. Everything runs in one AWS account in **us-east-1**. This page lists where personal data lives, why, for how long, and how to delete one user from all of it.

## What is stored, where, and why

| Store | Personal data | Purpose | Retention |
|---|---|---|---|
| Aurora `users` | Spotify user id, display name, email, admin flag | Sign-in (Spotify OAuth) and the account itself | Until the user is deleted |
| Aurora `user_sessions` | Refresh-token hash, IP address, user agent | Refresh-token rotation and replay detection (ADR-0015) | Until the user is deleted; a session expires after 7 days |
| Aurora `user_vendor_tokens` | Spotify / YouTube OAuth tokens, encrypted with a KMS data key (envelope) | Importing and publishing playlists on the user's behalf | Until the user disconnects or is deleted |
| Aurora overlay: `categories`, `category_tracks`, `triage_*`, `playlists`, `playlist_tracks`, `user_tags`, `track_tags`, `user_imported_tracks`, `clouder_user_{artist,label,style}_prefs` | The user's curation: what they kept, tagged, liked, published | The product | Until the user is deleted |
| Aurora audit columns `*_by_user_id` (enrichment runs, auto-enrich and auto-ingest settings) | Which admin started a run or changed a setting | Operations | Set to NULL on deletion; the run or setting stays |
| Aurora automated backups | All of the above | Point-in-time recovery | 7 days |
| S3 raw bucket `covers/<user_id>/` | Playlist cover images the user uploaded | Playlist covers | Until the user is deleted (every version is removed) |
| S3 feature bucket `models/<user_id>/` | The user's triage-suggestion models (`.npz`), trained on their keep / discard decisions per style | Suggested buttons in triage | Until the user is deleted (every version is removed); older models of the same user stay until then |
| S3 lake `bronze/events/` (Firehose, Parquet) | Pseudonymous telemetry: user id, session id, event, track, timestamps — no name, email or IP | Listening analytics on the Home cards | 400 days (lifecycle rule; infrequent access after 90) |
| S3 lake `bronze/_errors/` | Records Firehose could not convert (may include the same pseudonymous fields) | Debugging a delivery | 30 days |
| S3 lake `bronze/catalog_export/` | Nightly snapshot that includes `categories` and `category_tracks` | Lakehouse dimensions | 14 days (lifecycle rule) |
| Iceberg `clouder_silver.events`, `clouder_gold.fct_play` | Same pseudonymous telemetry, deduplicated / turned into plays | Analytics history | 400 days back from the newest partition (dbt post-hook), and until the user is deleted; deleted rows stay in Iceberg snapshots until the nightly `VACUUM` expires them (about 5 days) |
| CloudWatch Logs | `user_id` in structured Lambda logs; client IP in API Gateway access logs | Debugging and incident response | 30 days (14 for the analytics API) |
| SSM Parameter Store | App secrets only (OAuth client credentials, signing keys) | Configuration | — no per-user data |
| Browser `localStorage` | Last selected style and playback device id | UI convenience | Until the user clears it; no tokens are ever stored (see [frontend/auth.md](frontend/auth.md)) |

Public YouTube comments collected for tracks (`external_comments`) belong to third-party commenters, not to CLOUDER users, and are not affected by deleting a user.

## Deleting a user

`scripts/delete_user.py` removes a user from every store above that holds per-user rows. It runs from an operator machine with AWS credentials for the account. `--user-id` takes either spelling of the UUID; the script uses the stored one (32 hex digits, no dashes), as every store keys by it.

```bash
export AURORA_CLUSTER_ARN=... AURORA_SECRET_ARN=... RAW_BUCKET_NAME=...
PYTHONPATH=src .venv/bin/python scripts/delete_user.py --user-id <uuid> --dry-run
PYTHONPATH=src .venv/bin/python scripts/delete_user.py --user-id <uuid>
```

1. **Dry run.** Runs the real Aurora deletes inside a transaction and rolls it back, then prints the exact row counts per table. Every run starts with it.
2. **Confirmation.** The real run asks for the user id again (`--yes` skips the prompt).
3. **Aurora.** One transaction (`collector.user_deletion.delete_user`). The tables come from the catalog: every `*user_id` column marks rows the user owns, foreign keys lead to their children, children go before parents, and the `users` row goes last. Audit columns are set to NULL. A new user-owned table is picked up without code changes, and `tests/db/test_user_deletion_pg.py` fails until its seed covers it.
4. **Covers and models.** Every version and delete marker under `covers/<user_id>/` in the raw bucket and under `models/<user_id>/` in the feature bucket (`--features-bucket`, default `clouder-prod-audio-features`). The audio profiles under `features/` are per video, not per user, and stay.
5. **Lake.** A tombstone `{"user_id", "deleted_at"}` is written to `s3://<lake>/governance/deleted_users/` (Glue table `clouder_analytics.deleted_users`, no expiry). Then Athena deletes the user's rows from `clouder_silver.events` and `clouder_gold.fct_play`. `stg_events` drops tombstoned users, so neither the nightly build nor a full refresh can bring the rows back; the dbt test `assert_deleted_users_absent` checks this on every build.

Each step can be run again: after a partial failure, run the script again.

### What is left after deletion, and for how long

- **Aurora backups** keep the user for up to 7 days, until they age out.
- **Bronze telemetry** keeps the raw, pseudonymous events for up to 400 days. Once the `users` row is gone, nothing links the user id to a person, and every table built from bronze excludes it (the tombstone).
- **Catalog snapshots** keep the user's categories for up to 14 days.
- **CloudWatch Logs** expire after 30 days.
- **Signed-in sessions.** An access token already issued stays valid for up to 30 minutes. The refresh token stops working at once, because its session row is gone.

A user who signs in with Spotify again gets a new, empty account.

## Exporting a user's data (access and portability)

`scripts/export_user.py` writes one JSON file with what CLOUDER holds about a user in its databases: their rows in every Aurora table the deletion walks (the same catalog-derived graph, children included, read from one snapshot), the titles, artists and names of the tracks, labels and styles those rows point at, audit references to them, their playlist cover keys and their telemetry from `clouder_silver.events`. Credential columns (encrypted OAuth tokens, refresh-token hashes) are redacted. The file is created with mode 0600; send it to the user over a private channel and delete it afterwards.

```bash
PYTHONPATH=src .venv/bin/python scripts/export_user.py --user-id <uuid> --out export-<uuid>.json
```

Not in the file: the cover images themselves (fetch them by key), telemetry from the last day that is still only in bronze (silver is built nightly), and CloudWatch logs (30 days).

## Legal basis and data-subject rights

CLOUDER is run by one person for a closed group of DJs who asked to use it.

| Purpose | Data | Basis (GDPR Art. 6(1)) |
|---|---|---|
| Account and sign-in | `users`, `user_sessions` | (b) needed to provide the service the user asked for |
| Curation and publishing | the overlay tables, `user_vendor_tokens`, covers | (b) |
| Account security: refresh-token rotation, replay detection, logs | sessions (IP, user agent), CloudWatch | (f) legitimate interest in keeping accounts safe |
| Listening analytics shown back to the user | pseudonymous telemetry, about 400 days (see the retention table) | (f) the cards are part of the product; no third party sees the data |

| Right | How |
|---|---|
| Access, portability (Art. 15, 20) | `scripts/export_user.py` — one JSON file |
| Erasure (Art. 17) | `scripts/delete_user.py` — Aurora, covers, triage models, lake (tombstone and Iceberg deletes) |
| Rectification (Art. 16) | Display name and email are copied from Spotify at every sign-in: the user corrects them in their Spotify account, and CLOUDER picks the change up at the next sign-in |
| Objection to analytics (Art. 21) | No in-app switch yet. On request the owner tombstones the user (`collector.user_deletion.purge_lake`): their events leave silver and gold and stay out of them. Collection itself does not stop — new events still reach bronze (kept 400 days) and the cards' 3-day live tail; stopping it needs a switch in the telemetry handler |

**Known gaps.** There is no privacy notice inside the app yet: users learn the above from the owner and from this page. All data is in AWS us-east-1; for users in the EU that is a transfer outside the EEA, which a public launch would need to address (an EU region or a documented transfer mechanism). There is no consent banner because the app sets no third-party cookies and runs no third-party tracking.
