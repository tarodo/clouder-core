"""Read-only Spotify matching gold set and its evaluation (offline).

The worker stores every Spotify link the same way (`identity_map.match_type =
'isrc_match'`), so the tier is recovered from the data: the Spotify track's ISRC
equals the catalog's (`isrc`), differs only in the last character (`isrc_neighbour`,
the sibling-ISRC step), or differs entirely (`metadata`, the text-search fallback,
ADR-0006); `no_payload` marks links without a stored Spotify payload. The owner
exports a stratified sample per tier plus searched-but-not-found tracks, labels
them y/n, and `evaluate` turns the labels into precision per tier and a recall
estimate. No Lambda calls this module.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

TIERS = ("isrc", "isrc_neighbour", "metadata", "no_payload")

_ARTISTS = """(SELECT COALESCE(STRING_AGG(DISTINCT a.name, ', ' ORDER BY a.name), '')
                 FROM clouder_track_artists cta JOIN clouder_artists a ON a.id = cta.artist_id
                WHERE cta.track_id = {t}.track_id) AS artist_names"""

_MATCHES_SQL = """
WITH m AS (
    SELECT t.id AS track_id, t.isrc, t.title, t.length_ms, t.spotify_id,
           se.payload->>'name' AS spotify_title,
           se.payload->'external_ids'->>'isrc' AS spotify_isrc,
           (se.payload->>'duration_ms')::bigint AS spotify_duration_ms,
           (SELECT STRING_AGG(a->>'name', ', ') FROM jsonb_array_elements(se.payload->'artists') a)
               AS spotify_artists,
           CASE WHEN se.payload IS NULL THEN 'no_payload'
                WHEN upper(se.payload->'external_ids'->>'isrc') = upper(t.isrc) THEN 'isrc'
                WHEN left(upper(se.payload->'external_ids'->>'isrc'), -1) = left(upper(t.isrc), -1)
                    THEN 'isrc_neighbour'
                ELSE 'metadata' END AS tier
    FROM clouder_tracks t
    LEFT JOIN source_entities se
      ON se.source = 'spotify' AND se.entity_type = 'track' AND se.external_id = t.spotify_id
    WHERE t.spotify_id IS NOT NULL
), ranked AS (
    SELECT m.*, row_number() OVER (PARTITION BY tier ORDER BY md5(track_id)) AS rn,
           count(*) OVER (PARTITION BY tier) AS population
    FROM m
)
SELECT r.track_id, r.isrc, r.title, r.length_ms, r.spotify_id, r.spotify_title, r.spotify_isrc,
       r.spotify_duration_ms, r.spotify_artists, r.tier, r.population, """ + _ARTISTS.format(t="r") + """
FROM ranked r WHERE rn <= :n
ORDER BY tier, rn
"""

_NOT_FOUND_SQL = """
SELECT s.*, """ + _ARTISTS.format(t="s") + """
FROM (
    SELECT t.id AS track_id, t.isrc, t.title, count(*) OVER () AS population
    FROM clouder_tracks t
    WHERE t.spotify_searched_at IS NOT NULL AND t.spotify_id IS NULL
    ORDER BY md5(t.id)
    LIMIT :n
) s
"""


def export_gold(client: Any, per_tier: int) -> list[dict[str, Any]]:
    population: dict[str, Any] = {"kind": "population", **dict.fromkeys(TIERS, 0), "not_found": 0}
    records: list[dict[str, Any]] = []
    for row in client.execute(_MATCHES_SQL, {"n": per_tier}):
        population[row["tier"]] = int(row["population"])
        records.append({
            "kind": "match",
            "tier": row["tier"],
            "track_id": row["track_id"],
            "isrc": row["isrc"],
            "artist": row["artist_names"],
            "title": row["title"],
            "length_ms": row["length_ms"],
            "spotify_id": row["spotify_id"],
            "spotify_url": f"https://open.spotify.com/track/{row['spotify_id']}",
            "spotify_title": row["spotify_title"],
            "spotify_artists": row["spotify_artists"] or "",
            "spotify_isrc": row["spotify_isrc"],
            "spotify_duration_ms": row["spotify_duration_ms"],
        })
    for row in client.execute(_NOT_FOUND_SQL, {"n": per_tier}):
        population["not_found"] = int(row["population"])
        records.append({
            "kind": "not_found",
            "track_id": row["track_id"],
            "isrc": row["isrc"],
            "artist": row["artist_names"],
            "title": row["title"],
            "search_url": "https://open.spotify.com/search/" + quote(f"{row['artist_names']} {row['title']}"),
        })
    return [*records, population]


def evaluate(records: list[Mapping[str, Any]], labels: Mapping[str, bool]) -> dict[str, Any]:
    """Labels: True = a correct match, or truly absent from Spotify; False = wrong, or missed."""
    population = next(r for r in records if r["kind"] == "population")
    tiers = {}
    for tier in TIERS:
        got = [labels[r["track_id"]] for r in records
               if r["kind"] == "match" and r["tier"] == tier and r["track_id"] in labels]
        tiers[tier] = {
            "labelled": len(got),
            "correct": sum(got),
            "precision": sum(got) / len(got) if got else None,
            "population": population.get(tier, 0),
        }
    misses = [labels[r["track_id"]] for r in records if r["kind"] == "not_found" and r["track_id"] in labels]
    missed = (len(misses) - sum(misses)) / len(misses) * population["not_found"] if misses else None
    # ponytail: tiers without labels are left out of the found count, so the recall
    # estimate leans low until every tier is labelled.
    found = sum(t["precision"] * t["population"] for t in tiers.values() if t["precision"] is not None)
    recall = found / (found + missed) if missed is not None and found + missed else None
    return {"tiers": tiers, "missed_estimate": missed, "recall_estimate": recall}


def render_report(result: Mapping[str, Any]) -> str:
    lines = ["| Tier | Population | Labelled | Correct | Precision |", "|---|---|---|---|---|"]
    for tier, t in result["tiers"].items():
        precision = f"{t['precision']:.1%}" if t["precision"] is not None else "—"
        lines.append(f"| {tier} | {t['population']} | {t['labelled']} | {t['correct']} | {precision} |")
    if result["recall_estimate"] is None:
        lines.append("\nRecall: label the not-found sample and at least one tier.")
    else:
        lines.append(f"\nEstimated missed tracks: {result['missed_estimate']:.0f}; "
                     f"recall ≈ {result['recall_estimate']:.1%}.")
    return "\n".join(lines) + "\n"
