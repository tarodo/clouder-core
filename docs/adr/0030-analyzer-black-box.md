# ADR-0030: The analyzer is a black box behind its contract
Status: Accepted
Date: 2026-10-30

## Context

clouder-analyzer (private repo, runs on the owner's PC) runs the audio models. clouder-core hands it
work over `/v1/analysis/*` and stores what it posts back
([track analysis spec](../superpowers/specs/2026-10-15-track-analysis-api-design.md)).

Earlier specs and comments here also described the worker's side: where its audio comes from, the
tools it uses, its cache and its pacing. That tied this repository's docs to choices that belong to
the worker and can change with no change here.

## Decision

- clouder-core knows the analyzer only through the `/v1/analysis/*` contract
  (`docs/api/openapi.yaml`). A claim hands out a track id, its matched `video_id` as an opaque
  reference, the catalog length and the analyzers the track lacks. Results, profiles and waveforms
  come back keyed by track and `video_id`.
- How the analyzer obtains the audio for a claimed track is not part of the contract. Code, comments
  and docs in this repository don't describe it: no source sites or tools, no fetch, cache, pacing
  or bot-check details. They say the analyzer analyzes a track, not how the audio got there.
- No audio crosses the contract, only results and derived vectors.
- The worker's own repository documents its side.

## Consequences

- Changing how the worker gets audio needs no code or doc change here.
- Core-side facts stay documented: which tracks a claim hands out (tracks with a matched video, the
  claim order), leases, and what is stored.
- `tests/unit/test_repo_hygiene.py` fails if tracked text names the download tool again.
- Older commits and pull requests keep the earlier wording; history is not rewritten.
