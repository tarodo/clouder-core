# Triage suggestions v1 (light audio profile, per-user heads) — design

Date: 2026-10-23. Status: draft for owner review.

## Intent

The owner triages ~400 new releases a week per style and keeps about 27 % of them. A lab study on 3 235 of his labelled DnB tracks
(`/Users/roman/Projects/HP/ai_detect/ideas/reports/recommendations.md`, `protocol.md`) showed that a small audio profile
predicts his decisions on artists the model has never seen:

| task (4 light blocks, artist-grouped CV) | result |
|---|---|
| keep / discard | ROC AUC 0.801; 12.2 keeps in the top 20 of 100 (random: 5.4) |
| category, 6 classes | balanced accuracy 0.686; the right one in the top 2: 0.907 |

v1 turns this into help during triage: while a track plays, the button the model suggests is lit brightly and its second guess
more palely. Models retrain on their own as the owner labels, so a new style (techno next) starts getting suggestions within its
first block.

## Goals

1. **The light profile for every downloaded track.** clouder-analyzer computes it when it downloads a track. The profile goes
   straight to S3; nothing accumulates on the PC.
2. **Re-read audio already on the PC with no re-download.** This covers the lab videos in `lab-data` (781 + 2 462 ablation, 105 dev) and the analyzer's
   own cache.
3. **One model per (user, style), trained in AWS.** It has a keep/discard head and a category head. It retrains when a block
   is finalized and after every 150 new labels.
4. **A stored prediction for every profiled track of the style, per user.** It holds keep / discard and the full category ranking.
5. **Lit buttons in both triage screens.** These are the bucket player panel and Curate. A line on the block also says which
   model is in use and how well it did.

## Non-goals

- **Similar tracks.** The owner wants it later and has not picked a place in the UI. The MuLan vector stays inside the S3
  profile; pgvector, a `track_embeddings` table and any similarity UI wait for that spec.
- **Heavy blocks.** MERT, MAEST, stems and allin1 move to the next iteration. Owner decision, 2026-10-23: they added nothing
  measurable on the same data.
- **Metadata and preference features in the keep head.** Label, artist and like / dislike are left out. *My call:* they lift
  grouped AUC by only 0.801 → 0.815 and need target-encoding tables at inference. Add them in a later version.
- **Sorting a bucket by the model, or hiding tracks.** Bucket order stays as it is (`added_at DESC`).
- **Automatic distribution by the model.** The owner plans to automate it later. v1 only lights buttons.
- **Fine-tuning, segments (drop / break) and a non-NC model set.**

## Anti-goals (failure even if it works)

- **The model never moves a track.** Only the owner's tap does. This is unlike the AI rule, which still moves AI tracks to
  DISCARD.
