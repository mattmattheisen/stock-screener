# CAN SLIM V2 Validation Protocol

Status: **pre-registration / shadow validation only**

This document freezes the validation rules for CAN SLIM V2 before any production registration. The purpose is to prevent hindsight, threshold chasing, and retrospective use of today's fundamentals against historical prices.

## 1. Non-negotiable point-in-time rule

Do **not** retrospectively rerun V2 on old dates using the current fundamentals cache.

C, A, I, group leadership, and market state are time-sensitive. A historical price series combined with today's EPS CAGR, ownership, or market-exposure state is not a valid backtest.

Valid evidence is limited to:

1. a genuinely point-in-time stored snapshot containing all required V2 inputs, or
2. a prospective shadow run where V1 and V2 receive the same `StockData` and same market-state snapshot at scan time.

If a field cannot be reconstructed point-in-time, mark it unavailable. Do not silently substitute a current value.

## 2. Frozen V2 methodology for the first shadow window

Once shadow collection begins, the following are frozen under methodology version `canslim_v2`:

- C/A/N/S/L/I scoring bands
- C, A, and L hard stock gates
- 70-point stock qualification threshold
- M exposure bands and the rule that M contributes zero stock-score points
- input-normalization rules

Any methodology change creates a new version and restarts the shadow-validation window. Do not tune thresholds on the same sample used to judge them.

## 3. Gate A — deterministic correctness

Required before any shadow run:

- all V2 criterion unit tests pass
- all scorecard tests pass
- all StockData adapter tests pass
- direct unregistered V2 scanner tests pass
- V1 production scanner remains unchanged
- V2 remains unregistered

Initial branch gate at creation: **39 deterministic tests passing**.

## 4. Gate B — live data coverage

Before judging returns, measure whether the existing data pipeline can evaluate V2 fairly.

Track per market and per run:

- C availability
- A availability
- N availability
- S availability
- L availability
- I availability
- M availability
- percentage of symbols with all C/A/L hard-gate inputs available

Do not interpret low scores caused by missing inputs as investment evidence. Missing-data rates are a data-quality result, not a failed CAN SLIM signal.

## 5. Gate C — prospective V1 vs V2 shadow collection

For every normal published scan run, calculate V1 and V2 from the **same pre-fetched point-in-time StockData**.

Persist at minimum:

- run/as-of identifier
- symbol
- V1 score, pass state, and rank
- V2 stock score, stock-pass state, M state, actionable state, and rank
- each V2 letter's points/pass/availability
- methodology version
- market-exposure score and stance used by M

Shadow results must not alter the user-facing composite score, portfolio action, or existing published V1 result.

## 6. Outcome horizons

The existing validator's next-session entry rule is acceptable and should be reused.

Use:

- 1-session return as a diagnostic only
- 5-session return/MFE/MAE as an early diagnostic
- **20-session return/MFE/MAE as the primary CAN SLIM validation horizon**

The 20-session horizon should be added to the existing deterministic validation service before V2 is considered for production registration. CAN SLIM is not fundamentally a one-day signal, so registration should not be decided from one- or five-session performance alone.

## 7. Comparison metrics

Compare V1 and V2 on equal-size top-N cohorts per run and on pass-qualified cohorts.

Report:

- sample size
- mean and median forward return
- positive-return hit rate
- median MFE
- median MAE
- MFE/absolute-MAE ratio
- V1/V2 top-N overlap
- V1/V2 rank correlation
- qualified-symbol count
- missing-data rate by letter
- results segmented by M stance

Do not promote one attractive metric while ignoring the rest.

## 8. Minimum evidence before registration

Do not register V2 as a production-selectable screener until all of the following are true:

1. deterministic correctness gate remains green;
2. no point-in-time leakage is identified;
3. the primary C/A/L inputs have acceptable live coverage for the target market;
4. at least **60 trading sessions** of prospective shadow data exist;
5. at least **300 V2 top-N or qualified stock-events** have matured through the 20-session horizon;
6. V2 does not show a material deterioration versus V1 in median 20-session return or downside behavior;
7. any claimed V2 improvement is visible across more than one market stance and is not driven by a handful of symbols;
8. methodology thresholds were not changed during the evaluation window.

If V2 fails these gates, keep V1 and diagnose which letter or data dependency caused the failure. A failed validation is a useful result.

## 9. Registration order after validation

Only after the evidence gate passes:

1. wire market exposure into scan-level context once per market/run;
2. register `canslim_v2` alongside V1, not as an in-place replacement;
3. expose V1/V2 side-by-side for a release period;
4. extend validation reporting to break out V1 and V2;
5. deprecate V1 only after a separate explicit decision.

This protocol intentionally favors a small, falsifiable migration over a wholesale rewrite.
