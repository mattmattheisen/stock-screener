# Historical data readiness and first comparison plan

## Current source audit
Inspected `backend/app/scanners/canslim_scanner.py`, `backend/app/scanners/criteria/rs_resolution.py`, `backend/app/scanners/criteria/relative_strength.py`, `backend/app/services/validation_service.py`, `backend/app/services/market_exposure_service.py`, `backend/README.md`, and `docs/ARCHITECTURE.md`.

| Field | Repository evidence | Historical readiness |
|---|---|---|
| Daily OHLCV | `stock_prices` and price cache | Storage exists; historical completeness, delistings, adjustment policy and publication timing not verified |
| Earnings C/A | quarterly_growth / eps_growth_qq and eps_growth_yy | Scanner consumes current snapshot; as-of historical filings not verified; annual EPS is proxied by Y/Y quarterly EPS |
| N | Scanner uses `prices.max()` from supplied data and close price | Historical calculation needs a 252-session rolling **daily high** with correct as-of cut-off |
| S | Scanner reverses price series then calls `prices.diff()` | Direction may be inverted; research uses chronological closes and daily volumes |
| RS | `resolve_stock_rs` supports canonical market-scoped computed ratings and a legacy scan-local calculator | Neither is proven to be licensed historical proprietary IBD RS; keep source identity explicit |
| I | `fundamentals['institutional_ownership']` | Point-in-time historical ownership/filing timestamps not verified |
| M | `market_exposure` stored by date, computed from price, breadth and VIX | Historical score exists conceptually; validate coverage, same-date availability, lookback, and frozen regime mapping |
| Forward outcomes | `validation_service.py` has 1/5/20-session returns, MFE and MAE | Forward scan-hit validation is not a full trade-level portfolio backtest |

## Additional scanner behavior verified
- The production scanner's `_calculate_canslim_score` returns `passes=True` if score >=70 **and C and L pass**. A, N, S and I are scored but not mandatory hard gates. Do not equate its overall `passes` flag with a strict all-letter CAN SLIM rule.
- The scanner's 52-week high is the maximum of supplied reversed closes, not explicitly the last 252 daily highs.
- Its `_check_supply_demand` calls `prices.diff()` on most-recent-first prices, which may invert the direction of up/down-day volume.
- `rs_resolution.py` calls the canonical value a market RS formula and falls back to legacy calculation when canonical mode is not selected. Neither should be relabelled as proprietary IBD RS.

## Go/no-go for historical performance comparison
**NO-GO** until availability timestamps, licensed historical RS (or separately pre-registered proxy study), delisted universe, adjusted prices, and historical institutional snapshots are verified. Synthetic unit-test inputs are not evidence of historical performance.

## Next executable milestone
1. Run isolated GitHub Actions tests and inspect the workflow logs. Correct any failures on the research branch only.
2. Export a **read-only** schema and coverage report for prices, earnings, RS, institutional ownership, and market exposure, with earliest/latest dates and null rates.
3. Construct a chronological signal ledger with per-symbol, per-day gate evidence, `UNAVAILABLE` reasons and source timestamps.
4. Only after data validation, compute A/B/C/D/E signal counts and incremental entries; then add a portfolio simulator with next-session execution, 8% initial stop, costs, exposure limits, and out-of-sample evaluation.