- **Nothing hidden** (the owner's rule for the AI switch). A lit button is visible, and the block shows which model is lit and
  how it scored.
- **The lab videos must not be downloaded again.**
- **Audio is not kept** beyond the analyzer's 7-day cache TTL, as today.
- **No periodic schedule that wakes Aurora.** Aurora runs with min ACU 0. All new work is event-driven: finalize, label count,
  new profiles.

## Decisions

The table lists the owner's decisions from the 2026-10-23 conversation, then my calls. Calls marked *mine* can be overruled.

| Topic | Decision |
|---|---|
| Profile | Light only: MuLan, MuQ, EffNet, MusiCNN. Heavy blocks come in the next iteration. |
| Storage | S3 is the feature store. The PC only downloads and computes, and keeps nothing beyond the audio TTL. |
| Training and scoring | In AWS (a new ML worker Lambda), so models retrain even with the PC off. |
| Retrain triggers | Block finalize, and every 150 new labels of a (user, style). |
| Prediction scope | Every track of the style that has a profile, for every user × style with a model. Not only open blocks. |
| Category prediction | The full ranking with probabilities is stored. The UI shows the top two. |
| Lit buttons | Predicted keep (or no keep head): top-1 category bright, top-2 pale. Predicted discard: DISCARD bright, top-1 category pale. |
| Similar tracks | Not in v1. |
| Anchoring | Buttons light from the first model on, with no shadow period and no per-block switch (owner, option A). The owner accepts that later labels and the "first button right" number are made with the suggestion in view. |
| Admin | An "Audio profile" card next to the "AI analysis" card (§6). |
| Old tracks without audio | Analyzed before the profile existed, audio evicted (~16 k): re-downloaded once, after open blocks and new releases (claim order). |
| Who gets models | Every user with enough labels in a style, automatically. |
| Keep threshold | *Mine:* predicted keep share equals the labelled keep share (~27 % for DnB), set on out-of-fold predictions. |
| Labels | *Mine:* AI-flagged tracks are not labels, so the model doesn't learn the AI rule as taste. Details in "Labels". |
| Model line in the block | *Mine:* shows the model date, label count, and how often the previous model's first button was right. |
| Backup | *Mine:* S3 versioning on the features bucket. A noncurrent version expires after 30 days. |

## Architecture

```
PC (clouder-analyzer, GPU)                       AWS
──────────────────────────                       ──────────────────────────────────────────────
claim (+ light_profile) ──► POST /v1/analysis/claim
download → decode → AI detectors → results ──► POST /v1/analysis/results              (unchanged)
            └──► light profile ──────────► POST /v1/analysis/features ──► S3 features/light-1/<video>.f16
profile-dir DIR (lab / cache backfill) ──►          │                       + audio_features row
                                                    │                       + track_analyses light_profile ok
                                                    └──► SQS ml-jobs {score, video_ids}
triage finalize ───────────────────────────────────► SQS ml-jobs {retrain, user, style}
move / transfer, +150 labels since last train ──────► SQS ml-jobs {retrain, user, style}
                                                    ML worker Lambda (numpy, scikit-learn)
                                                    ├─ retrain: labels → heads → S3 models/… → ml_models
                                                    │           → score the whole style → track_predictions
                                                    └─ score:   new profiles × models of their style → track_predictions
GET bucket tracks / block  ◄── prediction per track, model line ── triage UI lights buttons
```

## 1. The light profile, version `light-1`

**The lab code is the reference, and v1 must reproduce it.** The lab's numbers rest on exactly these features. The code lives in
`/Users/roman/Projects/HP/ai_detect/ideas/lab/lab/`:
- `audio.py`: decode and the `mono_16k` / 24 kHz views;
- `extractors/{mulan,muq,effnet,musicnn}.py`;
- `hot.py`: track means.

**Decode** is the same ffmpeg call the analyzer already makes: float32 stereo at 44.1 kHz. Mono views use `resample_poly`, as in
the lab `audio.py`.

**Pooling.** Each array is reduced to its mean over time (lab `hot.py`: float64 mean, then float32). The profile is the
concatenation below, 16 778 values, stored as raw little-endian float16 (33 556 bytes per video):

| offset | width | block | source array (lab) |
|---:|---:|---|---|
| 0 | 400 | effnet | `discogs400` (genre_discogs400 head), mean |
| 400 | 1280 | effnet | `embedding` (discogs-effnet-bs64-1), mean |
| 1680 | 512 | mulan | `mix.clips` (MuQ-MuLan-large 10 s clips), mean |
| 2192 | 1024 | muq | `mix.final`, mean |
| 3216 | 13312 | muq | `mix.layers_1hz` (13 × 1024 raveled), mean |
| 16528 | 200 | musicnn | `embedding`, mean |
| 16728 | 50 | musicnn | `taggram`, mean |

- **Order** is the lab hot table's column order, extractor then array name, both sorted (`hot.build`). So a profile row
  compares to a lab hot row element by element. The table above is the contract that clouder-core and the ML worker share. Changing the layout means a new version
  (`light-2`) and a recompute, which needs audio. So the layout is frozen, and every module that reads it imports one shared
  constant.
- **Model weights are pinned** by repo, revision and SHA-256, as in the lab extractors. Examples: MuLan
  `OpenMuQ/MuQ-MuLan-large@2e01c796…`; the essentia graphs by file SHA.
- **Parity gate** before any backfill:
  - the analyzer's profile for ≥ 50 lab videos must match the lab hot tables (`lab-data:/lab/ablation/hot`,
    `/lab/ablation_more/hot`);
  - the threshold is cosine ≥ 0.999 per block and no NaN.
  - A miss blocks the rollout, because the lab metrics do not transfer otherwise.

