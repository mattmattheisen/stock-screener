# Initial code audit — 2026-11-11

## Verified
- `backend/README.md` identifies a CANSLIM scanner in the scanner registry and a separate `/validation` workflow for follow-through validation of published scan picks and theme alerts. This is **not yet verified** to be a trade-level, point-in-time portfolio backtester.
- `docs/LIVE_APP_GUIDE.md` describes the built-in CANSLIM screen as C quarterly EPS >=25%, A annual EPS growth >=15–25%, **N within approximately 15% of the 52-week high**, S up/down volume >=1.3, L RS >=80, and I institutional ownership ~40–80%.
- **Methodology mismatch:** the user's independently defined CAN SLIM research watch uses **N <=10%**. The existing stock-screener documentation says ~15%. Therefore do not treat this repository's scanner as the unchanged control without finding and verifying its actual implementation and introducing an explicit 10% research-only baseline.
- `backend/app/services/market_exposure_service.py` has a 0–100 market exposure rubric with stance bands: Power Trend >=85; Confirmed Uptrend >=65; Uptrend Under Pressure >=50; Downtrend/Caution >=30; Correction/In Cash below 30. It computes distribution days using >=0.2% down with higher volume over 25 sessions, with a baseline and penalties. Its follow-through-day detector explicitly labels itself a heuristic, not a true IBD state machine.
- The market exposure module says it was tuned on SPY 2024–2026; this is not independent evidence of predictive validity.

## Required before implementation
1. Locate the exact CANSLIM scanner source and configuration; document real gates and missing-data behavior.
2. Trace `/validation` implementation to distinguish forward scan-hit validation from executable trade backtests.
3. Confirm provenance of RS: proprietary IBD RS vs a calculated relative-strength proxy. Never silently substitute.
4. Identify point-in-time fundamentals, price, and institutional filing availability. Verify split handling, delisted symbols, publication timestamps and execution assumptions.
5. Build a separate, pure research comparator with A (user's 10% N and RS80), B (M-only), C (15% N-only), D (RS75-only), E combined; never alter the existing scanner.
6. Run deterministic unit tests, then a chronological out-of-sample backtest if and only if data are adequate.

## Current status
Initial documentation and market exposure code inspected. Scanner implementation not yet located. No executable backtest, no performance claims, no production change.
