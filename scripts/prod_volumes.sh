#!/usr/bin/env bash
# Read-only volume snapshot of the CLOUDER database: aggregates only (count/sum/avg),
# no personal data. Prints sections and saves them to prod_volumes_<timestamp>.txt.
#
#   scripts/prod_volumes.sh                                   # prod Aurora via RDS Data API
#   PSQL_URL=postgresql://postgres:postgres@localhost:5432/postgres scripts/prod_volumes.sh
#                                                             # same SQL against any Postgres
set -uo pipefail

CLUSTER="${CLUSTER:-clouder-prod-aurora}"
OUT="prod_volumes_$(date +%Y%m%d_%H%M).txt"

if [ -z "${PSQL_URL:-}" ]; then
  read -r ARN SECRET DB <<<"$(aws rds describe-db-clusters --db-cluster-identifier "$CLUSTER" \
    --query 'DBClusters[0].[DBClusterArn,MasterUserSecret.SecretArn,DatabaseName]' --output text)"
fi

run() {
  if [ -n "${PSQL_URL:-}" ]; then
    psql "$PSQL_URL" -X -A -F ' | ' -P footer=off -v ON_ERROR_STOP=1 -c "$1"
  else
    aws rds-data execute-statement --resource-arn "$ARN" --secret-arn "$SECRET" --database "$DB" \
      --format-records-as JSON --query formattedRecords --output text --sql "$1"
  fi
}

q() {  # q <title> <sql>; retries while a paused Aurora resumes
  local out i
  for i in 1 2 3 4 5 6; do
    if out=$(run "$2" 2>&1); then printf '\n## %s\n%s\n' "$1" "$out"; return; fi
    case "$out" in
      *DatabaseResumingException*) echo "Aurora is resuming, retrying in 15s..." >&2; sleep 15 ;;
      *) break ;;
    esac
  done
  printf '\n## %s\nFAILED: %s\n' "$1" "$out"
}

{
echo "# CLOUDER volumes — $(date -u +%Y-%m-%dT%H:%MZ)"

q "Canonical catalog" "
SELECT (SELECT count(*) FROM clouder_tracks)        AS tracks,
       (SELECT count(*) FROM clouder_artists)       AS artists,
       (SELECT count(*) FROM clouder_labels)        AS labels,
       (SELECT count(*) FROM clouder_albums)        AS albums,
       (SELECT count(*) FROM clouder_styles)        AS styles,
       (SELECT count(*) FROM clouder_track_artists) AS track_artist_links,
       (SELECT count(*) FROM source_entities)       AS source_entities,
       (SELECT count(*) FROM source_relations)      AS source_relations,
       (SELECT count(*) FROM identity_map)          AS identity_map_rows"

q "Ingest runs" "
SELECT count(*)                                   AS runs,
       count(*) FILTER (WHERE status = 'COMPLETED') AS completed,
       count(*) FILTER (WHERE status = 'FAILED')    AS failed,
       coalesce(sum(item_count), 0)               AS raw_tracks_ingested,
       round(avg(item_count))                     AS avg_tracks_per_run,
       max(item_count)                            AS max_tracks_per_run,
       count(DISTINCT style_id)                   AS styles,
       count(DISTINCT coalesce(week_year, iso_year) || '-' || coalesce(week_number, iso_week)) AS weeks,
       min(period_start)                          AS first_period,
       max(period_end)                            AS last_period,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM finished_at - started_at))::numeric)
                                                  AS p50_ingest_to_canonical_s,
       round(max(extract(epoch FROM finished_at - started_at)))
                                                  AS max_ingest_to_canonical_s
FROM ingest_runs"

q "Last 12 weeks (raw tracks, incl. re-ingests)" "
SELECT coalesce(week_year, iso_year) AS year, coalesce(week_number, iso_week) AS week,
       count(DISTINCT style_id) AS styles, sum(item_count) AS tracks
FROM ingest_runs GROUP BY 1, 2 ORDER BY 1 DESC, 2 DESC LIMIT 12"

