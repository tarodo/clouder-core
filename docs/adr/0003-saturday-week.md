# ADR-0003: Saturday-week as canonical period
Status: Accepted
Date: 2026-05-17

## Context

Beatport publishes new releases on a rolling weekly basis, and the admin workflow groups ingests by "week" — typically the DJ promo window. The natural question is which week-numbering system to use.

ISO 8601 week numbering (Monday-to-Sunday, week 1 = the week containing the first Thursday of the year) is widely supported by programming languages and databases. However, it has two properties that work against the Beatport use case. First, ISO weeks start on Monday, but Beatport's release cycle aligns to Saturday: new promos drop on Saturdays and the window closes on Friday. Second, ISO weeks that span a year boundary belong to the year containing the majority of days, which causes counter-intuitive labelling (e.g. January 1 can belong to week 52 of the previous year).

The team decided to define a custom week convention that mirrors the actual release cycle: each week runs Saturday-to-Friday inclusive. This also simplifies the mapping from "which week did this track appear?" to "which admin ingest should I look at?" — the answer is always the Saturday of that week.

Days before the first Saturday of a year (January 1 through the Friday immediately preceding the first Saturday) are assigned to the last week of the prior year, keeping the week sequence contiguous across the year boundary.

This convention is implemented once in `src/collector/saturday_week.py` and mirrored in the frontend at `frontend/src/features/admin/lib/saturdayWeek.ts`. The two implementations are the authoritative sources; do not derive week numbers elsewhere.

## Decision

Weekly periods are defined Saturday-to-Friday inclusive. Week 1 begins on the first Saturday on or after January 1. Days before the first Saturday belong to the previous year's last week. ISO weeks are not used.

## Consequences

- `ingest_runs` stores `week_year` and `week_number` (Saturday-week) for new runs. The legacy `iso_year` / `iso_week` columns are kept for backward compatibility but are null on all new records.
- `POST /collect_bp_releases` (deprecated) still accepts `iso_year` + `iso_week` and maps them via `compute_iso_week_date_range`. All new ingest entry points use the Saturday-week path (`POST /admin/beatport/ingest`).
- The admin UI exclusively displays and accepts `week_year` / `week_number`. The week picker computes ranges using `saturdayWeek.ts`.
- A year can have 52 or 53 weeks depending on where the first Saturday falls. `weeks_in_year(year)` returns the count.
- Developers accustomed to ISO weeks may be surprised that `week_of_date(date(2026, 1, 1))` returns `(2025, 53)` if January 1 is a Thursday — it belongs to the last week of 2025 under this convention.

**Cross-references:** `../data/raw-ingestion.md`.
