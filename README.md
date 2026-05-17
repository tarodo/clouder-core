# CLOUDER

> A weekly track-curation tool for a small circle of DJs.

CLOUDER pulls fresh weekly releases from Beatport into your personal canonical library, lets you triage them with one keystroke, and ships the keepers straight into Spotify-ready playlists you can play in the browser.

**Who it's for.** DJs who buy or audition new releases every week and need a fast, repeatable workflow from "what came out this week" to "what's going into the set."

## Features

- **Weekly automated ingest** from Beatport into a personal canonical catalogue.
- **Tap-to-curate workflow** — one key per destination playlist, optimistic shrinks the queue.
- **In-browser playback** via the Spotify Web Playback SDK, keyboard-first hotkeys.
- **AI-assisted screening** — labels and artists are checked for AI-generated content and flagged.
- **Per-DJ playlists and tags** layered on a shared canonical catalogue.

---

## For developers

CLOUDER is a serverless ingest pipeline (Lambda + S3 + SQS + Aurora PostgreSQL) plus a React 19 SPA. The backend is Python; the frontend is Mantine 9 + react-router 7. Infrastructure is Terraform.

**Start here:**

- **System overview** — [`docs/architecture.md`](docs/architecture.md)
- **Architecture decisions** — [`docs/adr/`](docs/adr/)

**By role:**

- Backend / API / worker dev — [`docs/backend/`](docs/backend/)
- Data engineer — [`docs/data/`](docs/data/)
- Frontend dev — [`docs/frontend/`](docs/frontend/)
- Ops / SRE — [`docs/ops/`](docs/ops/)
- API consumer — [`docs/api/`](docs/api/)

**Local quickstart:**

```bash
python -m pip install -r requirements-dev.txt
pytest -q
```

For the SPA: see [`frontend/README.md`](frontend/README.md).
For deployment: see [`docs/ops/deploy.md`](docs/ops/deploy.md).

## License

Private — internal use only.