## 2. clouder-analyzer (private repo, Windows PC)

### Analyzer and image

- **New analyzer `light_profile`,** registered like `ai_lofcz` (`analyzers/__init__.py`). It runs on the decoded `Audio`
  after the AI detectors.
  - It does not post through `/results` on success. It posts the vector to `POST /v1/analysis/features`, which also marks the
    track done (§3).
  - On failure it posts `light_profile` `failed` / `unusable_source` through `/results`, as today.
- **The image moves to CUDA**, the same base and torch as the lab's `lab-base` (CUDA 13 + cuDNN, torch 2.8 cu128, proven on
  the PC's RTX 5070 Ti).
  - It adds `muq==0.1.0` (no deps, as in the lab Dockerfile) and `essentia-tensorflow==2.1b6.dev1389`.
  - Compose gets a GPU reservation.
  - The image's layers should match `lab-base` so Docker shares them: the PC's C: drive is tight. Check free space before the
    build.
- **Speed.** On the lab run the profile costs ~6 s of model time per track (~12 s with decode). The pipeline must keep up with
  `DOWNLOADS_PER_HOUR=250`, about 14 s per track.
  - Measure in the first pass, and log per-track profile time.
  - If the profile becomes the bottleneck, it runs in its own worker thread, not inline.

### Backfill command

`clouder-analyzer profile-dir DIR [--recursive]`:
- Takes every `<video_id>.opus` under DIR, computes the profile and posts it to `/v1/analysis/features`. No download, no claim,
  no lease.
- Skips videos the server already has. The server answers "already have" per item, and the command may batch a check first.
- Runs as a one-off container with the lab volume mounted read-only (`-v lab-data:/lab:ro`) on:
  - `/lab/audio` (105 videos);
  - `/lab/ablation` (781);
  - `/lab/ablation_more` (2 462);
  - the analyzer's `/data/cache`.
- Lab files have no `.duration` sidecar, so the command must not need one.
- **Rollout order matters:** run this backfill **before** the claim asks for `light_profile`. Otherwise the claim would hand
  the lab tracks out and the analyzer would re-download them. Lab tracks are old, so they come last in claim order anyway, but
  don't rely on that.

### PC constraints

These are standing rules from the owner:
- **On the Mac:** nothing runs, no python, pytest, uv or docker. Edit, git, ssh and scp only. Tests and probes run on the PC
  in the analyzer image.
- **Analyzer container:** never stop `clouder-analyzer-analyzer-1` for lab work. Deploying the analyzer as a step of this plan
  is fine.
- **Lab volume:** never wipe `lab-data`, and mount it read-only.
- **Docker over ssh:** source `. $HOME\.docker-ssh\env.ps1` first. Put commands in `.sh` files, because PowerShell mangles
  quotes and `$`. Edit `.env` only through an alpine `sed`.

## 3. clouder-core: the feature store

**Bucket `clouder-prod-audio-features`.** It is private with SSE-S3 and versioning; a noncurrent version expires after 30
days.
- Keys are `features/light-1/<video_id>.f16`, the 33 556 bytes of §1.
- Keys `models/<user_id>/<style_id>/v<version>.npz` hold the models (§5).

**Table `audio_features`** (migration 45):
- columns: `video_id` (PK), `version`, `audio_sha256`, `created_at`;
- one row per video whose profile is in S3;
- the profile belongs to the audio, so it is keyed by video. Several tracks can share one video.

**`POST /v1/analysis/features`.** Service token, the same authorizer as claim / results.
- Request body: `{items: [{video_id, version: "light-1", audio_sha256, vector_b64}]}`, 1–50 items.
- Validation, stdlib only, with no numpy in the collector:
  - the decoded length is exactly 33 556 bytes;
  - `struct.unpack('<16778e')` gives all finite values;
  - the version is known.
- For each accepted item:
  - put the S3 object;
  - upsert `audio_features`;
  - upsert `track_analyses (track_id, 'light_profile', status 'ok', version, video_id, audio_sha256, analyzed_at)` for every
    track whose `vendor_track_map` ytmusic video is this one. This overrides a lease, so a later claim skips those tracks.
