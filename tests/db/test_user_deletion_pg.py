"""delete_user against real Postgres: nothing of the user survives, nobody else is touched."""

from __future__ import annotations

import uuid

from collector.user_deletion import delete_user

_CATALOG = [
    "INSERT INTO clouder_styles (id, name, normalized_name, created_at, updated_at)"
    " VALUES ('st', 'Techno', 'techno', now(), now())",
    "INSERT INTO clouder_tracks (id, title, normalized_title, style_id, created_at, updated_at)"
    " VALUES ('tr', 'T', 't', 'st', now(), now())",
    "INSERT INTO clouder_artists (id, name, normalized_name, created_at, updated_at)"
    " VALUES ('ar', 'A', 'a', now(), now())",
    "INSERT INTO clouder_labels (id, name, normalized_name, created_at, updated_at)"
    " VALUES ('lb', 'L', 'l', now(), now())",
]

# One row per user-owned table and per child table; ids are prefixed with :p.
_USER_ROWS = [
    "INSERT INTO users (id, spotify_id, display_name, email, created_at, updated_at)"
    " VALUES (:uid, :p || 'sp', 'Name', :p || '@example.com', now(), now())",
    "INSERT INTO categories (id, user_id, style_id, name, normalized_name, created_at, updated_at)"
    " VALUES (:p || 'cat', :uid, 'st', 'C', 'c', now(), now())",
    "INSERT INTO category_tracks (category_id, track_id, added_at) VALUES (:p || 'cat', 'tr', now())",
    "INSERT INTO triage_blocks (id, user_id, style_id, name, date_from, date_to, created_at, updated_at)"
    " VALUES (:p || 'blk', :uid, 'st', 'B', '2026-01-03', '2026-01-09', now(), now())",
    "INSERT INTO triage_buckets (id, triage_block_id, bucket_type, category_id, created_at)"
    " VALUES (:p || 'bkt', :p || 'blk', 'STAGING', :p || 'cat', now())",
    "INSERT INTO triage_bucket_tracks (triage_bucket_id, track_id, added_at)"
    " VALUES (:p || 'bkt', 'tr', now())",
    "INSERT INTO playlists (id, user_id, name, normalized_name, created_at, updated_at)"
    " VALUES (:p || 'pl', :uid, 'P', 'p', now(), now())",
    "INSERT INTO playlist_tracks (playlist_id, track_id, position, added_at)"
    " VALUES (:p || 'pl', 'tr', 0, now())",
    "INSERT INTO user_tags (id, user_id, name, normalized_name, created_at, updated_at)"
    " VALUES (:p || 'tag', :uid, 'G', 'g', now(), now())",
    "INSERT INTO track_tags (user_id, track_id, tag_id, created_at) VALUES (:uid, 'tr', :p || 'tag', now())",
    "INSERT INTO user_imported_tracks (user_id, track_id, imported_at) VALUES (:uid, 'tr', now())",
    "INSERT INTO user_sessions (id, user_id, refresh_token_hash, created_at, last_used_at, expires_at)"
    " VALUES (:p || 'ses', :uid, :p || 'hash', now(), now(), now())",
    "INSERT INTO user_vendor_tokens (user_id, vendor, access_token_enc, data_key_enc, updated_at)"
    " VALUES (:uid, 'spotify', '\\x00', '\\x00', now())",
    "INSERT INTO clouder_user_artist_prefs (user_id, artist_id, status, updated_at)"
    " VALUES (:uid, 'ar', 'liked', now())",
    "INSERT INTO clouder_user_label_prefs (user_id, label_id, status, updated_at)"
    " VALUES (:uid, 'lb', 'disliked', now())",
    "INSERT INTO clouder_user_style_prefs (user_id, style_id, position, updated_at)"
    " VALUES (:uid, 'st', 0, now())",
    "INSERT INTO clouder_label_enrichment_runs (id, prompt_slug, prompt_version, vendors, models,"
    " merge_vendor, merge_model, requested_labels, cells_total, created_at, created_by_user_id)"
    " VALUES (:p || 'lrun', 's', 'v', '[]', '{}', 'm', 'm', 0, 0, now(), :uid)",
    "INSERT INTO clouder_artist_enrichment_runs (id, prompt_slug, prompt_version, vendors, models,"
    " merge_vendor, merge_model, requested_artists, cells_total, created_at, created_by_user_id)"
    " VALUES (:p || 'arun', 's', 'v', '[]', '{}', 'm', 'm', 0, 0, now(), :uid)",
    "INSERT INTO auto_enrich_config (kind, updated_at, updated_by_user_id)"
    " VALUES (:p || 'kind', now(), :uid)",
]
_AUDIT_ROWS = {  # rows that outlive the user, with the audit column set to NULL
    "clouder_label_enrichment_runs": ("created_by_user_id", "lrun"),
    "clouder_artist_enrichment_runs": ("created_by_user_id", "arun"),
    "auto_enrich_config": ("updated_by_user_id", "kind"),
}
_OWNED = {  # table -> rows deleted per user
    "users": 1,
    "categories": 1,
    "category_tracks": 1,
    "triage_blocks": 1,
    "triage_buckets": 1,
    "triage_bucket_tracks": 1,
    "playlists": 1,
    "playlist_tracks": 1,
    "user_tags": 1,
    "track_tags": 1,
    "user_imported_tracks": 1,
    "user_sessions": 1,
    "user_vendor_tokens": 1,
    "clouder_user_artist_prefs": 1,
    "clouder_user_label_prefs": 1,
    "clouder_user_style_prefs": 1,
}


