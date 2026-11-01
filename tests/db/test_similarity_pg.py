"""Similar tracks on real PostgreSQL + pgvector: the embeddings table, its writes, the ranked reads."""

from __future__ import annotations

import pytest


def _vec(*head: float, dims: int = 256) -> str:
    """A text vector: *head* then zeros."""
    return "[" + ",".join(str(x) for x in (*head, *[0.0] * (dims - len(head)))) + "]"


def test_audio_embeddings_holds_a_256_vector(pg) -> None:
    pg.execute("TRUNCATE audio_embeddings")
    pg.execute(
        "INSERT INTO audio_embeddings (video_id, version, embedding)"
        " VALUES ('v1', 'sim-1', CAST(:v AS vector))",
        {"v": _vec(1.0)},
    )
    (row,) = pg.execute("SELECT embedding <=> embedding AS d FROM audio_embeddings")
    assert row["d"] == 0
    with pytest.raises(Exception):
        pg.execute(
            "INSERT INTO audio_embeddings (video_id, version, embedding)"
            " VALUES ('v2', 'sim-1', CAST(:v AS vector))",
            {"v": _vec(1.0, dims=255)},
        )


@pytest.fixture
def repo(pg):
    from collector.repositories import ClouderRepository

    pg.execute("TRUNCATE audio_embeddings")
    pg.execute("TRUNCATE audio_features")
    yield ClouderRepository(pg)
    pg.execute("TRUNCATE audio_embeddings")
    pg.execute("TRUNCATE audio_features")


def test_similarity_upsert_writes_and_replaces(repo, pg) -> None:
    repo.similarity_upsert(version="sim-1", rows=[("v1", _vec(1.0)), ("v2", _vec(0.0, 1.0))])
    repo.similarity_upsert(version="sim-1", rows=[("v1", _vec(0.0, 0.0, 1.0))])
    rows = pg.execute(
        "SELECT video_id, embedding <=> CAST(:v AS vector) AS d FROM audio_embeddings"
        " WHERE version = 'sim-1' ORDER BY video_id",
        {"v": _vec(0.0, 0.0, 1.0)},
    )
    assert [(r["video_id"], round(r["d"], 6)) for r in rows] == [("v1", 0.0), ("v2", 1.0)]


def test_similarity_videos_pages_by_video_id(repo, pg) -> None:
    for v in ("vc", "va", "vb"):
        pg.execute(
            "INSERT INTO audio_features (video_id, version, audio_sha256, created_at)"
            " VALUES (:v, 'light-1', repeat('a', 64), now())",
            {"v": v},
        )
    assert repo.similarity_videos(after_video_id=None, limit=2) == ["va", "vb"]
    assert repo.similarity_videos(after_video_id="vb", limit=2) == ["vc"]
