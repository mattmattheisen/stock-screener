# CAN SLIM Research Lab: no-extra-cost data and language architecture

**Decision:** Python remains the control plane and backtest language. No new paid Unusual Whales API. Optional ChatGPT connector research is **not** a deployable GitHub data feed and should not be copied into production ingestion. Unusual Whales API is disabled/not required.

## Existing architecture to reuse
The repo already runs FastAPI, Celery, PostgreSQL, Redis, React, a feature store, stock scans, and price/fundamental providers. Reuse those rather than installing a parallel scraper or new orchestration platform. Before adoption, audit provider terms, reliability, rate limits, survivorship bias and split/dividend adjustment.

| Need | Source / method | Critical qualifications |
| --- | --- | --- |
| Daily OHLCV | Existing approved market-data providers/cache and price bundles | Check license, historical coverage, timestamp, split adjustment, missing bars and stale sessions |
| 21/50 moving averages and volume confirmation | Derive from point-in-time **completed** daily bars | Never mix adjusted and unadjusted prices; compare to 20 prior complete sessions for volume |
| Market-relative return | Benchmark daily adjusted bars from existing repo | Not the proprietary IBD RS Rating; name it RS proxy |
| Quarterly earnings and sales | SEC companyfacts + filings via existing fundamentals service | SEC data free/no key, but as-reported publication time, amendments, units, and ADR mappings matter |
| Institutional ownership | Form 13F data where supported | Delayed, incomplete and not institutional buying on a given trading day |
| IBD Acc/Dis, Composite, rank | Optional manually licensed point-in-time snapshots | Otherwise **unavailable**; never synthesize an IBD value |
| Unusual Whales options/dark pool | Optional user research via ChatGPT connector only | No unattended GitHub API ingestion without independent permitted credentials |
| Sell alerts | Existing CAN SLIM ChatGPT task or later validated app notifications | Do not equate a ChatGPT summary with running the GitHub scoring code |

## Code and language allocation

* **Python:** provider adapters, fundamental transforms, CAN SLIM screens, portfolio journal, statistical backtests and alert policy. Existing Python toolchain wins on integration and auditability.
* **Rust (phase 2, optional):** isolated deterministic calculation/validation kernel once profiling or invariants show a real need; PyO3 bindings or standalone CLI with stable schema, differential tests against Python. Not a rewrite.
* **Lean 4 (experimental):** model a small collection of trading-system invariants (e.g. no future bar influences an as-of signal, missing evidence never means a confirmed HOLD; no signal is an order). Proofs require independently checked correspondence with production implementation. Lean alone does not validate financial alpha.
* **C++ (defer):** only if empirical profiling finds latency-sensitive computation or an existing native library warrants it. Not justified for once-daily end-of-day signals.

## Current deliverable
`data_contract.py` demonstrates an explicit provider-neutral daily-bar contract and reference 21/50-day and relative-volume calculation. It is **offline**, not wired to Celery, the feature store, or alerts. Its observations insist on adjusted, complete daily bars, provenance and an as-of cutoff. It currently rejects unadjusted prices; a production adapter must implement and test corporate-action handling before feeding it.

Test: `python -m unittest discover -s research/canslim_free_data/tests -v`

## Acceptance gates before merging an operational connector
1. Identify and validate an existing legal, free-at-point-of-use data provider through the repository's adapters, with outage/staleness behavior.
2. Build a complete and corporate-action-aware price/volume ingestion adapter and SEC as-of earnings join.
3. Deterministic point-in-time backtests and holdout period, including gaps, realistic execution assumptions and performance diagnostics.
4. Confirmed alert transport, idempotent state transitions, notification provenance and manual trade authority.
5. Existing CI and new tests pass on the integration branch. Never hide failures by skipping gates.

This proposal introduces **no** extra subscription, secret requirement, scheduled job, live endpoint, broker connection, or automatic trade execution.

## Existing-cache bridge added (Nov 2026)

`cache_bridge.py` now reads the repository's existing `PriceCacheService.get_cached_only(symbol, period="1y")` cache-only contract. It never triggers live yfinance/Alpaca/Unusual Whales network calls and has **not** been wired to the running scanner.

Read-only signals are blocked unless the caller has explicitly verified:
- `Adj Close` is truly adjusted with known provenance (no implicit raw `Close` substitution);
- the full lookback is corporate-action reconciled, including split effects on raw volume;
- the expected completed market session exists (stale/intraday bars cannot masquerade as a final close).

This matters because the existing `stock_price_row_from_ohlcv` normalization code currently substitutes `close` when `Adj Close` is missing; thus a populated cached field is **not proof of adjusted-price provenance**. The repository's price contract ADR also documents known historical adjustment/correction risks. Do **not** mark verification flags true without a demonstrated independent audit.

**Remaining blockers:** reconciled adjustment factors and adjusted-volume semantics across splits; production data provenance feed; true historical as-of snapshots (modern dividend-adjusted series can be restated retrospectively); independent benchmark comparisons; and an operational alert transport. None is implemented by this read-only adapter.

Unit tests for this adapter are in `tests/test_cache_bridge.py`; CI status must be checked separately. No merge or production alert activation has been performed.

## Explicit provenance gate (Nov 12, 2026)

`price_provenance.py` introduces a separate receipt/gate differentiating end-of-day observations from *historical point-in-time* data. It rejects missing audit identities, raw-close fallback, unverified corporate actions / split-volume treatment, stale sessions, naive retrieval timestamps, and retrospective downloads represented as historical-as-of snapshots. Eight isolated unit tests cover these cases.

