# Breadth Contributor Snapshot Rollout

Breadth contributor drilldowns are an additive schema layered on the existing revision-3 breadth aggregates. They retain frozen company and IBD-group metadata for the latest 20 completed breadth sessions per market. The aggregate formulas and `calculation_revision = 3` do not change. New aggregate writes also store a contributor calculation signature so later snapshot repair can prove exact symbol and qualifying-value identity, not only matching counts.

## Deploy

1. Back up the database using the normal environment procedure.
2. Stop breadth writers so the migration and initial snapshot backfill do not overlap a daily run.
3. Apply the additive schema:

   ```bash
   cd backend
   ./venv/bin/alembic upgrade head
   ```

4. Restart the application and workers. New daily and ordinary historical breadth calculations now persist the aggregate and its contributor snapshot in one transaction.
5. Populate provenance-bearing sessions in the retained window from cached prices:

   ```bash
   cd backend
   ./venv/bin/python -m app.scripts.backfill_breadth_contributors \
     --markets US,CA,DE,HK,IN,JP,KR,TW,CN \
     --limit 20
   ```

The command is strict cache-only. It skips pre-migration or aggregate-only rows that do not have a contributor calculation signature, reports `skipped_unverifiable_dates`, and exits nonzero so an incomplete rollout cannot look successful. Exact contributor identity cannot be reconstructed safely from counts alone. To populate those older sessions, run the normal canonical breadth backfill so the aggregate and snapshot are recalculated and persisted together; then rerun this command.

For each provenance-bearing market/date, all requested dates must have complete cached input, the calculation signature must match, and every one of the 11 contributor counts must match the stored revision-3 aggregate. Otherwise that market writes no snapshots and exits nonzero. A count mismatch is reported as:

```text
market,date,signal,aggregate_count,contributor_count
```

Do not repair a mismatch by editing either count. Rebuild the affected revision-3 breadth data from its canonical inputs, then rerun the contributor command.

## Verify

- `GET /api/v1/breadth/contributors/index?market=US` returns `breadth-contributors-v1`, revision 3, and at most 20 newest-first dates.
- `GET /api/v1/breadth/contributors?market=US&date=YYYY-MM-DD` returns one frozen document, including complete empty snapshots when no stocks qualify.
- A nonzero supported Recent History cell opens the Stocks dialog; ratios, T2108, Broad Universe, zero cells, and dates outside the index remain plain text.
- The IBD Groups tab totals to the clicked cell count and keeps `No Group` last.
- Regenerate static artifacts and confirm each advertised `assets.breadth_contributors.index_path` and its date files exist. An invalid optional contributor asset must be omitted without removing the market or its aggregate breadth page.

## Rollback

Older application versions ignore the additive tables, nullable provenance column, and static asset descriptor. Roll back the application first; the contributor tables and provenance column may safely remain while revision-3 aggregates continue serving existing clients. If the schema itself must be removed, stop writers, preserve a backup, and downgrade one Alembic revision. The downgrade removes contributor snapshots and the nullable `market_breadth.contributor_calculation_signature` column; it does not alter aggregate values.
