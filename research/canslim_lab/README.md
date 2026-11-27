# CAN SLIM Research Lab

Run from the repository root with Python 3.10 or newer. This workflow evaluates a dated research snapshot and produces JSON with updated CSV ledgers. It has no order execution or live-scanner integration.

```sh
python research/canslim_lab/run.py SCREEN snapshot.json --momentum momentum.csv --verdicts verdicts.csv
```

On the first run, omit the ledger arguments. Save the output's decoded `momentum_csv` and `verdict_csv` strings for the next session. The other modes are `REGIME`, `DEEP-DIVE --ticker ABC`, `HOLDING-REVIEW`, and `SCORE`. Place the snapshot path immediately after the mode.

## Snapshot contract

- Set `as_of` to the signal date in ISO format. In `sources`, list the provenance and observation timestamps of the input series. Build the candidate list in `stocks` from a watchlist, dated leadership list, or authorized screen. This CLI consumes exports or normalized upstream evidence. It does not authenticate, fetch, or independently verify IBD or Unusual Whales data.
- In `market`, supply `nasdaq` and `sp500` objects with booleans `above_21`, `above_50`, `follow_through_active`, `follow_through_failed` and integer `distribution_days`. Derive distribution days from the last 25 completed sessions using a decline of at least 0.2% on higher comparable volume. For follow-through, use a gain of at least 1.25% on higher comparable volume from day four of the rally attempt. Use a close below the rally-attempt low for a failed follow-through. Supply `breadth_trend` as stable, improving, or deteriorating, `vix_curve` as contango, flattening, or backwardation, and `credit_widening` as a boolean. Additional evidence such as the McClellan Oscillator is echoed in the report.
- A correction signal on either index wins. Six distribution days plus a close below the 50-day average qualifies as heavy distribution. Five distribution days or a 21-day break on either index can put the uptrend under pressure. A confirmed uptrend requires both indexes to hold their moving averages, with follow-through on at least one. Missing data may leave the regime unconfirmed.
- For each stock include `ticker`, `close`, `close_src`, `eps_growth`, `sales_growth`, `sales_accelerating`, and `annual_eps_growth` (three year-over-year percentages). Supply analyst grades in `grades` for qualitative criteria, with supporting evidence. Supply `leadership.rs_line_near_high` and `leadership.outperforming_peers` using peers beaten over both three and six months. Put verified IBD data in `ibd` with `source` and `as_of`. The momentum table records available ratings and ranks and compares them to the latest earlier snapshot.
- Supply `base`, `pivot`, `pivot_src`, `pivot_basis`, `invalidation`, `breakout_volume`, `prior_daily_volume_average`, `earnings_sessions`, `next_earnings`, `bear_case`, and `thesis_invalidation`. Any supplied flow evidence is carried with the research record without affecting eligibility. For early entries supply `early_entry` with `setup`, `trigger`, and `confirmation_needed`. For holdings supply `holding: true`, `actual_entry`, and documented `exit_flags`. For a young-company exception supply `young_company: true`, a passing N grade, and `catalyst`.
- The reported `research_defaults` are experimental and can be overridden per snapshot. A-grade requires C, L, and S to pass, annual earnings or the young-company exception to pass, a bear case, and volume confirmation. The initial-loss threshold is 8% from the actual entry. An earnings-risk exception requires `earnings_risk_accepted: true`.

## Scoring

Supply `outcomes` indexed by signal ID, then by `"4"` or `"8"`. Each observation has an ISO `date`, `close`, `source`, `spx_return`, and optionally `matched_baseline_return`, all returns expressed as percentages. Use the first session on or after the calendar anniversary and build the baseline from a point-in-time screen of stocks at a 52-week high in a top-20 group on the same signal date. Match the price adjustment basis and observation windows. Missing baselines remain unavailable. Comparisons below 30 observations are flagged. Overlapping windows and repeat tickers can reduce the effective sample size.

The CLI scores verdict-date returns. A separate fill-based study is required to measure trade returns and stop-outs. The existing frozen CAN SLIM V2 validation protocol remains the reference for its own shadow sample.
