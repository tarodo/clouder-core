# Triage block classification: defaults, toggles, and the FAV bucket

**Date:** 2026-05-27
**Status:** Approved (pending spec review)
**Area:** backend (`src/collector/curation/`), frontend (`frontend/src/features/triage/`), schema migration

## Problem

The "New triage block" modal under-serves the user during block creation:

- The disliked-label rule (`include_disliked_labels`) defaults to **off** and only takes
  effect if the user opens Advanced and ticks it. The user wants disliked-label tracks
  routed to NOT by default.
- The "compilations go to NOT" rule is **hardcoded** in the classification `CASE`. There is
  no way to turn it off.
- There is no equivalent rule for disliked **artists** — only labels are handled.
- Tracks from labels/artists the user **liked** are scattered across NEW/OLD with everything
  else, so the most promising material is not surfaced.

## Goal

At block creation, classify tracks so that liked material surfaces, disliked material is
demoted, and the user controls each rule from the modal. All rules default ON.

## Scope

In scope: the create-block classification path, the four create-time toggles, a new
technical bucket `FAV`, and the modal UI. Out of scope: the `NOT EXISTS` filter that
excludes tracks already sitting in a user category (unchanged), finalize/move/transfer
behavior (unchanged), and any retroactive reclassification of existing blocks.

## Classification

Classification happens once, at create time, as a single `INSERT … SELECT` with a `CASE`
expression. The ordering is **first match wins**:

```
1. liked label   OR liked artist      -> FAV            [gated by include_favorites]
2. disliked label OR disliked artist  -> NOT            [gated by include_disliked_labels / include_disliked_artists]
3. spotify_release_date IS NULL       -> UNCLASSIFIED
4. spotify_release_date < old_cutoff  -> OLD
5. release_type = 'compilation'       -> NOT            [gated by compilations_to_not]
6. else                               -> NEW
```

**Likes win over dislikes (deliberate).** Because branches 1 and 2 each group label and
artist together, "any like" beats "any dislike". Consequences, all intended:

- liked artist on a disliked label → FAV
- disliked artist on a liked label → FAV
- a track that is both liked and disliked (e.g. liked label + disliked artist) → FAV

The `FAV` branch is evaluated before date/age branches, so a liked-but-old track (or one
with no Spotify date, or a compilation) still goes to FAV.

### Toggle → branch mapping

| Toggle | Column | Default | Effect when ON |
|---|---|---|---|
| Send disliked-label tracks to NOT | `include_disliked_labels` (exists, default flips) | TRUE | adds disliked-label subquery to branch 2 |
| Send disliked-artist tracks to NOT | `include_disliked_artists` (new) | TRUE | adds disliked-artist subquery to branch 2 |
| Send compilation tracks to NOT | `compilations_to_not` (new) | TRUE | emits branch 5 |
| Collect liked label/artist into FAV | `include_favorites` (new) | TRUE | emits branch 1 |

When a toggle is OFF its subquery/branch is **not emitted** and its parameters are **not
bound** — mirroring the existing `disliked_when` pattern, which avoids binding no-op
subqueries. Concretely:

- Branch 1 is emitted only if `include_favorites`. Bind `:fav_bucket_id` only then.
- Branch 2 is emitted only if `include_disliked_labels OR include_disliked_artists`; the
  subqueries inside it are OR'd and each is included only if its toggle is on.
- Branch 5 is emitted only if `compilations_to_not`.
- `:not_bucket_id` is bound only if branch 2 or branch 5 is emitted (otherwise NOT is never
  referenced in the `CASE`). `:new/:old/:unclassified_bucket_id` are always bound.

### Subqueries

Disliked label (existing, unchanged shape) and the three new ones share structure. All
filter by `:user_id` and use the existing `idx_user_label_prefs_user_status` /
`idx_user_artist_prefs_user_status` indexes.

```sql
-- liked label   (status='liked'),    disliked label   (status='disliked')
EXISTS (SELECT 1 FROM clouder_albums a
        JOIN clouder_user_label_prefs ulp ON ulp.label_id = a.label_id
        WHERE a.id = t.album_id AND ulp.user_id = :user_id AND ulp.status = :s)

-- liked artist  (status='liked'),    disliked artist  (status='disliked')
EXISTS (SELECT 1 FROM clouder_track_artists cta
        JOIN clouder_user_artist_prefs uap ON uap.artist_id = cta.artist_id
        WHERE cta.track_id = t.id AND uap.user_id = :user_id AND uap.status = :s)
```

Branch 1 (FAV) = `(liked-label EXISTS) OR (liked-artist EXISTS)`.
Branch 2 (NOT) = OR of whichever disliked subqueries are enabled.

### Pure mirror

`triage_service.classify_bucket_type` is the pure mirror used by unit tests. Updated
signature and body:

```python
def classify_bucket_type(
    *,
    spotify_release_date: date | None,
    release_type: str | None,
    old_cutoff: date,
    is_favorite: bool = False,
    is_disliked: bool = False,
    compilation_to_not: bool = True,
) -> str:
    if is_favorite:
        return BUCKET_TYPE_FAV
    if is_disliked:
        return BUCKET_TYPE_NOT
    if spotify_release_date is None:
        return BUCKET_TYPE_UNCLASSIFIED
    if spotify_release_date < old_cutoff:
        return BUCKET_TYPE_OLD
    if release_type == "compilation" and compilation_to_not:
        return BUCKET_TYPE_NOT
    return BUCKET_TYPE_NEW
```

`is_favorite` / `is_disliked` are already-resolved booleans (the caller combines toggle
state with preference rows), keeping the helper pure.

## The FAV bucket