- Then one SQS message `{type: "score", video_ids: [...]}` for the accepted videos.
- Response: `{accepted: [...], rejected: [{video_id, reason}]}`. An already-stored video with the same version and
  `audio_sha256` is accepted as a no-op.
- **Route = three places:** `_ROUTE_TABLE`, `scripts/generate_openapi.py`, and `infra/analysis.tf`. Then regenerate
  `openapi.yaml` and `schema.d.ts`, and sync the analyzer's `contract/analysis.openapi.yaml`.

**A profile follows the track's current match.** *My call:* the lab found every manual re-match among the keeps, so losing
re-matched tracks would skew the labels.
- `upsert_vendor_match` can replace a track's ytmusic `vendor_track_id`.
- When it does, the same write deletes the track's `light_profile` row in `track_analyses`, unless `audio_features` already
  has the new video; in that case the row is set `ok` for the new video.
- Labels and scoring always join track → current `vendor_track_map` video → `audio_features`, never `track_analyses.video_id`.
- The AI analyzers' rows are out of scope here.

**Claim** is otherwise unchanged: `light_profile` is just one more analyzer name. Tracks analyzed before the profile existed miss it, so
the claim hands them out in its existing order: open blocks first, then newest release. That is the one-time re-download of
~16 k tracks, ~3 days at 250/h.
- **One download serves every analyzer.** A new track comes out with all three names missing, and one download runs the AI
  pair and the profile.
- **A track the AI pair already checked** (~19.8 k on 2026-10-23) comes out with `analyzers: ["light_profile"]` only. The
  analyzer runs only what the claim lists, so the AI pair does not re-run on it. The owner allowed a re-run, but nothing needs
  one.

## 4. Labels

For user U and style S, computed by the ML worker from Aurora:
- **Keep, with category c:**
  - every track in an active STAGING bucket (category c) of U's non-deleted blocks of style S, open or finalized;
  - plus every row in `category_tracks` of U's live categories in S (this includes tracks added outside triage);
  - a track in several categories takes the one with the latest `added_at`.
- **Discard:** every track in a DISCARD bucket of those blocks, unless it is also a keep. Keep wins: the owner kept it
  somewhere.
- **Not labels:**
  - tracks flagged by the AI rule (`AI_FLAGGED_SQL`);
  - tracks in NEW / OLD / NOT / UNCLASSIFIED / FAV buckets (auto buckets, not decisions);
  - tracks without an `audio_features` row.
- **Soft-deleted category:** its tracks stay keeps but are not a category class.

## 5. Models (ML worker)

### Training

- **The pipeline is the lab's `ablation.pipeline()`**, ported (`ideas/lab/lab/ablation.py`):
  - median impute, standardise, block weights 1/√width over the four extractor blocks (effnet 1 680, mulan 512,
    muq 14 336, musicnn 250);
  - PCA on the train rows;
  - `LogisticRegressionCV`: C over 1e-4…1e4 (LAB_C_MAX=4), inner stratified 3-fold;
  - keep head: `roc_auc`;
  - category head: multinomial, `balanced_accuracy`, `class_weight="balanced"`;
  - scikit-learn 1.7.2, as in the lab.
- **When each head trains:**
  - keep head: needs ≥ 130 labels, with ≥ 35 keeps and ≥ 35 discards;
  - category head: needs ≥ 2 categories, each with ≥ 30 labelled tracks, and only those categories are classes;
  - if neither head qualifies, nothing is written, and the next trigger tries again.
- **Training rows are videos,** as in the lab. Tracks that share a video collapse into one row, and a video whose tracks
  disagree (keep vs discard, or two categories) is dropped.
- **Keep threshold:** the (1 − keep share) quantile of out-of-fold keep probabilities (3-fold `cross_val_predict`).
- **Stored form is compact and linear.** The PCA rotation, scaler and block weights fold into one linear map per head:
  - medians (16 778) for NaN imputation, weights (16 778 × K), bias (K);
  - float32 in one npz under `models/…/v<version>.npz`, roughly 0.1–1 MB;
  - a test must show it reproduces the fitted pipeline's `predict_proba` within 1e-5.
  - Scoring is then a dot product.
