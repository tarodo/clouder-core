"""export_aurora on real PostgreSQL: every owned and child row of the user, nobody else's."""

from __future__ import annotations

import uuid

from test_user_deletion_pg import _CATALOG, _OWNED, _cleanup, _seed_user

from collector.user_deletion import delete_user
from collector.user_export import export_aurora, resolve_catalog


def test_exports_every_owned_table_and_nothing_of_others(pg) -> None:
    for sql in _CATALOG:
        pg.execute(sql)
    me, other = str(uuid.uuid4()), str(uuid.uuid4())
    _seed_user(pg, me, "a_")
    _seed_user(pg, other, "b_")
    try:
        out = export_aurora(pg, me)
        catalog = resolve_catalog(pg, out)
    finally:
        delete_user(pg, me)
        delete_user(pg, other)
        _cleanup(pg, ["a_", "b_"])

    assert {t: len(out.get(t, [])) for t in _OWNED} == _OWNED
    flat = [row for rows in out.values() for row in rows]
    assert not any(other in str(v) for row in flat for v in row.values())
    (token,) = out["user_vendor_tokens"]
    assert token["access_token_enc"] == token["data_key_enc"] == "[redacted]"
    (session,) = out["user_sessions"]
    assert session["refresh_token_hash"] == "[redacted]"
    assert "clouder_label_enrichment_runs.created_by_user_id" in out
    assert catalog["tracks"]["tr"]["title"] == "T"
    assert catalog["styles"]["st"] == "Techno"
    assert catalog["artists"] == {"ar": "A"} and catalog["labels"] == {"lb": "L"}
