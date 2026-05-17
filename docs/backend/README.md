# Backend

Lambda runtimes, vendor integrations, and the data-access layer.

- [Handlers](handlers.md) — entry points: API, worker, search, spotify, vendor_match, migration.
- [Vendor providers](providers.md) — Protocol pattern, `VENDORS_ENABLED`, adding a vendor.
- [RDS Data API](data-api.md) — `DataAPIClient`, retry policy, transactions, `find_identity`.
- [Testing](testing.md) — pytest setup, `FakeDataAPI`, what it misses.
- [Gotchas](gotchas.md) — backend-only sharp edges.

See also [`docs/architecture.md`](../architecture.md), [`docs/adr/`](../adr/).
