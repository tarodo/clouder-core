from __future__ import annotations

import math
import struct

import pytest

from collector import audio_profile as ap


def test_layout_is_contiguous() -> None:
    pos = 0
    for _name, off, width in ap.ARRAYS:
        assert off == pos
        pos += width
    assert pos == ap.DIMS == 16778
    assert ap.NBYTES == 2 * ap.DIMS


def test_blocks_cover_arrays() -> None:
    assert ap.BLOCKS[0][1] == 0
    for (_, off, width), (_, nxt, _w) in zip(ap.BLOCKS, ap.BLOCKS[1:], strict=False):
        assert off + width == nxt
    assert ap.BLOCKS[-1][1] + ap.BLOCKS[-1][2] == ap.DIMS
    arr_ends = {off + w for _n, off, w in ap.ARRAYS}
    assert {off + w for _n, off, w in ap.BLOCKS} <= arr_ends


def test_decode_roundtrip() -> None:
    vals = [float(i % 7) / 4 for i in range(ap.DIMS)]
    assert ap.decode_vector(struct.pack("<16778e", *vals)) == tuple(vals)


def test_decode_rejects_wrong_length() -> None:
    with pytest.raises(ValueError):
        ap.decode_vector(b"\x00" * (ap.NBYTES - 2))


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_decode_rejects_nan_and_inf(bad: float) -> None:
    vals = [0.0] * ap.DIMS
    vals[5] = bad
    with pytest.raises(ValueError):
        ap.decode_vector(struct.pack("<16778e", *vals))


def test_s3_key() -> None:
    assert ap.s3_key("abc") == "features/light-1/abc.f16"
