# CAN SLIM Adaptive Entry Study (research only)

Status: protocol only; no backtest run, no production gate changes.

## Objective
Test whether the existing CAN SLIM system's market-regime and entry thresholds exclude profitable trades without adequately reducing downside. Avoid selecting only successful examples such as LLY.

## Immutable control
Model A: current production CAN SLIM criteria, including N within 10% of the rolling 52-week high, proprietary RS >=80, existing C/A/S/I rules, existing M restrictions, and the 8% initial-loss rule based on actual entry price. Missing proprietary data stays unavailable; it is never imputed as a pass.

## Experimental variants
- B (M-only): unchanged N and L; in *cautionary* M only, allow 25% of normal initial size when all other existing gates pass and independent stock strength/volume conditions are documented. No entries during confirmed downtrend unless explicitly authorized as a separate experiment.
- C (N-only): permit up to 15% below the point-in-time rolling 52-week high; all other gates unchanged.
- D (L-only): proprietary RS >=75; all other gates unchanged.
- E (combined): B+C+D, evaluated only after individual attribution.
All variants retain the 8% initial-loss rule and original C/A/S/I conditions.

## Required point-in-time inputs
Daily adjusted and unadjusted OHLCV, split/corporate-action history, publication-timestamped SEC earnings and annual fundamentals, point-in-time proprietary RS history or licensed equivalent explicitly labelled as a different measure, market-regime states and inputs as originally defined, historical institutional filings by filing date, historical watchlist universe including delisted names, actual entry/exit timestamps, fees and slippage.

## Design
1. Audit existing CAN SLIM scan and backtest code and extract the exact original predicates before coding experiments.
2. Freeze definitions and data availability timestamps. Never backfill earnings, institutional reports, or RS before public availability.
3. Evaluate B, C and D separately versus A, then E. Use the same universe, portfolio constraints, execution timing and risk limits.
4. Include all eligible historical candidates, failed breakouts, delisted stocks, and non-trades. Use chronological train/validation/test windows and a held-out out-of-sample period.
5. Compare annualized and total return, maximum drawdown, exposure-adjusted return, Sharpe, turnover, win rate, profit factor, average win/loss, stop-outs, and opportunity cost.
6. Stress-test market regime changes, earnings gaps, trading costs, and the 10%/15% and 75/80 boundary neighborhoods.
7. Reconstruct LLY, ANET and FTNT only as case studies; do not use their outcomes to choose thresholds.

## Release criteria
No live alerts, order routing, or merge to production. A candidate change requires an auditable point-in-time dataset, passing deterministic tests, credible out-of-sample improvement net of costs, and explicit approval.

## Known blockers
Repository implementation and data coverage not yet audited. No historical proprietary RS or complete point-in-time institutional dataset verified. Do not claim tested results until executable runs and artifacts exist.
