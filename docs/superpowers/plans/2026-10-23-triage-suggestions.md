# Triage suggestions v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:**
- clouder-analyzer computes the light audio profile and ships it to S3.
- An AWS ML worker trains per-(user, style) keep/discard and category heads and stores predictions.
- Triage lights the suggested buttons.

**Architecture.** Three PRs in clouder-core plus one in clouder-analyzer, released in this order: feature store → analyzer
→ ML worker → API and UI. Controller ops steps sit between them: deploys, the parity gate, the lab backfill and the
first retrain.

**Tech Stack:**
- clouder-core: Python 3.12 Lambdas on the Aurora Data API, Terraform, React 19 + Mantine 9.
- clouder-analyzer: Python 3.12 with uv, CUDA torch 2.8, `muq==0.1.0`, `essentia-tensorflow==2.1b6.dev1389`.
- ML: numpy and scikit-learn 1.7.2.

**Spec:** `docs/superpowers/specs/2026-10-23-triage-suggestions-design.md`. Read it first; it is the authority.

## Global Constraints

- **clouder-core runtime:**
  - DB access goes only through the Data API (`self._data_api.execute`), never psycopg in `src/collector/` runtime paths;
  - no array params: use `jsonb_to_recordset(CAST(:items AS jsonb))`, comma-joined text, or `:t{i}` placeholders;
  - a Data API response is capped at 1 MiB, so paginate anything that can exceed ~2 000 rows.
- **Route = three places:**
  - `src/collector/handler.py` `_ROUTE_TABLE`, `scripts/generate_openapi.py` `ROUTES`, and an `infra/*.tf` route;
  - service-token routes also need the route key allowed in `src/collector/auth_authorizer.py`.
  - Then regenerate: `PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py` and `cd frontend && pnpm api:types`.
- **Repository layer:**
  - a new public repository method goes alphabetically into `tests/unit/test_repositories_layout.py` `API`;
  - a new mixin module goes into `AGGREGATES` and `repositories/__init__.py`;
  - modules stay ≤ 600 lines.
- **Commits and PRs:**
  - Conventional Commits, subject ≤ 50 chars, author tarodo, no AI attribution or Co-Authored-By;
  - never stage `graphify-out/`;
  - a PR merges with `gh pr merge --merge` after all 8 checks pass.
- **clouder-analyzer (Mac rule):**
  - nothing runs on the Mac: no python, pytest, uv, pip or docker;
  - edit, git, ssh and scp only;
  - tests, `uv lock` and image builds run on the PC (`ssh vorom@192.168.0.60`).
- **PC Docker:**
  - first `. $HOME\.docker-ssh\env.ps1`; multi-command work goes in `.sh` files written on the Mac, scp'd and run inside a
    container (PowerShell mangles quotes and `$`);
  - never stop `clouder-analyzer-analyzer-1` outside a planned deploy;
  - never write to or wipe `lab-data` (mount it `:ro`);
  - edit the PC `.env` only with an alpine `sed`.
- **Profile contract `light-1`:**
  - 16 778 float16 little-endian values, 33 556 bytes;
  - layout per spec §1: effnet/discogs400 0..400, effnet/embedding 400..1680, mulan/mix.clips 1680..2192,
    muq/mix.final 2192..3216, muq/mix.layers_1hz 3216..16528, musicnn/embedding 16528..16728,
    musicnn/taggram 16728..16778.
- **Thresholds:**
  - keep head: ≥ 130 labels, ≥ 35 keep, ≥ 35 discard;
  - category head: ≥ 2 categories with ≥ 30 tracks each;
  - retrain after 150 new labels;
  - `first_n ≥ 20` to show the hit rate.
- **Training:**
  - C grid `np.logspace(-4, 4, 9)`, inner `StratifiedKFold(3, shuffle=True, random_state=0)`, `max_iter=5000`;
  - block weights 1/√width for effnet 1 680, mulan 512, muq 14 336, musicnn 250;
  - category head: `class_weight="balanced"`, scoring `balanced_accuracy`; keep head: `roc_auc`.

## Review Focus

1. **Re-matched track.** A track whose matched video changed after profiling must be labelled and scored by its
   *current* video, or not at all. Tests: Task 2 (re-match hook) and Task 7 (`ml_labels` joins the current
   `vendor_track_map`).
2. **Two tracks on one video in one claim.** One feature post, both tracks `light_profile ok`. Tests: Task 2
   (`record_audio_features` marks every mapped track) and Task 5 (runner dedupes the blob by video).
3. **A deleted category in a stored ranking.** The UI skips it and lights the next category. Test: Task 10
   `suggestedDestinations` "deleted category".
