"""Layout of the `light-1` audio profile: 16 778 little-endian float16 per YouTube video.

Stdlib only: the collector zip has no numpy.
"""

from __future__ import annotations

import math
import struct

VERSION = "light-1"
DIMS = 16778
NBYTES = 2 * DIMS

# (name, offset, width)
ARRAYS: tuple[tuple[str, int, int], ...] = (
    ("effnet/discogs400", 0, 400),
    ("effnet/embedding", 400, 1280),
    ("mulan/mix.clips", 1680, 512),
    ("muq/mix.final", 2192, 1024),
    ("muq/mix.layers_1hz", 3216, 13312),
    ("musicnn/embedding", 16528, 200),
    ("musicnn/taggram", 16728, 50),
)

# Model feature blocks (name, offset, width).
BLOCKS = (
    ("effnet", 0, 1680),
    ("mulan", 1680, 512),
    ("muq", 2192, 14336),
    ("musicnn", 16528, 250),
)

_STRUCT = struct.Struct(f"<{DIMS}e")


def decode_vector(data: bytes) -> tuple[float, ...]:
    if len(data) != NBYTES:
        raise ValueError(f"expected {NBYTES} bytes, got {len(data)}")
    values = _STRUCT.unpack(data)
    if not all(math.isfinite(v) for v in values):
        raise ValueError("vector contains NaN or Inf")
    return values


def s3_key(video_id: str) -> str:
    return f"features/{VERSION}/{video_id}.f16"
