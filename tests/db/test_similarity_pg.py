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
