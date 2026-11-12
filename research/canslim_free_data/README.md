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
