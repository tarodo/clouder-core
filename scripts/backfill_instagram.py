"""One-off backfill: fill missing instagram_url for already-enriched entities.

Runs the socials resolver (src/collector/social_links.py) for every
clouder_label_info / clouder_artist_info row whose merged.instagram_url is
empty, and writes ONLY instagram_url (+ provenance socials_tier{N}) back.
Idempotent: the UPDATE re-checks emptiness, so re-runs and races are safe.

Usage:
    PYTHONPATH=src .venv/bin/python scripts/backfill_instagram.py --dry-run --limit 20
    PYTHONPATH=src .venv/bin/python scripts/backfill_instagram.py            # full run

Requires: aws creds (RDS Data API), TAVILY_API_KEY env (or --env-file with a
TAVILY_API_KEY=... line). Read-only unless --dry-run is omitted.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

DEFAULT_CLUSTER_ARN = "arn:aws:rds:us-east-1:223458487728:cluster:clouder-prod-aurora"
DEFAULT_SECRET_ARN = (
    "arn:aws:secretsmanager:us-east-1:223458487728:"
    "secret:rds!cluster-1ebed129-3946-4c55-a18e-72b53364e0e6-pCk4dS"
)

_URL_FIELDS = ("website", "bandcamp_url", "soundcloud_url", "twitter_url",
               "beatport_url", "discogs_url", "residentadvisor_url")

_SELECT = {
    "label": """
        SELECT li.label_id::text AS id, l.name AS name,
               li.merged->>'website' AS website, li.merged->>'bandcamp_url' AS bandcamp_url,
               li.merged->>'soundcloud_url' AS soundcloud_url, li.merged->>'twitter_url' AS twitter_url,
               li.merged->>'beatport_url' AS beatport_url, li.merged->>'discogs_url' AS discogs_url,
               li.merged->>'residentadvisor_url' AS residentadvisor_url,
               coalesce((
                   SELECT s.name FROM clouder_albums a
                   JOIN clouder_tracks t ON t.album_id = a.id
                   JOIN clouder_styles s ON s.id = t.style_id
                   WHERE a.label_id = l.id
                   GROUP BY s.name ORDER BY count(*) DESC LIMIT 1
               ), 'electronic music') AS style
        FROM clouder_label_info li JOIN clouder_labels l ON l.id = li.label_id
        WHERE li.merged->>'instagram_url' IS NULL OR li.merged->>'instagram_url' = ''
        ORDER BY li.updated_at
    """,
    "artist": """
        SELECT ai.artist_id::text AS id, ar.name AS name,
               ai.merged->>'website' AS website, ai.merged->>'bandcamp_url' AS bandcamp_url,
               ai.merged->>'soundcloud_url' AS soundcloud_url, ai.merged->>'twitter_url' AS twitter_url,
               ai.merged->>'beatport_url' AS beatport_url, ai.merged->>'discogs_url' AS discogs_url,
               ai.merged->>'residentadvisor_url' AS residentadvisor_url,
               coalesce((
                   SELECT s.name FROM clouder_track_artists ta
                   JOIN clouder_tracks t ON t.id = ta.track_id
                   JOIN clouder_styles s ON s.id = t.style_id
                   WHERE ta.artist_id = ar.id
                   GROUP BY s.name ORDER BY count(*) DESC LIMIT 1
               ), 'electronic music') AS style
        FROM clouder_artist_info ai JOIN clouder_artists ar ON ar.id = ai.artist_id
        WHERE ai.merged->>'instagram_url' IS NULL OR ai.merged->>'instagram_url' = ''
        ORDER BY ai.updated_at
    """,
}

_UPDATE = {
    "label": """
        UPDATE clouder_label_info
        SET merged = jsonb_set(merged, '{instagram_url}', to_jsonb(:url::text)),
            provenance = jsonb_set(coalesce(provenance, '{}'::jsonb),
                                   '{instagram_url}', to_jsonb(:prov::text)),
            updated_at = now()
        WHERE label_id = :id
          AND (merged->>'instagram_url' IS NULL OR merged->>'instagram_url' = '')
    """,
    "artist": """
        UPDATE clouder_artist_info
        SET merged = jsonb_set(merged, '{instagram_url}', to_jsonb(:url::text)),
            provenance = jsonb_set(coalesce(provenance, '{}'::jsonb),
                                   '{instagram_url}', to_jsonb(:prov::text)),
            updated_at = now()
        WHERE artist_id = :id
          AND (merged->>'instagram_url' IS NULL OR merged->>'instagram_url' = '')
    """,
}


def provenance_label(tier: int | None) -> str:
    return f"socials_tier{tier}" if tier is not None else "socials_regex"


def load_tavily_key(env_file: str | None) -> str:
    key = os.environ.get("TAVILY_API_KEY", "").strip()
    if key:
        return key
    if env_file:
        for line in Path(env_file).read_text().splitlines():
            if line.startswith("TAVILY_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("TAVILY_API_KEY not set (env or --env-file)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="resolve but write nothing")
    parser.add_argument("--limit", type=int, default=None, help="max entities PER KIND")
    parser.add_argument("--kind", choices=["label", "artist"], default=None)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--cluster-arn", default=os.environ.get("CLOUDER_CLUSTER_ARN", DEFAULT_CLUSTER_ARN))
    parser.add_argument("--secret-arn", default=os.environ.get("CLOUDER_SECRET_ARN", DEFAULT_SECRET_ARN))
    parser.add_argument("--database", default="clouder")
    parser.add_argument("--env-file", default="experiments/artists/.env")
    args = parser.parse_args()

    import boto3

    from collector.social_links import SocialsResolver

    tavily_key = load_tavily_key(args.env_file)
    rds = boto3.client("rds-data", region_name="us-east-1")

    def execute(sql: str, params: dict | None = None) -> list[dict]:
        kwargs = dict(
            resourceArn=args.cluster_arn, secretArn=args.secret_arn,
            database=args.database, sql=sql, formatRecordsAs="JSON",
        )
        if params:
            kwargs["parameters"] = [
                {"name": k, "value": {"stringValue": str(v)}} for k, v in params.items()
            ]
        for attempt in range(3):
            try:
                resp = rds.execute_statement(**kwargs)
                return json.loads(resp.get("formattedRecords") or "[]")
            except rds.exceptions.DatabaseResumingException:
                if attempt == 2:
                    raise
                time.sleep(15)
        return []

    kinds = [args.kind] if args.kind else ["label", "artist"]
    resolver = SocialsResolver(tavily_key)
    totals = {"scanned": 0, "found": 0, "written": 0, "errors": 0, "credits": 0}
    tiers: dict[str, int] = {}

    for kind in kinds:
        rows = execute(_SELECT[kind])
        if args.limit:
            rows = rows[: args.limit]
        print(f"== {kind}: {len(rows)} entities without instagram")

        def process(row: dict) -> tuple[dict, object]:
            merged = {f: row.get(f) for f in _URL_FIELDS}
            merged["instagram_url"] = None
            result = resolver.resolve(
                kind=kind, name=row["name"], style=row.get("style") or "electronic music",
                merged=merged,
            )
            return row, result

        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futures = [pool.submit(process, row) for row in rows]
            done = 0
            for fut in as_completed(futures):
                row, result = fut.result()
                done += 1
                totals["scanned"] += 1
                totals["credits"] += result.tavily_credits
                url = result.updates.get("instagram_url")
                if result.error:
                    totals["errors"] += 1
                    print(f"[{done}/{len(rows)}] {kind}:{row['name']} ERR {result.error[:80]}")
                    continue
                if not url:
                    print(f"[{done}/{len(rows)}] {kind}:{row['name']} not found "
                          f"({result.tavily_credits}cr)")
                    continue
                totals["found"] += 1
                prov = provenance_label(result.instagram_tier)
                tiers[prov] = tiers.get(prov, 0) + 1
                if args.dry_run:
                    print(f"[{done}/{len(rows)}] {kind}:{row['name']} -> {url} ({prov}, DRY)")
                    continue
                execute(_UPDATE[kind], {"id": row["id"], "url": url, "prov": prov})
                totals["written"] += 1
                print(f"[{done}/{len(rows)}] {kind}:{row['name']} -> {url} ({prov})")

    cost = totals["credits"] * 0.008
    print(f"\nTOTAL: scanned={totals['scanned']} found={totals['found']} "
          f"written={totals['written']} errors={totals['errors']} "
          f"credits={totals['credits']} (~${cost:.2f}) tiers={tiers}")


if __name__ == "__main__":
    main()