`FAV` is a **technical** bucket, like NEW/OLD/NOT. It is created automatically at
block-create time and is **not promoted** to a category at finalize (only STAGING buckets
promote). The user manually moves tracks out of FAV into real categories during triage.

Changes:

- `triage_service.py`: add `BUCKET_TYPE_FAV = "FAV"`; add it to `TECHNICAL_BUCKET_TYPES`
  (so the create-block loop inserts it) and to `TECHNICAL_BUCKET_DISPLAY_ORDER`.
- Display order: **FAV first** → `FAV, NEW, OLD, NOT, UNCLASSIFIED, DISCARD`. Update the
  `CASE tbk.bucket_type` ordinals in `_fetch_block_detail` accordingly (FAV=0, NEW=1, …,
  STAGING=6).
- `bucketLabels.ts`: add `'FAV'` to `TechnicalBucketType` and `TECHNICAL_TYPES`. The badge
  renders the literal `FAV` in the mono font with no further change.

The existing `uq_triage_buckets_block_type_tech` unique index (`WHERE bucket_type <>
'STAGING'`) already guarantees exactly one FAV per block; the staging/category CHECK
(`(bucket_type = 'STAGING') = (category_id IS NOT NULL)`) is satisfied because FAV has a
NULL `category_id`.

## Schema migration

New revision `20260527_27_triage_classification_flags_fav` (down_revision
`20260527_26`):

1. Add three columns to `triage_blocks`, NOT NULL with server defaults reflecting
   historical behaviour of pre-existing rows:
   - `include_disliked_artists BOOLEAN NOT NULL DEFAULT FALSE` (did not exist before)
   - `compilations_to_not BOOLEAN NOT NULL DEFAULT TRUE` (matches old hardcoded rule)
   - `include_favorites BOOLEAN NOT NULL DEFAULT FALSE` (did not exist before)

   New blocks always send explicit values from the API, so the server defaults only affect
   already-finalized rows (where the flags are display-only). `include_disliked_labels`
   keeps its existing `server_default=FALSE` column; only the application-layer default
   changes.

2. Replace the `ck_triage_buckets_type` CHECK constraint to include `'FAV'`:
   drop `ck_triage_buckets_type`, then add it back with
   `bucket_type IN ('NEW','OLD','NOT','DISCARD','UNCLASSIFIED','STAGING','FAV')`.

`downgrade()` reverses both (re-add old CHECK, drop the three columns). Mirror the column +
constraint changes in `db_models.py` (the three new `mapped_column`s and the updated CHECK
string).

## API

`schemas.CreateTriageBlockIn` gains three fields, all `bool` defaulting to `True`:
`include_disliked_artists`, `compilations_to_not`, `include_favorites`. (`include_disliked_labels`
default flips from `False` to `True`.)

- `triage_repository.create_block` gains the three matching keyword params (default `True`),
  persists all four flags in the INSERT, and threads them into the dynamic `CASE`.
- `TriageBlockRow` dataclass gains the three fields; `_fetch_block_detail` selects and
  populates them.
- `curation_handler._create_triage_block` passes the three new schema fields through;
  `_serialize_triage_block` adds them to the response body.
- `scripts/generate_openapi.py`: add the three booleans to the `CreateTriageBlockIn` request
  schema and to the block response schema; regenerate `docs/api/openapi.yaml`. The frontend
  CI diff-check then requires regenerating `frontend/src/api/schema.d.ts`.

## Frontend

- `triageSchemas.ts`: `includeDislikedLabels` default → `true`; add
  `includeDislikedArtists`, `compilationsToNot`, `includeFavorites`, all
  `z.boolean().default(true)`.
- `CreateTriageBlockDialog.tsx`: set all four in `initialValues` to `true`; render three new
  `Switch`es inside the Advanced `Collapse`. Order in Advanced:
  OLD depth → disliked-label → disliked-artist → compilation → FAV. Pass all four to
  `create.mutateAsync`.
- `useCreateTriageBlock.ts`: extend `CreateTriageBlockInput` with the three new optional
  booleans.
- `i18n/en.json`: add label + description strings for the three new toggles under
  `triage.form.*`, and an empty-state body for the FAV bucket under
  `triage.bucket.empty.*` (e.g. `no_tracks_body_fav` — "Tracks from labels and artists you
  liked land here. Move them into a category.").

## Testing

- Unit `test_triage_service`: extend `classify_bucket_type` cases — FAV beats dislike, FAV
  beats old/null-date/compilation; `compilation_to_not=False` sends compilations to NEW;
  dislike still beats date when no like present.
- Unit `test_triage_schemas`: new defaults (`True`) and that the three new booleans parse.
- Unit `test_triage_repository`: create_block builds the expected `CASE`/params per toggle
  combination (favorites off → no FAV branch/param; both dislike toggles off + compilations
  off → NOT not referenced; FAV bucket row created among technical buckets).
- Unit `test_curation_handler_triage`: handler forwards the three fields and serializes them.
- Integration `test_triage_handler`: end-to-end create with liked/disliked label + artist
  fixtures lands tracks in FAV/NOT as specified, and FAV appears first in the bucket order.
- Frontend `CreateTriageBlockDialog.test` / `useCreateTriageBlock.test`: defaults are on
  without opening Advanced; toggles submit the right payload.
- Frontend `bucketLabels.test`: `FAV` is recognised as technical and labelled `FAV`.

## Decisions

- **Persist flags as columns** (not create-time-only) — symmetry with the existing
  `include_disliked_labels` column; the migration is mandatory anyway for the FAV CHECK.
- **FAV first** in display order — it is the highest-value material; "start here".
- **Likes beat dislikes** via a plain swap of branches 1↔2 (no finer label-vs-artist
  precedence).