4. **A new style below the thresholds** (techno's first block). The retrain writes no model and does not crash, and the
   next trigger can fire again. Test: Task 7 "too few labels".
5. **Very short or odd audio.** Under 10 s (MuLan tiling), under 30 s (a single MuQ window), or mono: the profile is still
   16 778 finite values. A non-finite vector is rejected by the server. Tests: Task 4 and Task 2.

---

## PR 1 — clouder-core: feature store (branch `feat/triage-suggestions`)

### Task 1: Migration 45, ORM models, profile layout module

**Files:**
- Create: `alembic/versions/20261023_45_triage_suggestions.py` (revision `"20261023_45"`, down_revision `"20261023_44"`)
- Modify: `src/collector/db_models.py`, `docs/data/data-model.md`, `src/collector/user_deletion.py` (only if it enumerates
  tables)
- Create: `src/collector/audio_profile.py`, `tests/unit/test_audio_profile.py`
- Test: `tests/db/test_triage_suggestions_pg.py`

**Interfaces:**
- Produces the tables:
  - `audio_features(video_id varchar(32) PK, version varchar(16) NOT NULL, audio_sha256 char(64) NOT NULL,
    created_at timestamptz NOT NULL)`;
  - `ml_models(user_id varchar(36) FK users ON DELETE CASCADE, style_id varchar(36) FK clouder_styles,
    version int NOT NULL DEFAULT 0, trained_at timestamptz, retrain_requested_at timestamptz,
    n_labels int NOT NULL DEFAULT 0, n_keep int NOT NULL DEFAULT 0, keep_threshold real, classes jsonb,
    metrics jsonb NOT NULL DEFAULT '{}', artifact_key text, PK(user_id, style_id))`, where `version = 0` means requested,
    never trained;
  - `track_predictions(user_id varchar(36) FK users ON DELETE CASCADE, style_id varchar(36),
    track_id varchar(36) FK clouder_tracks, model_version int NOT NULL, keep_score real, keep boolean,
    categories jsonb, scored_at timestamptz NOT NULL, PK(user_id, style_id, track_id))`.
- Produces `collector.audio_profile`:
  - `VERSION = "light-1"`, `DIMS = 16778`, `NBYTES = 33556`;
  - `ARRAYS: tuple[tuple[str, int, int], ...]` (name, offset, width) — the seven rows of the Global Constraints;
  - `BLOCKS = (("effnet", 0, 1680), ("mulan", 1680, 512), ("muq", 2192, 14336), ("musicnn", 16528, 250))`;
  - `decode_vector(data: bytes) -> tuple[float, ...]` raises `ValueError`;
  - `s3_key(video_id: str) -> str` returns `"features/light-1/<video_id>.f16"`.

- [ ] **Step 1: Write the failing tests.**
  - `test_audio_profile.py`:
    - `test_layout_is_contiguous`: offsets chain and the last end is 16778;
    - `test_blocks_cover_arrays`;
    - `test_decode_roundtrip`: `struct.pack('<16778e', *vals)` decodes back;
    - `test_decode_rejects_wrong_length`;
    - `test_decode_rejects_nan_and_inf`;
    - `test_s3_key`.
  - `test_triage_suggestions_pg.py::test_tables_exist_and_cascade`: insert a user, an ml_models row and a prediction; delete
    the user; both rows are gone.
- [ ] **Step 2: Run them and see them fail.**
  - `pytest tests/unit/test_audio_profile.py -q` → ImportError.
  - The db test runs in CI `alembic-check`. Locally it runs only if `TEST_DATABASE_URL` is set.
- [ ] **Step 3: Implement.**
  - `decode_vector` uses `struct.unpack("<16778e", data)` and `math.isfinite`. Stdlib only: the collector zip has no numpy.
- [ ] **Step 4: Run.** `pytest tests/unit/test_audio_profile.py tests/unit/test_repositories_layout.py -q` → PASS.
- [ ] **Step 5: Commit.** `feat(db): feature store and model tables`.

### Task 2: `POST /v1/analysis/features`, re-match hook, bucket and queue infra

**Files:**
- Modify:
  - `src/collector/schemas.py`, `src/collector/api/routes_analysis.py`, `src/collector/handler.py`,
    `src/collector/auth_authorizer.py`;
  - `src/collector/repositories/vendor_match.py`, `src/collector/repositories/__init__.py`;
  - `scripts/generate_openapi.py`, `docs/api/openapi.yaml`, `frontend/src/api/schema.d.ts`;
  - `infra/s3.tf`, `infra/sqs.tf`, `infra/main.tf` (locals), `infra/variables.tf`, `infra/analysis.tf`,
    `infra/lambda_roles.tf` (collector role), `infra/lambda.tf` (collector env).
- Create: `src/collector/repositories/audio_features.py` (`AudioFeaturesMixin`), `src/collector/ml_jobs.py`
- Test: `tests/unit/test_analysis_features_route.py`, `tests/db/test_audio_features_pg.py`, the infra guard tests
  (`tests/unit/test_analysis_infra.py`, `test_iam_per_function_infra.py`)

**Interfaces:**
- Consumes `collector.audio_profile` (Task 1).
- Produces the schemas:
  - `AnalysisFeatureItem(video_id: str, pattern ^[A-Za-z0-9_-]{6,32}$; version: Literal["light-1"];
    audio_sha256: ^[0-9a-f]{64}$; vector_b64: str, max 44 800 chars)`;
  - `AnalysisFeaturesRequest(items: 1..50, video_ids unique)`;
  - response `AnalysisFeaturesResponse {accepted: int, rejected: [{video_id, reason}]}`, reasons `"bad_vector"`.
- Produces `AudioFeaturesMixin`:
  - `known_audio_features(*, video_ids: list[str]) -> dict[str, tuple[str, str]]`, video → (version, sha);
  - `record_audio_features(*, items: list[dict], now: datetime) -> int`: upserts `audio_features`, then upserts
    `track_analyses(track_id, 'light_profile', status 'ok', version, video_id, audio_sha256, analyzed_at=now,
    lease cleared)` for every track whose matched video in `vendor_track_map` is in the items. Returns the number of
    track rows.
- Produces `collector.ml_jobs`:
  - `enqueue_score(*, video_ids: list[str]) -> None`, best-effort like `enqueue_block_auto_enrich`;
  - env `ML_JOBS_QUEUE_URL`; message body `{"type": "score", "video_ids": [...]}`.
- Produces infra:
  - bucket `aws_s3_bucket.audio_features`, name `"${local.name_prefix}-audio-features"`, with versioning, a noncurrent
    expiry of 30 days, multipart abort at 7 days, AES256 and a full public-access block;
  - queue `aws_sqs_queue.ml_jobs` plus a DLQ: retention 1 209 600 s, visibility 960 s, maxReceiveCount 3;
  - collector env `AUDIO_FEATURES_BUCKET` and `ML_JOBS_QUEUE_URL`;
  - collector role: `s3:PutObject` on `features/*` and `sqs:SendMessage` on `ml_jobs`.

- [ ] **Step 1: Write the failing tests.**
  - Route tests, with a fake repository, a fake S3 client and a fake SQS client:
    - `test_features_accepts_valid_vector`: S3 `put_object` key `features/light-1/<vid>.f16`, body 33 556 bytes; repo called;
      one SQS message `{"type":"score","video_ids":[vid]}`;
    - `test_features_rejects_bad_vector`: a NaN gives `rejected[0].reason == "bad_vector"`, no S3 put;
    - `test_features_same_sha_is_noop_put`: `known_audio_features` returns the same (version, sha), so no S3 put, but the
      item is still accepted and recorded;
    - `test_features_requires_service`: 403 without the service context.
  - DB tests:
    - `test_record_marks_every_track_on_video`: two tracks map to one video; both get `light_profile ok`, and an existing
      lease row is overwritten;
    - `test_rematch_deletes_stale_light_profile`: `upsert_vendor_match` to a new video without features deletes the row;
    - `test_rematch_to_profiled_video_sets_ok`: the new video has features, so the row is `ok` with the new `video_id`;
    - `test_rematch_same_video_keeps_row`.
- [ ] **Step 2: Run** `pytest tests/unit/test_analysis_features_route.py -q` → FAIL.
- [ ] **Step 3: Implement.**
  - **Handler** `_handle_analysis_features`:
    - `_require_service`, then `_parse`;
    - for each item: base64-decode, then `decode_vector` (on error the item is rejected as `bad_vector`);
    - `known_audio_features`, then S3 `put_object` for new or changed items;
    - `record_audio_features`, then `enqueue_score(accepted video ids)`.
  - **Clients:** the S3 client comes from `boto3.client("s3")` through a module-level builder, as in
    `auto_enrich_dispatch`.
  - **Re-match hook:** in `upsert_vendor_match`, when `vendor == "ytmusic"`, add two statements on the same
    `transaction_id`:
    - delete the `light_profile` row whose `video_id IS DISTINCT FROM :video`;
    - insert or update it to `ok` from `audio_features` when the new video is there.
- [ ] **Step 4: Add the route in three places, then regenerate OpenAPI and `schema.d.ts`.** Infra guard tests updated.
- [ ] **Step 5: Run** `pytest -q` (whole suite) plus `cd infra && terraform fmt -check && terraform validate` → PASS.
- [ ] **Step 6: Commit.** `feat(analysis): feature store upload route`.

### Task 3: Admin "Audio profile" card

**Files:**
- Modify:
  - backend: `src/collector/repositories/analysis.py` (`analysis_status`), `scripts/generate_openapi.py`
    (`ANALYSIS_STATUS`), `docs/api/openapi.yaml`, `frontend/src/api/schema.d.ts`;
  - frontend: `frontend/src/features/admin/routes/AdminCoveragePage.tsx`, `frontend/src/i18n/en.json`,
    `frontend/src/features/admin/components/AnalysisStatus.tsx` (only to export `Stat` or move it to `Stat.tsx`).
- Create: `frontend/src/features/admin/components/AudioProfileStatus.tsx` + `__tests__/AudioProfileStatus.test.tsx`
- Test: `tests/unit/test_analysis_status*.py` (the existing status tests), `tests/db/test_analysis_pg.py` (status case)

**Interfaces:**
- `analysis_status` also returns:
  - `profile: {waiting, profiled, failed, unusable}`, the `light_profile` counts. `waiting` = matched tracks with
    no held `light_profile` row (`_HELD`).
  - `models: {count: int, last_trained_at: datetime | None}` over `ml_models` with `version > 0`.
- i18n `admin.profile_status`:
  - `title` "Audio profile";
  - the queue: `queue` "Queue:", `waiting` "Waiting", `profiled` "Profiled", `failed` "Unavailable",
    `unusable` "No usable audio";
  - the models line: `models` "Models: {{count}} · last retrain {{ago}}", `models_none` "No models yet".

- [ ] **Step 1: Write the failing tests.**
  - DB: `test_status_profile_counts` (one ok, one failed, one unleased mapped track gives waiting 1) and
    `test_status_models_block`.
  - Frontend `AudioProfileStatus.test.tsx`: renders "Audio profile", the four queue stats and "No models yet" when the
    count is 0.
  - Update the `AnalysisStatus.test.tsx` fixture with the new fields.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
  - The card shares the query key `['admin','analysisStatus']` with the AI card, so there is one fetch.
  - `AdminCoveragePage` wraps the two cards in `<SimpleGrid cols={{ base: 1, md: 2 }}>`.
- [ ] **Step 4: Run** `pytest -q`, `cd frontend && pnpm typecheck && pnpm lint && pnpm test` → PASS.
- [ ] **Step 5: Commit.** `feat(admin): audio profile status card`.

**PR 1 (controller).** Push, then `gh pr create`, watch the 8 checks, `gh pr merge --merge`, and watch Deploy.
- **Gate:** Deploy is green, the admin page shows both cards, and the live features route answers a service-token-less
  request with 401/403.
- The live upload is checked with real vectors in the PR A ops, step 4: `profile-dir --limit 5` first, then the DB and S3
  are checked through the RO role.

---

## PR A — clouder-analyzer (branch `feat/light-profile`, repo `clouder-analyzer` (sibling checkout))

**How the analyzer is tested.** Every test run happens on the PC.
- Ship the tree with `git archive HEAD | ssh vorom@192.168.0.60 "rm -rf ca-dev && mkdir ca-dev && tar -x -C ca-dev"`, as a
  `.sh` script.
- Build `docker build -t clouder-analyzer-dev ca-dev`.
- Run `docker run --rm --gpus all -v clouder-analyzer_analyzer-data:/data:ro clouder-analyzer-dev sh -c "uv sync --frozen
  --group dev && uv run pytest -q"`.
- Never touch the running `clouder-analyzer-analyzer-1`.

### Task 4: Light profile extractor port and parity command

**Files:**
- Create:
  - `src/clouder_analyzer/profile/__init__.py`, `layout.py`, `views.py`, `mulan.py`, `muq.py`, `essentia_models.py`
    (effnet + musicnn);
  - `src/clouder_analyzer/analyzers/light_profile.py`.
- Modify: `src/clouder_analyzer/analyzers/base.py` (`AnalyzerOutput.blob: bytes | None = None`), `pyproject.toml`
  (deps), `uv.lock` (regenerated on the PC), `src/clouder_analyzer/cli.py` (`parity` subcommand)
- Test: `tests/test_light_profile.py`, `tests/test_profile_layout.py`

**Interfaces:**
- `profile.layout.ARRAYS`, `DIMS = 16778` and `NBYTES = 33556` are identical to clouder-core `collector.audio_profile`. A
  test pins all seven rows.
- `profile_vector(audio: Audio, models: ProfileModels) -> np.ndarray` returns float32 of shape (16778,).
- `class LightProfile`: `name = "light_profile"`, `version = "light-1"`. `__init__(self, models_dir: Path)` loads all four
  models once. `run(audio) -> AnalyzerOutput(status="ok", result={"dims": 16778},
  blob=vec.astype("<f2").tobytes())`.
- CLI: `clouder-analyzer parity --hot FILE.parquet --audio-dir DIR [--limit 50]`:
  - prints per-block minimum cosine;
  - exits 1 if any block is under 0.999, or on any NaN or missing file.

**Steps:**
- [ ] **Step 1: Port the lab code exactly.** The reference is the owner's local lab repo `ai_detect/ideas/lab/lab/`:
  `audio.py` `Track.mono/mono_24k/mono_16k`, `extractors/{mulan,muq,effnet,musicnn}.py`, `hot.py` pooling.
  - Views: `mono = samples.mean(axis=0, dtype=float32)`; `resample_poly` with gcd ratios (24 kHz 80/147, 16 kHz 80/441).
  - Per-array dtype as in the lab:
    - effnet and musicnn arrays are cast to float16;
    - muq `mix.final` is `h[-1]` as float16, and `mix.layers_1hz` is 25-frame means as float16;
    - mulan `mix.clips` stays float32.
  - Then `a.mean(0, dtype=float64).astype(float32).ravel()`, concatenated in layout order.
  - MuLan: one forward over all 10 s clips; the tail is completed with `np.resize`; the strict key check stays as in the
    lab.
  - MuQ: 30 s windows, 20 s step, trim 125 frames, last window shifted, as in the lab `windowed`.
  - Essentia graph files come from `models_dir/essentia/<name>.pb` and `.json`. HF models load offline from
    `HF_HOME=models_dir/hf` (`HF_HUB_OFFLINE=1`).
  - Model pins:

    | model | pin |
    |---|---|
    | MuQ-MuLan-large | `2e01c796b71dca71b45251384c04cd7b237c9020` |
    | MuQ-large-msd-iter | `0562a57814f6f8bbd9fdea0a25921a2fce1a841a` |
    | xlm-roberta-base | `e73636d4f797dec63c3081bb6ed5c7b0bb3f2089` |

- [ ] **Step 2: Dependencies, in `pyproject.toml`.**
  - Add `torch==2.8.0` and `torchaudio==2.8.0` from a uv index `pytorch-cu128`
    (`https://download.pytorch.org/whl/cu128`, explicit), `essentia-tensorflow==2.1b6.dev1389`, `muq==0.1.0`
    (requires-dist emptied via `[[tool.uv.dependency-metadata]]`), `x-clip==0.14.4`, `easydict==1.13`,
    `torchvision==0.23.0`, `beartype==0.23.1`, `ftfy==6.3.1`, `regex==2026.9.29`, `transformers==4.53.2`,
    `pyarrow==26.0.0`.
  - Run `uv lock` in a container on the PC and copy `uv.lock` back with scp.
- [ ] **Step 3: Write the tests.**
  - `test_layout_matches_core`: seven rows, contiguous, 16778.
  - Model tests, skipped unless `/data/models` exists, so they run on the PC with the volume mounted:
    - `test_vector_finite_on_noise_40s`;
    - `test_vector_short_track_8s`: MuLan tiling and a single MuQ window;
    - `test_mono_source_ok`;
    - `test_blob_is_33556_bytes`.
- [ ] **Step 4: Run on the PC.** The full suite must pass, and the existing analyzer tests stay green.
- [ ] **Step 5: Commit.** `feat(profile): light profile extractor`.

### Task 5: GPU image, config, features client, runner routing, `profile-dir`, contract

**Files:**
- Modify:
  - `Dockerfile` (base `nvidia/cuda:13.0.3-cudnn-runtime-ubuntu24.04`, python3.12 + ffmpeg + uv + Deno; keep the lofcz
    model download and SHA check), `compose.yaml` (GPU reservation, env `HF_HOME=/data/models/hf`, `HF_HUB_OFFLINE=1`),
    `.env.example`;
  - `src/clouder_analyzer/config.py`: `light_profile: bool = False` (env `LIGHT_PROFILE`) and
    `profile_models_dir: Path = Path("/data/models")` (env `PROFILE_MODELS_DIR`). That makes 16 env names.
  - `src/clouder_analyzer/analyzers/__init__.py`: register `LightProfile` only when `settings.light_profile`.
  - `src/clouder_analyzer/api.py`: `FeatureItem(video_id, version, audio_sha256, vector: bytes)`, and
    `post_features(items) -> tuple[int, list[dict]]` sending `{"items": [{video_id, version, audio_sha256,
    vector_b64}]}`.
  - `src/clouder_analyzer/runner.py`: `ResultItem.blob` must not go into the results JSON.
  - `src/clouder_analyzer/cli.py`: the `profile-dir` subcommand.
  - `scripts/sync_contract.py`: also keep `/v1/analysis/features`.
  - `contract/analysis.openapi.yaml`: re-synced from clouder-core at the PR 1 merge commit.
  - Tests: `tests/test_packaging.py`, `tests/test_runner.py`, `tests/test_api.py`, `tests/test_contract.py`,
    `tests/test_cli.py`, `tests/test_ai_deezer.py` (registry keys).

**Interfaces:**
- **Runner** `_post`:
  - items whose analyzer output carried a `blob` are posted with `api.post_features` in chunks of 50, deduped by
    `video_id`;
  - those items are never posted to `/results`;
  - all other items are posted exactly as today;
  - rejected features are logged as `features_rejected` and counted in `RunSummary.rejected`.
- **`profile-dir`:** `clouder-analyzer profile-dir DIR [DIR ...] [--limit N]`.
  - It takes the audio files recursively, unique by stem, which is the video id.
  - It skips ids listed in `STATE_DIR/profile-dir.done` and appends accepted ids to that file, so the run can resume.
  - It decodes with `audio.decode` + `sha256_file`, with no `.duration` sidecar needed. It builds the profile with
    `LightProfile` regardless of `LIGHT_PROFILE`, and posts batches of 50.
  - It logs `profile_dir_progress` every 50 and prints a summary at the end.

- [ ] **Step 1: Write the failing tests.**
  - `test_blob_items_go_to_features_not_results`: a fake analyzer returns a blob; `FakeApi.features` gets one item and
    `posts` has none for it.
  - `test_two_tracks_one_video_post_one_feature`.
  - `test_post_features_body_matches_contract` (the jsonschema `AnalysisFeaturesRequest`).
  - `test_profile_dir_resumes_from_done_file`.
  - `test_registry_without_light_profile_by_default`.
  - Packaging tests updated to the new image: CUDA base, GPU in compose, 16 env names.
- [ ] **Step 2: Run on the PC and see them fail.**
- [ ] **Step 3: Implement. Then on the PC: build the image, run the whole suite, and run `clouder-analyzer score` on one lab
  file.** All three must pass.
- [ ] **Step 4: Commit.** `feat(runner): post light profiles to features route`.

**PR A and ops (controller).**
1. **PR and deploy.** Open the PR and merge it. Deploy with the existing routine (`git archive main` → `~/clouder-analyzer`,
   `docker compose up -d --build`), keeping `LIGHT_PROFILE` unset. The AI pair must keep working: one claim cycle in the
   logs.
2. **Copy the model weights** once, with an alpine container (`lab-data:/lab:ro`, `analyzer-data:/data`):
   - from `/lab/cache/hf/hub/{models--OpenMuQ--MuQ-MuLan-large,models--OpenMuQ--MuQ-large-msd-iter,models--xlm-roberta-base}`
     to `/data/models/hf/hub/`;
   - and `/lab/cache/essentia/{discogs-effnet-bs64-1,genre_discogs400-discogs-effnet-1,msd-musicnn-1}.{pb,json}` to
     `/data/models/essentia/`.
3. **Parity gate.** `parity --hot /lab/ablation/hot/c1.parquet --audio-dir /lab/ablation/c1 --limit 50` and the same for
   `/lab/ablation_more/hot/m01.parquet` with `/lab/ablation_more/m01` must exit 0.
4. **Backfill.** First `profile-dir --limit 5` on `/lab/audio`: the 5 `audio_features` rows and S3 objects are there,
   checked through the RO role and `aws s3 ls`. Then run `profile-dir /lab/audio /lab/ablation /lab/ablation_more`
   detached, a one-off container with `--gpus all` and `lab-data:/lab:ro`. 3 339 unique videos at ~8–12 s each is ~8–11 h.
   - *Ruling vs spec:* audio outside the lab set is left out of the backfill. The claim hands those tracks out early
     (newest first) anyway.
   - **Gate:** `audio_features` count ≥ 3 339 lab videos, and the admin card shows the Profiled count.
5. **Enable the claim.** Set `LIGHT_PROFILE=1` in the PC `.env` (alpine sed) and recreate the container.
   - **Gate:** the first claims post accepted features, the logs show per-track profile time, throughput stays near
     250/h, and there are no `analyzer_error` streaks.

---

## PR 2 — clouder-core: ML worker (branch `feat/ml-worker`, from main after PR 1)

### Task 6: ML core (training, compact heads, prediction, metrics)

**Files:**
- Create: `src/collector/ml/__init__.py`, `src/collector/ml/model.py`, `src/collector/ml/features.py`,
  `src/collector/ml/labels.py`
- Modify: `requirements-dev.in`, `requirements-dev.txt` (add `numpy`, `scikit-learn==1.7.2`), `pyproject.toml` (mypy
  `ignore_missing_imports` for `sklearn.*`)
- Create: `requirements-ml.in` / `requirements-ml.txt` (numpy, scikit-learn==1.7.2, plus whatever the worker's import chain
  needs from `requirements-lambda.in`: pydantic, pydantic-settings, structlog), compiled with the `deps` job's `uv pip
  compile` flags
- Test: `tests/unit/test_ml_model.py`, `tests/unit/test_ml_labels.py`, `tests/unit/test_ml_features.py`

**Interfaces:**
- `labels.Label(track_id: str, video_id: str, keep: bool, category_id: str | None, added_at: datetime)`.
- `labels.training_rows(labels) -> tuple[list[str], np.ndarray, list[str | None]]`:
  - one row per video;
  - drop a video whose tracks disagree on keep or on category;
  - returns (video_ids, keep bool array, category per row).
- `features.vectors(video_ids, fetch: Callable[[str], bytes | None], workers: int = 32) -> tuple[list[str], np.ndarray]`:
  present ids and float32 (n, 16778) from `np.frombuffer(b, "<f2")`. `features.s3_fetcher(s3, bucket)`.
- `model.Head(medians: ndarray[d], weights: ndarray[d, K], bias: ndarray[K], classes: tuple[str, ...])`:
  - `proba(X) -> ndarray[n, K]`;
  - the keep head has K=1 and `classes=("keep",)`, so the column is P(keep) by sigmoid;
  - the category head is softmax over K.
- `model.Model(keep: Head | None, keep_threshold: float | None, category: Head | None, n_labels: int, n_keep: int,
  cv: dict[str, float])`.
- `model.train(X, keep, category, *, blocks=audio_profile.BLOCKS, seed=0) -> Model | None` (None when neither head
  qualifies).
- `model.Prediction(keep_score: float | None, keep: bool | None, categories: list[tuple[str, float]] | None)` and
  `model.predict(model, X) -> list[Prediction]`.
- `model.to_npz(model) -> bytes` / `model.from_npz(data) -> Model`.
- `model.first_button(pred, alive: set[str]) -> str | None` returns `"DISCARD"` or a category id, per the spec §6 lighting
  rule.
- `model.evaluate_previous(preds: list[Prediction], labels: list[Label], alive: set[str]) -> dict`, with keys
  `first_hit, first_n, keep_auc, keep_n, top1, top2, cat_n` (a value is None when its n is 0, or when the AUC has one class).

- [ ] **Step 1: Write the failing tests.** Synthetic data: small blocks such as `(("a",0,8),("b",8,4))`, separable
  Gaussians, n ≈ 200.
  - `test_collapsed_head_matches_pipeline`: `max |Head.proba − pipe.predict_proba| ≤ 1e-5` for both tasks, including a
    column that is NaN in some rows and a constant column.
  - `test_train_none_below_thresholds`: 100 labels, or 2 categories of 29 tracks.
  - `test_category_head_only_classes_with_30`.
  - `test_keep_threshold_matches_share`: the predicted keep share on the train set is within ±0.05 of the label share.
  - `test_npz_roundtrip`.
  - `test_first_button_discard_and_category`.
  - `test_first_button_skips_dead_category`.
  - `test_evaluate_previous_counts`.
  - `test_training_rows_drop_conflicting_video`.
  - `test_vectors_skips_missing`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
  - `fit_pipeline` ports the lab `ablation.pipeline()`, with the grid and constants from the Global Constraints.
  - PCA may be dropped if fits are faster without it. An L2 logistic regression optimum lies in the row space, so
    predictions are the same either way. If you drop it, record that in the report.
  - `collapse` folds imputer statistics, scaler `mean_`/`scale_`, block weights, the PCA (if kept) and `coef_`/`intercept_`
    into `Head`.
  - Keep threshold: `cross_val_predict(LogisticRegression(C=<chosen C>, max_iter=5000), …, cv=StratifiedKFold(3,
    shuffle=True, random_state=0), method="predict_proba")`, then the `1 − mean(keep)` quantile.
- [ ] **Step 4: Run** `pytest tests/unit/test_ml_*.py -q` → PASS, then the whole suite.
- [ ] **Step 5: Commit.** `feat(ml): heads, compact form and metrics`.

### Task 7: ML repository and worker handler

**Files:**
- Create: `src/collector/repositories/ml.py` (`MlMixin`), `src/collector/ml_worker_handler.py`
- Modify: `src/collector/repositories/__init__.py`, `tests/unit/test_repositories_layout.py`, `src/collector/ml_jobs.py`
  (add `enqueue_retrain`, `enqueue_score_style`)
- Test: `tests/db/test_ml_pg.py`, `tests/unit/test_ml_worker_handler.py`

**Interfaces:**
- `MlMixin`. Every method that can return more than 2 000 rows pages with keyset on `track_id` and a limit of 2 000.
  - `ml_labels(*, user_id, style_id, after_track_id=None, limit=2000) -> list[dict]`:
    - rows `{track_id, video_id, keep, category_id, added_at}` per spec §4;
    - joins the track's current matched video (`vendor_track_map`) to `audio_features`;
    - excludes `AI_FLAGGED_SQL`;
    - keep wins; the latest category wins.
  - `ml_style_tracks(*, style_id, after_track_id=None, limit=2000) -> list[dict]`: profiled tracks of the style as
    `{track_id, video_id}`.
  - `ml_tracks_for_videos(*, video_ids) -> list[dict]`: `{track_id, video_id, style_id}`.
  - `ml_model(*, user_id, style_id) -> dict | None` and `ml_models_for_style(*, style_id) -> list[dict]` (version > 0).
  - `ml_alive_categories(*, user_id, style_id) -> list[str]`.
  - `ml_predictions(*, user_id, style_id, track_ids) -> dict[str, dict]`.
  - `ml_save_model(*, user_id, style_id, expected_version: int, n_labels, n_keep, keep_threshold, classes, metrics,
    artifact_key, now) -> bool`: an optimistic `UPDATE … SET version = expected_version + 1 … WHERE version =
    expected_version`, which also clears `retrain_requested_at`.
  - `ml_upsert_predictions(*, user_id, style_id, model_version, rows, now) -> int`:
    - `jsonb_to_recordset`, 200 rows per call;
    - `ON CONFLICT DO UPDATE … WHERE track_predictions.model_version <= EXCLUDED.model_version`.
  - `ml_request_retrain(*, user_id, style_id, now) -> bool`:
    - upserts the row (version 0 if new) and sets `retrain_requested_at = now` unless a request is pending;
    - pending means newer than `trained_at` and less than 1 h old;
    - returns True when the caller should enqueue.
  - `ml_labels_since_training(*, user_id, style_id) -> int`:
    - counts STAGING/DISCARD placements in the user's blocks of the style with `added_at > coalesce(trained_at,
      '-infinity')`;
    - AI-flagged tracks excluded.
- Handler `lambda_handler(event, context)`: for each SQS record, `json.loads(body)` and dispatch on `type`:
  - **`retrain`** `{user_id, style_id}`:
    1. Labels (all pages), then `training_rows`, then `vectors` from S3.
    2. `evaluate_previous` on labels added since the previous `trained_at`, using the stored predictions.
    3. `train`. A `None` result clears `retrain_requested_at` and stops.
    4. Put the artifact at `models/<user>/<style>/v<n>.npz`.
    5. `ml_save_model`, with `metrics = {**evaluate_previous, "cv": model.cv}`.
    6. `enqueue_score_style(user_id, style_id, model_version=n, after_track_id=None)`.
  - **`score_style`** `{user_id, style_id, model_version, after_track_id}`:
    - one page of `ml_style_tracks`, then vectors, then predict, then upsert;
    - enqueues the next page if the page was full;
    - stops when the model row's version has moved past `model_version`.
  - **`score`** `{video_ids}`: tracks for videos, grouped by style; for each model of that style, predict and upsert. Head
    artifacts are cached per container.
  - A bad record raises, so SQS redrives it to the DLQ, as in `auto_enrich_dispatch_handler`.
- Env: `AUDIO_FEATURES_BUCKET`, `ML_JOBS_QUEUE_URL`, plus the Aurora settings.

- [ ] **Step 1: Write the failing tests.**
  - DB:
    - `test_labels_keep_wins_and_latest_category`;
    - `test_labels_exclude_ai_and_auto_buckets`;
    - `test_labels_use_current_video`: a re-matched track to an unprofiled video is absent;
    - `test_labels_paginate`;
    - `test_save_model_optimistic`: a second save with a stale `expected_version` returns False;
    - `test_upsert_never_downgrades_version`;
    - `test_request_retrain_dedupes_within_hour`;
    - `test_labels_since_training_counts_moves`.
  - Handler, with fakes for the repo, S3 and SQS:
    - `test_retrain_too_few_labels_writes_nothing`;
    - `test_retrain_saves_artifact_and_enqueues_scoring`;
    - `test_score_style_pages_and_stops_on_newer_version`;
    - `test_score_new_videos_uses_style_models`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `pytest -q` → PASS.
- [ ] **Step 5: Commit.** `feat(ml): worker for retrain and scoring`.

### Task 8: ML worker infra, packaging and triggers

**Files:**
- Create: `scripts/package_ml_lambda.sh`
  - Builds `dist/ml_worker.zip` from `requirements-ml.txt` + `src/collector`.
  - Deletes `*/tests` directories and `__pycache__`, and uses `deterministic_zip.py`.
  - Fails if the unzipped size is ≥ 240 MB.
- Modify:
  - `infra/lambda.tf`: `aws_lambda_function.ml_worker`, runtime python3.12, handler `collector.ml_worker_handler.lambda_handler`,
    memory 10240, timeout 900; code from `aws_s3_object.ml_worker_zip` (bucket `audio_features`, key
    `lambda/ml_worker.zip`, `source_hash = filemd5(...)`); ESM on `ml_jobs`, batch 1, max concurrency 2.
  - `infra/lambda_roles.tf`: `module.role_ml_worker` with Data API, the DB secret, `s3:GetObject` on `features/*`,
    `s3:GetObject`/`s3:PutObject` on `models/*`, consume `ml_jobs`, send `ml_jobs`.
  - `infra/logging.tf`, `infra/alarms.tf` (DLQ map, errors) and `infra/dashboard.tf`, following the
    `auto_enrich_dispatch_worker` pattern.
  - `.github/workflows/deploy.yml`: run `scripts/package_ml_lambda.sh` next to `package_lambda.sh`, before AWS creds.
  - `.github/workflows/pr.yml`:
    - `deps` also compiles, diffs and audits `requirements-ml.in/.txt`;
    - `terraform` gets the ML zip the same way it gets `collector.zip` (copy that mechanism).
  - Triggers:
    - `src/collector/curation/routes_triage.py`: after finalize, call `ml_request_retrain` and enqueue a retrain if it
      returned True. Best-effort, after `enqueue_block_auto_enrich`.
    - After a successful move or transfer into a STAGING or DISCARD bucket: if `ml_labels_since_training ≥ 150`, request
      and enqueue as above.
    - Both go through one helper, `collector.curation.ml_triggers.after_labels(*, user_id, block_id, finalized: bool)`. It
      gets the repository the same way the route gets its other repositories, and it never raises.
- Test: `tests/unit/test_ml_triggers.py`, the infra guard tests, and a test of `package_ml_lambda.sh`'s size gate if the
  repo tests scripts (check `tests/unit/test_package*.py`).

- [ ] **Step 1: Write the failing tests.**
  - `test_finalize_requests_retrain`;
  - `test_move_into_staging_at_150_requests_retrain`;
  - `test_move_below_150_does_not`;
  - `test_trigger_errors_never_break_move`;
  - the infra guard: ML worker role statements.
- [ ] **Step 2: Implement.** `terraform fmt -check && terraform validate`, plus a local `scripts/package_ml_lambda.sh` run
  for the size printout.
- [ ] **Step 3: Run** `pytest -q` → PASS.
- [ ] **Step 4: Commit.** `feat(ml): worker infra and retrain triggers`.

**PR 2 (controller).**
1. **PR, merge, Deploy.**
2. **First model:** `aws sqs send-message --queue-url <ml-jobs url> --message-body
   '{"type":"retrain","user_id":"<owner>","style_id":"<DnB>"}'`, once the backfill gate has passed. The owner id and the
   DnB style id come from Aurora via the RO secret.
3. **Gates:**
   - the CloudWatch logs show the retrain;
   - `ml_models` has version 1, cv keep AUC ≈ 0.81 and category ≈ 0.69 (a big miss means stop and debug);
   - `track_predictions` covers every profiled DnB track.

---

## PR 3 — clouder-core: API and UI (branch `feat/triage-suggestion-ui`)

### Task 9: Predictions and model in the triage API

**Files:**
- Modify:
  - `src/collector/curation/triage_repository.py`:
    - `list_bucket_tracks` gets `LEFT JOIN track_predictions` on the block's user and style, and `BucketTrackRowOut.prediction`;
    - `_fetch_block_detail` gets the model row, and `TriageBlockRow.model`.
  - `src/collector/curation/routes_triage.py`: the serializers.
  - `scripts/generate_openapi.py`: `BUCKET_TRACK_ROW.prediction`, `TRIAGE_BLOCK_DETAIL.model`. Then regenerate.
- Test: `tests/unit/test_triage_repository.py`, `tests/integration/test_triage_handler.py`, `tests/db/` (a triage case)

**Interfaces:**
- A bucket track row gains `prediction: {keep: bool | null, category_ids: string[]} | null`. `category_ids` is in stored
  order.
- Block detail gains `model: {trained_at: string, n_labels: int, first_hit: float | null, first_n: int} | null`, which is
  null when there is no row or `version = 0`.

- [ ] **Step 1: Write the failing tests.**
  - `test_bucket_tracks_include_own_prediction`;
  - `test_bucket_tracks_never_show_other_users_prediction`;
  - `test_block_detail_model_null_without_model`;
  - `test_block_detail_model_fields`.
- [ ] **Step 2: Implement, regenerate OpenAPI and `schema.d.ts`, then run** `pytest -q` → PASS.
- [ ] **Step 3: Commit.** `feat(triage): expose predictions and model`.

### Task 10: Lit buttons and the model line

**Files:**
- Create: `frontend/src/features/triage/lib/suggestedDestinations.ts` + `__tests__/suggestedDestinations.test.ts`, and
  `frontend/src/features/triage/components/__tests__/SuggestedButtons.browser.test.tsx`
- Modify:
  - triage: `hooks/useBucketTracks.ts` (the `BucketTrack.prediction` type), `hooks/useTriageBlock.ts`
    (`TriageBlock.model`), `components/BucketDistributeButtons.tsx` (prop `suggested?: Suggested`),
    `components/BucketPlayerPanel.tsx`, `components/TriageBlockHeader.tsx`;
  - curate: `components/DestinationGrid.tsx`, `components/DestinationButton.tsx` + `.module.css`,
    `components/CurateSession.tsx`;
  - `frontend/src/i18n/en.json`;
  - demo: `frontend/src/demo/db.ts`, `frontend/src/demo/seed.ts` (a few predictions and a model).

**Interfaces:**
- `type Suggested = { primary: string | null; secondary: string | null }` holds bucket ids.
- `suggestedDestinations(prediction: BucketTrack['prediction'], buckets: TriageBucket[]): Suggested`:
  - **Ranking:** `category_ids` filtered to the ids of active STAGING buckets in `buckets`.
  - **`keep === false`:** primary is the DISCARD bucket, secondary is ranking[0].
  - **Otherwise:** primary is ranking[0], secondary is ranking[1].
  - **No prediction:** both null.
- Renderers light only buttons they actually render.
- Bucket player panel: primary is `variant="filled"` (DISCARD as primary: `filled` red), secondary is `variant="light"` in
  the theme's primary colour, not red.
- Curate: `data-suggested="primary" | "secondary"` on `DestinationButton`, with CSS using the theme's accent tokens.
- Both screens: the lit button's `aria-label` gains `t('triage.suggested.primary_aria')` ("suggested") or
  `secondary_aria` ("second suggestion").
- Model line i18n:
  - `triage.model_line` "Suggestions: model of {{date}} · {{labels}} labels";
  - `triage.model_line_hit` " · first button right {{pct}} %", shown only when `first_n ≥ 20`.

- [ ] **Step 1: Write the failing tests.**
  - `suggestedDestinations` covers six cases:
    - keep → top1 + top2;
    - discard → DISCARD + top1;
    - no keep head → top1 + top2;
    - a deleted category is skipped;
    - no prediction;
    - only one category alive.
  - Component tests for both screens: the right buttons carry the variant or `data-suggested` and the aria text.
  - `TriageBlockHeader`: the line appears with a model, has no hit part when `first_n < 20`, and is absent without a model.
  - Browser test: a filled primary and a light secondary render with different computed backgrounds; DISCARD primary is
    red; the secondary is not red.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.**
  - `cd frontend && pnpm typecheck && pnpm lint && pnpm test` → PASS;
  - `pnpm test:browser` → PASS, with screenshots of both screens at desktop and mobile width.
- [ ] **Step 5: Commit.** `feat(triage): light suggested buttons`.

**PR 3 (controller).**
1. **PR, merge, Deploy.**
2. **Live check:** an open DnB block shows lit buttons on profiled tracks, and the block header shows the model line.
3. **Done:** report the analyzer's first light-profile pass and the backfill counts to the owner.