**Important limitation:** this is a validation contract, not an independent attestation service. An upstream system can currently fill verification identifiers without proving its adjustment logic. **Do not automatically generate or trust these identifiers.** A production-grade provenance service must supply reproducible source hashes, provider adjustment metadata, event reconciliation evidence, and historical snapshot timestamps before the receipt can be relied on for trading research. Existing `cache_bridge.py` still uses booleans and is not wired to this new gate. Consequently, neither this PR nor its presence in GitHub certifies the source data.

The important difference is *data fetched today about 2026-08-14* versus *data actually observed by the system on 2026-08-14*. Today's dividend-adjusted data can be revised by later events and must not be treated as a point-in-time historical observation.

No merge or live alert integration is authorized by these checks alone.

## Cache provenance diagnostics wired to existing cache API

`cache_audit_runner.inspect_cached_prices` consumes the real
`PriceCacheService.get_cached_only(symbol, period="1y")` interface.
It is **read-only**, never refreshes data, and always labels the results
`data_certified=False`. It reports missing adjusted close, suspicious
raw/adjusted equality, stale sessions, future bars and the outstanding
split/corporate-action and historical snapshot verification requirements.

Seven new isolated tests cover nominal-but-unverified data, potential
raw-close substitution, missing adjusted columns, stale/future data,
empty cache, and invalid as-of ordering.

### Specific blocker uncovered in production path

`backend/app/services/price_row_normalization.py` currently uses
`"adj_close": adj_close if adj_close is not None else close`.
That makes a populated database `adj_close` value *insufficient* to
certify adjustment provenance. We cannot infer truthful adjustment
metadata from the cached dataframe. Correcting this safely requires a
separately reviewed change to the backend persistence contract and
schema consumers; simply renaming the field would leave historical
bad rows untouched. The price-contract ADR
`docs/learning_loop/adr_ll2_e1_canonical_price_contract_v1.md`
already identifies this hazard.

**Do not flip verification booleans based on this diagnostic report.**
No existing production scanner code, database table or deployed task
was modified by this change. GitHub CI execution and data-source
certification are separate pending gates.

## Shared normalization patch staged (research branch only)

The branch now changes `backend/app/services/price_row_normalization.py`
so an absent `Adj Close` is persisted as SQL NULL rather than copied from
raw `Close`. Three backend unit regression tests cover missing, explicit,
and equal-but-not-provably-adjusted values.

**Migration/reconciliation is not complete.** Historical rows that were already
written with fabricated raw-close aliases remain indistinguishable without
external source data. Existing consumers that expect non-null adjusted closes
may need updates. Therefore this shared-backend change must not be merged
until baseline CI, consumers, and data migration plans are reviewed. It does
not establish adjusted volume semantics or historical point-in-time evidence.

## Compatibility and historical reconciliation work

On this research branch only:
- `stock_price_row_from_ohlcv` preserves missing adjusted prices as NULL.
- `stock_price_persistence` protects an existing non-null, usable adjusted
  value from an incomplete incoming refresh rather than overwriting it.
  This is **not** certification of the existing adjusted value.
- Three additional pandas/service compatibility tests and five refresh-policy
  tests were added alongside the earlier ingestion regression tests.
- `sql/historical_price_inventory.sql` supplies PostgreSQL **SELECT-only**
  checks for missing/invalid adjusted prices, suspicious raw/adjusted equality,
  possible corporate-action discontinuities and duplicate natural keys.

### Not yet resolved with current access

The GitHub repository alone does not expose the production PostgreSQL rows or
the original market-provider payloads. Historical `adj_close` values previously
filled from raw `close` cannot be reliably identified solely by equality,
because equality is legitimate when adjustment factor = 1. Backfill requires
independent provider corporate-action history, verified adjusted prices,
a protected database snapshot, a reviewed deterministic reconciliation,
and only then a staged migration. No DELETE/UPDATE SQL is supplied or run.

For historic point-in-time backtests, even newly retrieved adjusted data is
not equivalent to the original observation as of the historical trading date.
Model dividends/splits explicitly, preserve raw event dates and distinguish
retrospective reconstruction from original as-of snapshots.

**Merge gate:** actual database inventory, consumer compatibility tests, full
CI plus migrated fixture tests, source contract review and rollback rehearsal.
None has been certified by this branch alone. Rust is deferred.

## Offline comparison workflow (no database writes)

1. Execute `sql/historical_price_inventory.sql` against a **read-only** database
   connection and retain the output with its execution timestamp.
2. Export the required raw database rows to a separate local CSV containing
   `symbol,date,close,adj_close,volume`. Preserve a backup/snapshot before
   any migration. Do not upload confidential datasets to GitHub.
3. Independently obtain and license an appropriately corporate-action-adjusted
   reference series; export a separate CSV containing
   `symbol,date,close,adj_close,volume,source_id`. A `source_id` string is
   attribution, **not verification**. Note reference adjustment mode,
   retrieval timestamp, symbol mappings, corporate events and volume policy.
4. Generate a review-only report:

```bash
python research/canslim_free_data/reconcile.py \
  --db-export existing_prices.csv \
  --reference reference_prices.csv \
  --as-of 2026-11-12 \
  --report price_reconciliation_review.json
```

The tool compares symbol/trade-date keys, identifies missing/invalid price
adjustments and raw or adjusted-close conflicts, and records SHA-256 hashes
of its inputs. No SQL updates, trading signals, or API network calls occur.
A matching row only means **numerical equality**, not trusted provenance,
and a backfilled adjusted series is not a historical point-in-time snapshot.
Eight local fixture tests for this utility passed. Actual database data has
not been compared, so this is not yet a completed historical remediation.

The dedicated workflow now watches modified backend files, compiles the
touched Python files and executes the standalone research tests. Backend
integration tests still require the repository's full dependency/setup CI;
a syntax check does not prove semantic compatibility.
