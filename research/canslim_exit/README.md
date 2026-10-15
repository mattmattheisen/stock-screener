# CAN SLIM Exit Ledger — research-only integration

This isolated prototype adds **no** orders, trading API calls, jobs, schedulers, notification delivery, UI routes, or database migrations. The existing screener is unchanged until a separate integration is reviewed. It is a Python standard-library command line module.

## Run

```bash
python research/canslim_exit/exit_ledger.py research/canslim_exit/example_input.csv /tmp/exit_signals.csv
python -m unittest discover -s research/canslim_exit/tests -v
```

CSV columns: symbol, data_as_of, entry_price, close, peak_close_since_entry, atr22, ma21, ma50, volume_ratio, rs_change_3w, rs_rating, accdis_downgrades, rank_drop, leadership_lists_lost, group_weakening, failed_breakout, distribution_days, earnings_thesis_broken, risk_off. Leave missing data blank. Boolean inputs are true/false.

A decline of 8% from **original actual trade entry** triggers an *exit review*, not an order. A 7% warning band and treatment of partial fills/add-ons have **not yet** been implemented. Adjust prices and entry cost for splits consistently, and verify corporate actions before using. An 8% stop is not guaranteed to execute at that price in a gap. A reported 50-day break is observational and requires volume and persistence context.

Raw score thresholds are experimental, **not historically validated**. Unknown indicators are never treated as false and <75% weighted coverage produces INSUFFICIENT DATA (except overriding hard-stop or failed-breakout evidence). The Chandelier column is explicitly a close-based proxy (not a standard rolling highest-high stop) and does not cause an automatic exit.

## Attribution

Confirmed CAN SLIM entry cohort (as provided by user):
MSFT 10 @496.50 (2026-08-14); TSM 11 @428.23 (2026-08-14); ANET 25 @192.82 (2026-09-04); LLY 4 @1148.54 (2026-09-04); FTNT 18 @177.78 (2026-09-25).
MU, PANW, SPHB, ZS, CRWD, and AMD are legacy-strategy trades and **must not** be attributed to CAN SLIM. Do not put account identifiers in the repo.

## Validation next

Use point-in-time split-adjusted OHLCV history with executable next-bar fills and realistic gaps/slippage; compare fixed exits, 21/50-day structure, proper rolling-high Chandelier, and score logic, retaining as-of historical IBD changes only when actually available. Measure return, drawdown, upside captured, turnover and false exits, with out-of-sample or walk-forward validation. This commit does not assert any live market values or performance superiority.
