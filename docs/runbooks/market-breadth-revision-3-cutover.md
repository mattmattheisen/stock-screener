# Market breadth revision 3 cutover

This runbook replaces all revision-2 breadth history with the revision-3 dataset built from fixed local-market StockBee thresholds. There is no schema or Alembic migration: the existing `calculation_revision` column is the stale-data guard, and the existing shadow rebuild tables provide the atomic data migration.

## Preconditions

- Deploy code that sets `CURRENT_BREADTH_CALCULATION_REVISION = 3`.
- Confirm local OHLCV caches and point-in-time common-stock universe history cover the rebuild period plus 252 trading sessions of warm-up.
- Confirm the policy registry covers US, CA, DE, HK, IN, JP, KR, TW, and CN.
- Choose the first date that should remain publicly available after cutover.
- Run commands from `backend` with the production virtual environment active.

Revision-aware API reads hide revision-2 rows as soon as revision-3 code is deployed. Breadth may therefore be temporarily unavailable until activation completes; this is intentional and safer than serving mixed methodologies.

## 1. Back up the live data and published artifacts

No `alembic upgrade` is required for this cutover.

```bash
pg_dump --format=custom --table=market_breadth "$BREADTH_DATABASE_URL" \
  --file=market_breadth_before_revision_3.dump
```

Retain a copy of the current static market artifacts and the database dump through the monitoring and rollback windows.

## 2. Build and validate the complete shadow dataset

Omit `--market` so the build stages every breadth-enabled market. A selective build is diagnostic only and cannot activate the full-table replacement.

```bash
python -m app.scripts.rebuild_market_breadth build \
  --start-date 2024-01-01 \
  --end-date 2026-08-28

python -m app.scripts.rebuild_market_breadth validate \
  > breadth-revision-3-validation.json
```

Validation must exit zero and report:

- `"valid": true`;
- `"calculation_revision": 3`;
- local traded-value liquidity in the formula contract;
- the fixed market-policy contract;
- exact market/date manifest coverage;
- reconciled denominators, ratios, and eligibility signatures.

Re-running `build` recreates only the staging dataset and manifest. It does not modify `market_breadth`.

## 3. Pause breadth-dependent writers

Stop Celery beat and prevent these tasks or workflows from starting. Wait for active instances to finish:

- daily breadth calculation and gap fill;
- breadth backfill and revision rebuild;
- market exposure calculation/backfill;
- daily market pipelines and runtime bootstrap;
- static breadth/export publication.

Do not activate while any process can write breadth or its dependent outputs.

## 4. Activate atomically

```bash
python -m app.scripts.rebuild_market_breadth validate
python -m app.scripts.rebuild_market_breadth activate --confirm-replace
```

Activation locks and revalidates the live, staging, and manifest tables; deletes every existing `market_breadth` row, including US revision-2 rows; inserts only validated revision-3 rows; and verifies the revision and row count before committing one transaction.

## 5. Rebuild dependent outputs

Keep writers paused while completing these steps:

1. Rebuild market exposure for the same date range.
2. Rebuild StockBee group attribution where enabled.
3. Republish breadth UI snapshots for every breadth-enabled market.
4. Regenerate static market artifacts and combine only `breadth-r3` outputs.
5. Clear breadth and exposure response/snapshot caches.
6. Restart API, workers, and frontend on revision-3 code.
7. Resume workers and Celery beat.

AU, SG, and MY do not require breadth or exposure rebuilds; their snapshots and static sections continue independently.

## 6. Verify and monitor

For every breadth-enabled market, verify:

- `/api/v1/breadth/current` returns `calculation_revision: 3`;
- UI snapshot and static source markers end with `breadth-r3`;
- live and static latest dates match;
- advancing + declining + unchanged equals its eligible denominator;
- T2108 stays between 0% and 100%;
- StockBee counts do not exceed their metric-specific denominators;
- new daily writers continue producing revision-3 rows;
- exposure and other breadth-dependent views have been regenerated.

Monitor at least two normal market closes before deleting the staging data or backup.

## Rollback

Pause the same writers. Restore the backup into a separate inspection table, validate it, then replace `market_breadth` in one transaction while rolling the application back to revision-2-compatible code. Rebuild exposure, UI snapshots, and static artifacts from the restored dataset before resuming writers. Never restore directly over a live table without inspecting the backup first.

## Delayed cleanup

```bash
python -m app.scripts.rebuild_market_breadth cleanup
```

Cleanup drops only the shadow table and build manifest. After cleanup, staged data is recoverable only by running the rebuild again.