- **Budget:** a retrain, including scoring the whole style, finishes inside the Lambda limit. Target: under 10 min for DnB
  (~5 k labels, ~11 k profiled tracks). Profiles are fetched from S3 with a thread pool.
  - `# ponytail:` one GET per video. Keep a consolidated per-style matrix only if fetch time measurably dominates.

### Table `ml_models` (migration 45)

- One row per (user_id, style_id), the latest model only.
- Columns:
  - `version` int, incremented atomically;
  - `trained_at`, `retrain_requested_at`;
  - `n_labels`, `n_keep`;
  - `keep_threshold` (NULL = no keep head);
  - `classes` jsonb (category ids in head order; NULL = no category head);
  - `metrics` jsonb, `artifact_key`.

### Table `track_predictions` (migration 45)

- PK (user_id, style_id, track_id).
- Columns:
  - `model_version`;
  - `keep_score` real (NULL = no keep head), `keep` bool;
  - `categories` jsonb: `[[category_id, p], …]`, all classes, sorted by p descending (NULL = no category head);
  - `scored_at`.
- An upsert never replaces a row that carries a newer `model_version`.

### Jobs

There is one SQS queue `ml-jobs` and one ML worker Lambda.
- **Packaging:** numpy, scipy and scikit-learn, in a zip if it stays ≤ 250 MB unzipped, otherwise a container image. The
  builder's call. It needs its own pinned requirements lock, covered by the `deps` CI job.
- **Database:** the Data API only, like every Lambda here (no psycopg).

| Message | Producer | Work |
|---|---|---|
| `{type: "retrain", user_id, style_id}` | Finalize (next to `enqueue_block_auto_enrich`, best-effort) | Labels → metrics of the previous model → train → artifact → `ml_models` → score every profiled track of the style |
| same | Move / transfer into a STAGING or DISCARD bucket: when the count of such placements with `added_at > trained_at` (AI-flagged excluded) reaches 150 | same |
| `{type: "score", video_ids}` | `POST /v1/analysis/features` | Video → tracks → their style → each model of that style → upsert predictions |

**Dedupe:** a retrain is enqueued only when `retrain_requested_at` is not pending. Pending means newer than `trained_at` and
less than 1 h old, which also bounds a lost message. Two retrains of one pair must not leave an older version on top. The
atomic version bump and the guarded upsert cover that.

**The count check** must not slow a tap noticeably: one small indexed query in the move route.

**First model:** for the owner's DnB (and anyone already past the thresholds), send one retrain message by hand after the
backfill. The rollout carries the exact AWS CLI command. No admin route.

### Metrics

Each retrain is recorded in `metrics`:
- **The honest number.** Labels added since the previous `trained_at` are compared with the stored predictions of the previous
  model:
  - **first button right** (`first_hit`, `first_n`), the number the model line shows. *My call:* this is what the owner
    actually sees. The share of new labels where the previous model's primary button, per the lighting rule in §6, equals
    his decision: DISCARD for a discard, or the category for a keep. Every new label with a stored prediction counts.
    - The ranking is filtered to the categories alive now.
    - It is dominated by discards (~73 %), so the per-head numbers below are stored too.
  - keep AUC;
  - top-1 and top-2 category hit rate over keeps, counting only the classes that model knew;
  - n for each.
- **Inner-CV scores** of both heads. For DnB they should land near the lab's stratified numbers, keep AUC ≈ 0.81 and balanced
  accuracy ≈ 0.69. A big miss means a port bug.

## 6. API and UI

### API

- **Bucket tracks** (`list_bucket_tracks`, also used by Curate) gain `prediction: {keep: bool | null, category_ids: [ordered]}
  | null` per row.
  - It joins `track_predictions` on the block's user and style.
  - It returns only the caller's own predictions.
- **Block detail** (`GET /triage/blocks/{id}`) gains `model: {trained_at, n_labels, first_hit, first_n} | null`.
- Regenerate OpenAPI and `schema.d.ts`.

### Which buttons light

`suggestedDestinations(prediction, destinations)` is a pure function in the triage `lib/`, shared by both screens, with unit
tests.
- **Ranking:** `category_ids` filtered to categories with an active STAGING bucket in this block. Deleted or new categories
  drop out, so the next one moves up.
