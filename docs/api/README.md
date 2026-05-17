# API

HTTP contract for the CLOUDER API.

- [openapi.yaml](openapi.yaml) — OpenAPI 3.1 spec. Import into Postman / Swagger UI / Insomnia.
- [Auth flow](auth-flow.md) — Spotify OAuth redirect, refresh-token rotation, replay detection.

Regenerate `openapi.yaml` with `PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py` after editing `scripts/generate_openapi.py:ROUTES`. Run `pnpm api:types` in `frontend/` to refresh the generated TypeScript types.
