# 2026-10-07 — Backfill never converged on tracks merged by ISRC

## Summary

A backfill is supposed to converge: after one apply, a second dry run should report nothing to change. Instead every dry run reported about 26 changed tracks (album 26, publish date 22, mix name 3, length 2, BPM 1), and the set shifted between passes. The cause was 25 canonical tracks fed by two Beatport ids — an EP track and the same recording on a compilation, merged by an ISRC heuristic in March 2026. Each replay let whichever source came last overwrite the other.

## Impact

Album and publish date of 25 tracks flipped between two releases on every replay; the backfill could not prove itself idempotent. Nothing else was affected.

## Timeline (UTC+4)

- After the backfill merges (PR #252, 16:05) — first dry run (1 min 56 s): 26 tracks would change, 373 older observations skipped.
- After the 413 fix — another dry run (1 min 38 s): still about 26, different ones.
- 16:54 — `13f9e25` fixes staleness for merged tracks; 16:56 PR #254 merges.
- Apply (7 min 56 s): 153/153 runs, the 6 predicted tracks corrected. Final dry run (1 min 36 s): 0 changes, 399 older observations skipped.

## Root cause

The staleness check compared an observation only with the track's own source row. With two sources per canonical track, each source was "fresh" against itself, so both were applied in turn.

## Fix

`13f9e25` (`src/collector/repositories.py`): an observation is stale if any other source of the same canonical track has a newer observation from another run; within one run the larger Beatport id wins. The newest observation across all sources now wins whatever the replay order. Pinned by `test_merged_track_takes_the_newest_source_whatever_the_order` and `test_merged_track_within_one_run_is_stable` (`tests/db/test_canonicalize_merged_pg.py`).

## Detection gap

Synthetic test weeks give every canonical track exactly one source, and current code can no longer create merged tracks — only the retired March heuristic did. The state existed only in production data; the new test fabricates it.

## Follow-ups

- Done: [`docs/data/canonicalization.md`](../data/canonicalization.md) and [`docs/ops/backfill.md`](../ops/backfill.md) describe the rule.
- Open (listed in backfill.md): if the newest observation drops a value an older one had, an out-of-order replay can restore the old value; per-field observation times would close it.
- Open: the 25 merged tracks stay merged; no un-merge was done.
