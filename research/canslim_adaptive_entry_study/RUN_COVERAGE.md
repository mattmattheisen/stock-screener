# Executing the read-only coverage audit

From a Codespace or backend environment with an accessible PostgreSQL database:

```bash
PYTHONPATH=backend:. python -m research.canslim_adaptive_entry_study.coverage_report > canslim_coverage.json
python -m pytest -q research/canslim_adaptive_entry_study/test_*.py
```

Use **SELECT-only database credentials**. The utility performs aggregate SELECTs only. It does not backfill or modify records. Do not commit database credentials or exported data.

Interpretation:
- `stock_prices`: OHLCV coverage is not proof of correct splits/dividend adjustments, full trading calendars, or delisted constituents.
- `stock_fundamentals`: current one-row-per-symbol data is not a point-in-time historical filing archive. `data_source_timestamp` is not sufficient to infer past values.
- `feature_runs` and `stock_feature_daily`: run dates and feature snapshots may support historical signal reconstruction, but require source-specific as-of evidence and completeness review.
- `historical_ibd_rs`, `historical_fundamental_asof`, and `delisted_universe` remain explicitly UNVERIFIED.
- The script intentionally reports aggregate coverage, not performance. It cannot connect a missing historical proprietary RS record by substituting the repository's market-relative RS.
- Results are **not** an approval to merge or trade.

Note: SQL uses PostgreSQL FILTER syntax; the production backend is PostgreSQL. Tests of the comparator and ledger do not require database connectivity.

Before any performance simulation, verify daily high/close price adjustment consistency and enforce next-session entry after signals calculated at the close.
