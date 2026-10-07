"""Contract for raw Beatport track records (docs/data/contracts.md).

The contract is data: every known top-level field with its allowed JSON types,
the fields a record cannot be canonicalized without, and how empty the fields
canonicalization relies on may get per run. `screen` splits a run into records
to canonicalize and records to quarantine, and reports drift: unknown, missing,
re-typed or suddenly empty fields. A new upstream field is acknowledged by
adding it here.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Sequence

from .logging_utils import log_event

_S, _I, _B, _O, _A, _N = "string", "integer", "boolean", "object", "array", "null"

# Field -> allowed JSON types; measured over the raw zone on 2026-10-07.
FIELDS: dict[str, frozenset[str]] = {
    "id": frozenset({_I}),
    "name": frozenset({_S}),
    "mix_name": frozenset({_S, _N}),
    "isrc": frozenset({_S, _N}),
    "bpm": frozenset({_I, _N}),
    "length_ms": frozenset({_I, _N}),
    "length": frozenset({_S, _N}),
    "publish_date": frozenset({_S, _N}),
    "new_release_date": frozenset({_S, _N}),
    "key": frozenset({_O, _N}),
    "artists": frozenset({_A}),
    "remixers": frozenset({_A}),
    "bsrc_remixer": frozenset({_A}),
    "release": frozenset({_O}),
    "genre": frozenset({_O}),
    "sub_genre": frozenset({_O, _N}),
    "available_worldwide": frozenset({_B}),
    "exclusive": frozenset({_B}),
    "is_available_for_streaming": frozenset({_B}),
    "is_dj_edit": frozenset({_B}),
    "is_dj_version": frozenset({_B}),  # appeared upstream between 2026-07-20 and 2026-09-13
    "is_explicit": frozenset({_B}),
    "is_hype": frozenset({_B}),
    "is_ugc_remix": frozenset({_B}),
    "pre_order": frozenset({_B}),
    "pre_order_date": frozenset({_S, _N}),
    "free_downloads": frozenset({_A}),
    "free_download_start_date": frozenset({_S, _N}),
    "free_download_end_date": frozenset({_S, _N}),
    "catalog_number": frozenset({_S, _N}),
    "label_track_identifier": frozenset({_S, _N}),
    "current_status": frozenset({_O, _N}),
    "encoded_date": frozenset({_S, _N}),
    "image": frozenset({_O, _N}),
    "price": frozenset({_O, _N}),
    "publish_status": frozenset({_S, _N}),
    "sale_type": frozenset({_O, _N}),
    "sample_end_ms": frozenset({_I, _N}),
    "sample_start_ms": frozenset({_I, _N}),
    "sample_url": frozenset({_S, _N}),
    "slug": frozenset({_S, _N}),
    "url": frozenset({_S, _N}),
}

# Without these a record cannot become a canonical track (normalize's rule).
REQUIRED = frozenset({"id", "name"})

# Fields canonicalization relies on: share of NULLs per run above which the run drifts.
NULL_SHARE_LIMITS: dict[str, float] = {
    "isrc": 0.01,
    "bpm": 0.01,
    "length_ms": 0.01,
    "key": 0.01,
    "publish_date": 0.01,
}

# Known fields expected on every record; is_dj_version is absent from data before 2026-09.
ALWAYS_PRESENT = frozenset(FIELDS) - {"is_dj_version"}


@dataclass(frozen=True)
class ContractReport:
    valid: list[dict[str, Any]]
    quarantined: list[dict[str, Any]]
    unknown_fields: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    type_drift: dict[str, int] = field(default_factory=dict)
    null_share_over: dict[str, float] = field(default_factory=dict)

    @property
    def drift_fields(self) -> tuple[str, ...]:
        return tuple(sorted(
            set(self.unknown_fields) | set(self.missing_fields)
            | set(self.type_drift) | set(self.null_share_over)
        ))


def json_type(value: Any) -> str:
    if value is None:
        return _N
    if isinstance(value, bool):
        return _B
    if isinstance(value, int):
        return _I
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return _S
    if isinstance(value, list):
        return _A
    if isinstance(value, dict):
        return _O
    return type(value).__name__


def _required_violations(record: Any) -> list[str]:
    if not isinstance(record, dict):
        return ["record: not an object"]
    reasons = []
    rid = record.get("id")
    if not (isinstance(rid, int) and not isinstance(rid, bool) and rid > 0):
        reasons.append("id: not a positive integer")
    name = record.get("name")
    if not (isinstance(name, str) and name.strip()):
        reasons.append("name: empty")
    return reasons


def screen(records: Sequence[Any]) -> ContractReport:
    """Split a run into records to canonicalize and records to quarantine, and
    report how the run drifts from the contract."""
    valid: list[dict[str, Any]] = []
    quarantined: list[dict[str, Any]] = []
    seen: Counter[str] = Counter()
    nulls: Counter[str] = Counter()
    retyped: Counter[str] = Counter()
    for record in records:
        reasons = _required_violations(record)
        if reasons:
            quarantined.append({"reasons": reasons, "record": record})
            continue
        valid.append(record)
        for key, value in record.items():
            seen[key] += 1
            kind = json_type(value)
            if kind == _N:
                nulls[key] += 1
            allowed = FIELDS.get(key)
            if allowed is not None and kind not in allowed:
                retyped[key] += 1
    n = len(valid)
    if not n:
        return ContractReport(valid=valid, quarantined=quarantined)
    shares = {f: round(nulls[f] / n, 4) for f in NULL_SHARE_LIMITS}
    return ContractReport(
        valid=valid,
        quarantined=quarantined,
        unknown_fields=tuple(sorted(k for k in seen if k not in FIELDS)),
        # `f in FIELDS` keeps a narrowed contract (tests, the audit's --without) consistent.
        missing_fields=tuple(sorted(f for f in ALWAYS_PRESENT if f in FIELDS and not seen[f])),
        type_drift=dict(sorted(retyped.items())),
        null_share_over={f: s for f, s in shares.items() if s > NULL_SHARE_LIMITS[f]},
    )


def screen_run(
    raw_tracks: Sequence[Any],
    *,
    run_id: str,
    storage: Any,
    write: bool,
    correlation_id: str | None = None,
) -> ContractReport:
    """Screen one run: quarantine what cannot be canonicalized (unless a dry run)
    and log drift once, so a metric filter can alarm on it."""
    report = screen(raw_tracks)
    if write and report.quarantined:
        storage.write_quarantine(run_id, report.quarantined)
    if report.drift_fields:
        log_event(
            "WARNING",
            "contract_drift",
            correlation_id=correlation_id,
            run_id=run_id,
            drift_fields=",".join(report.drift_fields),
            unknown_fields=",".join(report.unknown_fields),
            count=len(report.drift_fields),
        )
    return report