- **Predicted discard** (`keep === false`): primary = DISCARD, secondary = the ranking's first.
- **Otherwise** (keep true, or no keep head): primary = the ranking's first, secondary = its second.
- **Not rendered, not lit.** A primary or secondary bucket that isn't among the rendered buttons (for example the current
  bucket) is not lit, and nothing shifts into its place.
- **No prediction** (no profile, or no model yet): nothing lights.

### Two screens

- **Bucket player panel** (`BucketDistributeButtons.tsx`):
  - primary is Mantine `variant="filled"`, secondary `variant="light"`;
  - DISCARD as primary becomes `filled red`.
  - DISCARD's current default look is `light red`, so the pale suggestion must use a different colour.
- **Curate** (`DestinationGrid` / `DestinationButton`):
  - the same two levels through a data attribute and CSS module styles;
  - hotkeys are unchanged.
- **Both screens:** a lit button carries an accessible "suggested" description, so the meaning is not colour-only.
- **Verify in a real browser** (`pnpm test:browser`), desktop and mobile widths. jsdom cannot see styles.

### Model line

On the triage block page, small and secondary, for example: "Suggestions: model of 24 Oct · 3,235 labels · first button right
71 %".
- The hit-rate part shows only when `first_n ≥ 20`.
- With no model the line is absent.
- The copy goes in `en.json`.

### Admin: an "Audio profile" card next to "AI analysis"

Owner request, 2026-10-23. The current card is on `/admin/coverage` (`AnalysisStatus.tsx`, compact since #378).
- **Layout:** the two cards sit side by side on desktop and stack on mobile.
- **The new card shows:**
  - its last result;
  - **Queue:** Waiting, Profiled, Failed, No usable audio — the `light_profile` counts, worded like the AI card's queue row;
  - *My call:* **Models:** the number of trained (user, style) models and when the last retrain ran. Without it, a stalled
    ML worker is visible only in CloudWatch.
- **Backend:** `GET /admin/analysis/status` gains `profile: {waiting, profiled, failed, unusable}` and
  `models: {count, last_trained_at}`.
- **The AI card stays as it is.**

## Rollout order and gates

1. **clouder-core:** migration 45, bucket, the features endpoint, the admin "Audio profile" card, deploy. *Gate:* a contract
   test posting a real 33 556-byte vector. The card then tracks the backfill and the re-download from step 3 on.
2. **Analyzer:** the `light_profile` analyzer, CUDA image, `profile-dir`. *Gate:* parity with the lab hot tables (§1). Deploy
   with `light_profile` **not yet claimed**.
3. **Backfill:** `profile-dir` over the four directories. *Gate:* `audio_features` holds every lab video, and every labelled
   track whose current video is a lab video has `light_profile ok`.
4. **Claim:** enable `light_profile` in the claim. *Gate:* the first pass logs profile time and keeps ~250/h.
5. **ML worker:** the worker, queue and triggers; then the first DnB retrain by hand. *Gate:* DnB inner-CV is near the lab
   numbers (§5), and predictions exist for every profiled DnB track.
6. **API and UI:** lit buttons and the model line. *Gate:* browser test screenshots for both screens, all four lighting cases.

## Constraints

- **clouder-core:**
  - Data API only, never psycopg in Lambda paths;
  - `PYTHONPATH=src`;
  - two-phase deploy, so the migration lands before the API Lambda;
  - Aurora cold start can exceed 29 s, which a worker retry must tolerate.
- **Data API:** no array params. Use VALUES lists or `jsonb_to_recordset`, as `record_analysis_results` does.
- **Git and PRs:**
  - main is PR-only with 8 required checks;
  - Conventional Commits ≤ 50 chars, author tarodo, no AI attribution;
  - merge PRs right after the checks pass.
- **Cost:** S3 ≈ 2 GB per 60 k tracks, about $0.05 per month. The ML worker runs on events only.
- **Licences:** MuLan, MuQ, EffNet and MusiCNN weights are CC BY-NC, and essentia is AGPL. The owner accepted this for a
  non-commercial project.

## Left to the builder

- Module and function names, zip vs image for the ML worker, and the SQS and Lambda sizes.
- How the analyzer threads the profile, and the GPU memory settings.
- Exact copy and styling within the rules above.
- How `profile-dir` checks which videos the server already has.
