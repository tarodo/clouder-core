"""ClouderRepository is a facade over one module per aggregate; its API is unchanged."""

from __future__ import annotations

from pathlib import Path

PKG = Path(__file__).resolve().parents[2] / "src" / "collector" / "repositories"

API = [
    "analytics_funnel",
    "batch_conservative_update_tracks",
    "batch_create_albums",
    "batch_create_artists",
    "batch_create_labels",
    "batch_create_styles",
    "batch_create_tracks",
    "batch_update_spotify_results",
    "batch_upsert_identities",
    "batch_upsert_source_entities",
    "batch_upsert_source_relations",
    "batch_upsert_track_artists",
    "claim_identities",
    "claim_tracks_for_spotify_search",
    "count_albums",
    "count_artists",
    "count_spotify_pending_in_range",
    "count_tracks",
    "count_tracks_not_found_on_spotify",
    "coverage_for_year",
    "create_ingest_run",
    "find_identities",
    "find_tracks_needing_spotify_search",
    "find_tracks_not_found_on_spotify",
    "get_run",
    "get_vendor_blocked_until",
    "get_vendor_match",
    "insert_review_candidate",
    "list_albums",
    "list_artists",
    "list_replayable_runs",
    "list_runs_for_cell",
    "list_tracks",
    "list_users",
    "mark_no_match",
    "propagate_release_type_to_albums",
    "read_track_state",
    "release_spotify_search_claim",
    "reset_spotify_not_found",
    "set_run_completed",
    "set_run_failed",
    "set_style_hidden",
    "set_vendor_blocked_until",
    "spotify_search_counts",
    "spotify_stats_for_year",
    "transaction",
    "upsert_identity",
    "upsert_source_entity",
    "upsert_source_relation",
    "upsert_track_artist",
    "upsert_vendor_match",
]

AGGREGATES = {
    "collector.repositories.runs",
    "collector.repositories.lineage",
    "collector.repositories.catalog_writes",
    "collector.repositories.spotify",
    "collector.repositories.vendor_match",
    "collector.repositories.api_views",
}


def test_facade_keeps_its_api() -> None:
    from collector.repositories import ClouderRepository

    assert sorted(n for n in dir(ClouderRepository) if not n.startswith("_")) == API


def test_each_method_lives_in_an_aggregate_module() -> None:
    from collector.repositories import ClouderRepository

    homes = {getattr(ClouderRepository, n).__module__ for n in API if n != "transaction"}
    assert homes == AGGREGATES


def test_aggregate_modules_stay_small() -> None:
    modules = list(PKG.glob("*.py"))
    assert modules, "collector/repositories/ is not a package"
    for module in modules:
        assert len(module.read_text().splitlines()) <= 600, module.name