q "Track enrichment coverage" "
SELECT count(*)                                           AS tracks,
       count(*) FILTER (WHERE isrc IS NOT NULL)           AS with_isrc,
       count(*) FILTER (WHERE spotify_searched_at IS NOT NULL) AS spotify_searched,
       count(*) FILTER (WHERE spotify_id IS NOT NULL)     AS spotify_matched,
       round(100.0 * count(*) FILTER (WHERE spotify_id IS NOT NULL)
             / nullif(count(*) FILTER (WHERE spotify_searched_at IS NOT NULL), 0), 1) AS spotify_match_pct,
       count(*) FILTER (WHERE release_type IS NOT NULL)   AS with_release_type
FROM clouder_tracks"

q "Identity map by entity and match type" "
SELECT entity_type, match_type, count(*) AS n
FROM identity_map GROUP BY 1, 2 ORDER BY 1, 2"

q "Cross-vendor matches" "
SELECT vendor, match_type, count(*) AS n, round(avg(confidence), 3) AS avg_confidence
FROM vendor_track_map GROUP BY 1, 2 ORDER BY 1, 2"

q "Match review queue" "
SELECT vendor, status, count(*) AS n FROM match_review_queue GROUP BY 1, 2 ORDER BY 1, 2"

q "LLM enrichment (cost_usd = in-app token estimate, not the real bill)" "
SELECT 'label' AS kind, count(*) AS runs,
       coalesce(sum(cells_total), 0) AS cells, coalesce(sum(cells_ok), 0) AS cells_ok,
       coalesce(sum(cells_error), 0) AS cells_error, round(coalesce(sum(cost_usd), 0), 2) AS cost_usd_est,
       (SELECT count(*) FROM clouder_label_info) AS entities_enriched
FROM clouder_label_enrichment_runs
UNION ALL
SELECT 'artist', count(*),
       coalesce(sum(cells_total), 0), coalesce(sum(cells_ok), 0),
       coalesce(sum(cells_error), 0), round(coalesce(sum(cost_usd), 0), 2),
       (SELECT count(*) FROM clouder_artist_info)
FROM clouder_artist_enrichment_runs"

q "Users and curation" "
SELECT (SELECT count(*) FROM users)                                   AS users,
       (SELECT count(*) FROM triage_blocks WHERE deleted_at IS NULL)  AS triage_blocks,
       (SELECT count(*) FROM triage_bucket_tracks)                    AS triage_track_slots,
       (SELECT count(*) FROM categories WHERE deleted_at IS NULL)     AS categories,
       (SELECT count(*) FROM category_tracks)                         AS categorized_tracks,
       (SELECT count(*) FROM playlists WHERE deleted_at IS NULL)      AS playlists,
       (SELECT count(*) FROM playlist_tracks)                         AS playlist_tracks,
       (SELECT count(*) FROM playlists WHERE deleted_at IS NULL
          AND (spotify_playlist_id IS NOT NULL OR ytmusic_playlist_id IS NOT NULL)) AS published_playlists,
       (SELECT count(*) FROM track_tags)                              AS track_tags,
       (SELECT count(*) FROM external_comments)                       AS collected_comments"

q "Recent canonicalization runs" "
SELECT to_char(started_at, 'YYYY-MM-DD HH24:MI') AS started, style_id, item_count AS tracks,
       round(extract(epoch FROM finished_at - started_at))                      AS ingest_to_canonical_s,
       round(extract(epoch FROM finished_at - started_at) * 1000 / nullif(item_count, 0), 1) AS s_per_1k_tracks
FROM ingest_runs WHERE status = 'COMPLETED'
ORDER BY started_at DESC LIMIT 30"

q "Database size" "SELECT pg_size_pretty(pg_database_size(current_database())) AS database_size"

q "Largest tables" "
SELECT relname AS table_name, n_live_tup AS approx_rows,
       pg_size_pretty(pg_total_relation_size(relid)) AS size
FROM pg_stat_user_tables ORDER BY pg_total_relation_size(relid) DESC LIMIT 10"
} | tee "$OUT"

echo
echo "Saved to $OUT"