def _seed_user(pg, uid: str, prefix: str) -> None:
    for sql in _USER_ROWS:
        pg.execute(sql, {"uid": uid, "p": prefix})


def _seed_singleton_audit(pg, uid: str) -> None:
    pg.execute(
        "INSERT INTO auto_ingest_settings (id, updated_by_user_id) VALUES (1, :uid)"
        " ON CONFLICT (id) DO UPDATE SET updated_by_user_id = EXCLUDED.updated_by_user_id",
        {"uid": uid},
    )


def _count(pg, table: str) -> int:
    return pg.execute(f'SELECT count(*) AS n FROM "{table}"')[0]["n"]


def _user_columns(pg) -> list[tuple[str, str]]:
    rows = pg.execute(
        "SELECT table_name::text AS t, column_name::text AS c FROM information_schema.columns"
        " WHERE table_schema = 'public' AND column_name ~ 'user_id$'"
    )
    return [(r["t"], r["c"]) for r in rows]


def _holding(pg, uid: str) -> list[str]:
    return [
        f"{t}.{c}"
        for t, c in _user_columns(pg)
        if pg.execute(f'SELECT count(*) AS n FROM "{t}" WHERE "{c}" = :u', {"u": uid})[0]["n"]
    ]


def _cleanup(pg, prefixes: list[str]) -> None:
    for table, (_, suffix) in _AUDIT_ROWS.items():
        key = "kind" if table == "auto_enrich_config" else "id"
        for p in prefixes:
            pg.execute(f'DELETE FROM "{table}" WHERE "{key}" = :k', {"k": p + suffix})


def test_delete_user_leaves_nothing(pg) -> None:
    alice, bob = str(uuid.uuid4()), str(uuid.uuid4())
    for sql in _CATALOG:
        pg.execute(sql)
    _seed_user(pg, alice, "a-")
    _seed_user(pg, bob, "b-")
    _seed_singleton_audit(pg, alice)
    try:
        # The seed covers every column that holds a user id: a new one fails here first.
        every_column = {f"{t}.{c}" for t, c in _user_columns(pg)}
        assert set(_holding(pg, alice)) == every_column
        bob_columns = set(_holding(pg, bob))

        dry = delete_user(pg, alice, dry_run=True)
        assert set(_holding(pg, alice)) == every_column, "dry run must roll back"

        result = delete_user(pg, alice)

        assert result == dry
        assert _holding(pg, alice) == []
        assert {k: v for k, v in result.items() if "." not in k} == _OWNED
        assert {k for k in result if "." in k} == {
            f"{t}.{c}" for t, (c, _) in _AUDIT_ROWS.items()
        } | {"auto_ingest_settings.updated_by_user_id"}
        for table, n in _OWNED.items():
            assert _count(pg, table) == n, table  # bob's rows only
        for table, (col, suffix) in _AUDIT_ROWS.items():
            key = "kind" if table == "auto_enrich_config" else "id"
            row = pg.execute(
                f'SELECT "{col}" AS u FROM "{table}" WHERE "{key}" = :k', {"k": "a-" + suffix}
            )
            assert row == [{"u": None}], table  # the audited row stays, anonymised
        assert set(_holding(pg, bob)) == bob_columns
        assert delete_user(pg, alice) == {}
    finally:
        delete_user(pg, alice)
        delete_user(pg, bob)
        _cleanup(pg, ["a-", "b-"])
