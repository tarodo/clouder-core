from __future__ import annotations

import pytest

from collector.curation import OrderMismatchError, ValidationError
from collector.curation.categories_service import (
    normalize_category_name,
    validate_category_name,
    validate_reorder_set,
)


# ---- normalize_category_name -----------------------------------------------

def test_normalize_lowercases_and_trims() -> None:
    assert normalize_category_name("  Tech House  ") == "tech house"


def test_normalize_collapses_internal_whitespace() -> None:
    assert normalize_category_name("Tech    House") == "tech house"


def test_normalize_handles_unicode() -> None:
    assert normalize_category_name("Délicat") == "délicat"


def test_normalize_handles_emoji() -> None:
    assert normalize_category_name("Hot 🔥 House") == "hot 🔥 house"


def test_normalize_pure_whitespace_yields_empty() -> None:
    assert normalize_category_name("   \t  ") == ""


# ---- validate_category_name ------------------------------------------------

def test_validate_accepts_normal_name() -> None:
    validate_category_name("Tech House")  # no exception


def test_validate_rejects_empty() -> None:
    with pytest.raises(ValidationError):
        validate_category_name("")


def test_validate_rejects_whitespace_only() -> None:
    with pytest.raises(ValidationError):
        validate_category_name("   ")


def test_validate_rejects_too_long() -> None:
    with pytest.raises(ValidationError):
        validate_category_name("x" * 65)


def test_validate_accepts_64_chars() -> None:
    validate_category_name("x" * 64)


def test_validate_rejects_control_chars() -> None:
    with pytest.raises(ValidationError):
        validate_category_name("Tech\x00House")


def test_validate_rejects_newlines() -> None:
    with pytest.raises(ValidationError):
        validate_category_name("Tech\nHouse")


# ---- validate_reorder_set --------------------------------------------------

def test_reorder_set_passes_on_exact_match() -> None:
    validate_reorder_set(actual={"a", "b", "c"}, requested=["a", "b", "c"])


def test_reorder_set_passes_on_reordered_match() -> None:
    validate_reorder_set(actual={"a", "b", "c"}, requested=["c", "a", "b"])


def test_reorder_set_rejects_missing_id() -> None:
    with pytest.raises(OrderMismatchError):
        validate_reorder_set(actual={"a", "b", "c"}, requested=["a", "b"])


def test_reorder_set_rejects_extra_id() -> None:
    with pytest.raises(OrderMismatchError):
        validate_reorder_set(actual={"a", "b"}, requested=["a", "b", "c"])


def test_reorder_set_rejects_duplicates() -> None:
    with pytest.raises(OrderMismatchError):
        validate_reorder_set(actual={"a", "b"}, requested=["a", "a"])
