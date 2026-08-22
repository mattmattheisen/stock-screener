# Correction Survivors and Action State Design

**Status:** Implemented in Releases A1 and A2; repository-wide verification retains 7 documented pre-existing environment failures; Setup Follow-Through remains deferred

**Date:** 2026-08-21

## Context

The Minervini feature report, source ledger, and action-state mockup describe a
useful gap in the product: the scanner can find strong stocks and the Setup
Engine can explain individual setups, but neither the live app nor the static
site offers a first-class workflow for stocks that held up well during a market
correction and are becoming actionable during the recovery.

The current architecture already has most of the underlying evidence:

- relative-strength ratings and benchmark-relative return,
- trend-template and moving-average alignment,
- Setup Engine patterns, contraction, tight-close, quiet-day, and dry-up data,
- extension, structural invalidation, liquidity, and earnings-risk flags,
- live watchlist stewardship transitions,
- snapshot-native scan rows shared by API scans and static export.

The missing layer is a stable decision contract that converts those inputs into
an explainable survivor classification and one current action state. That
contract must be computed once by the backend and consumed consistently by the
live app and static site. Re-deriving it independently in React or in the static
exporter would create policy drift.

## Goals

- Identify stocks that demonstrate leadership, trend integrity, constructive
  structure, and tradability through a correction.
- Rank eligible survivors with a transparent `resilience_score` without turning
  that score into an opaque eligibility rule.
- Assign a deterministic `action_state` with explicit precedence and reasons.
- Give live and static Scan surfaces the same preset, table state, evidence, and
  degraded-data behavior from the same persisted snapshot contract.
- Add a survivor summary to both Daily Snapshot surfaces.
- Overlay Action State on the live watchlist without replacing its existing
  strengthening/deteriorating stewardship model.
- Preserve Market and MIC provenance, benchmark identity, policy version, and
  as-of dates in every result.

## Non-Goals

- Do not create user-owned watchlists in the static site.
- Do not replace the Setup Engine, stewardship statuses, or Market Exposure
  model.
- Do not let market posture silently multiply or suppress a stock score.
- Do not reconstruct full `se_explain` or `se_candidates` payloads in static
  bundles.
- Do not introduce another absolute-volume or hard-coded USD liquidity policy;
  use the repository's existing Market-aware liquidity result.
- Do not include Setup Follow-Through outcome cohorts in the first release. That
  validation work is a separate release because the current validation records
  do not carry the required market, pattern, posture, and profile dimensions.

## Terminology

**Correction survivor** means a stock that passes all mandatory availability,
leadership, trend, structure, and liquidity gates for a specific Market snapshot.
It is an eligibility result, not a buy recommendation.

**Resilience score** is a zero-to-100 explanation and sort key for eligible
stocks. It cannot rescue a stock that failed a mandatory gate.

**Action State** is the most important current condition after applying the
precedence rules in this document. It answers what deserves attention now, not
how the stock performed historically.

**Market posture** is the advisory `MarketExposure` stance pinned to the same
market date. It provides context but does not alter survivor eligibility,
resilience score, or Action State.

**Stewardship status** is the live watchlist's cross-run state: strengthening,
unchanged, deteriorating, exit risk, or missing from run. It remains separately
visible because it answers a different question from Action State.

## Architecture

The backend owns the policy and publishes one compact snapshot-native projection.

1. A pure domain policy receives normalized, typed inputs and returns a complete
   opportunity-state result without querying databases, clocks, or services.
2. An application service assembles feature-row, Setup Engine, event, liquidity,
   prior-run stewardship, Market/MIC, benchmark, and as-of inputs.
3. The result is stored in the feature row's flexible `details_json` before the
   row is exposed through scan repositories or static export.
4. Three flat fields support filtering and sorting:
   `correction_survivor`, `resilience_score`, and `action_state`.
5. A compact nested `opportunity_state` object supports evidence displays and
   auditability.
6. Live scan APIs and static scan bundles serialize the same projection. Static
   export continues to omit the large Setup Engine explanation and candidate
   payloads.
7. Shared React presentation components render the contract. They do not
   recalculate policy.

The intended implementation boundaries are:

- `backend/app/domain/scanning/opportunity_state.py` for normalized types,
  scoring, gates, and state precedence,
- `backend/app/services/opportunity_state_service.py` for assembling current and
  optional prior-run inputs,
- existing feature computation/persistence orchestration for materialization,
- existing scan repository, query-field registries, response schemas, and
  static serializer for delivery,
- shared frontend components for badges, evidence, and Daily Snapshot panels.

No relational schema migration is required for the row projection because
`StockFeatureDaily.details_json` is the existing flexible feature payload.
Database migrations are still required to seed the live predefined preset.

## Persisted Contract

Each computed feature row will expose this versioned contract:

```json
{
  "correction_survivor": true,
  "resilience_score": 84.0,
  "action_state": "setup_ready",
  "opportunity_state": {
    "schema_version": 1,
    "policy_version": "correction-survivors-v1",
    "as_of_date": "2026-08-21",
    "market": "US",
    "mic": "XNAS",
    "benchmark_symbol": "SPY",
    "benchmark_as_of_date": "2026-08-21",
    "passed_checks": ["benchmark_leadership", "trend_integrity"],
    "failed_checks": [],
    "warnings": [],
    "metrics": {
      "benchmark_relative_return_65d": 0.083,
      "rs_rating_1m": 94.0,
      "rs_rating_3m": 88.0
    },
    "data_availability": {
      "features": "available",
      "liquidity": "available",
      "event_calendar": "available",
      "prior_run": "available"
    },
    "action_reasons": ["survivor", "setup_ready", "early_entry_zone"]
  }
}
```

The contract uses `benchmark_relative_return_65d` as the public term because the
benchmark is Market-specific. Existing `se_rs_vs_spy_65d` data may remain an
internal compatibility alias while producers and consumers migrate.

Allowed action-state values are:

- `exit_risk`
- `deteriorating`
- `event_risk`
- `extended`
- `data_limited`
- `setup_ready`
- `watch`

Rows from old snapshots that do not contain `opportunity_state` are not
backfilled in the browser. They expose `action_state: null` and render as “Not
computed,” not as `watch` or `data_limited`.

## Survivor Eligibility

Eligibility is conjunctive. A row is a correction survivor only when every gate
below passes.

### 1. Required evidence

The snapshot must provide:

- Market and as-of date,
- benchmark identity, benchmark as-of date, and 65-session relative return,
- one-month and three-month RS ratings,
- stage and moving-average alignment result,
- structural invalidation result,
- at least one supported structure signal,
- resolved Market-aware liquidity result,
- feature freshness/status result,
- explicit event-calendar availability, even when there is no upcoming event.

Missing required evidence makes the row ineligible and yields
`action_state: data_limited`, unless a higher-precedence state can be proven from
available evidence.

### 2. Leadership

All of the following must hold:

- `benchmark_relative_return_65d > 0`, or the existing RS-line new-high/blue-dot
  signal is true;
- `rs_rating_1m >= 80`;
- `rs_rating_3m >= 70`.

### 3. Trend integrity

All of the following must hold:

- the current trend stage is 1 or 2;
- the existing Setup Engine moving-average alignment rule passes;
- no hard structural invalidation is active.

### 4. Constructive structure

At least one of these existing, point-in-time signals must hold:

- a primary Setup Engine pattern is present;
- squeeze is detected;
- tight closes are at least three;
- quiet days are at least three;
- volume dry-up passes the Setup Engine's current volume-versus-50-day threshold.

### 5. Tradability and freshness

The existing listing-aware, Market-aware liquidity policy must pass and the row's
feature status must be usable for the requested as-of date. This design does not
add a second liquidity formula.

## Resilience Score

The score is calculated only when all required score inputs are available. It is
the sum of five 20-point pillars and is rounded to one decimal place. Boolean
checks contribute either their full points or zero; RS ratings are clamped to
zero through 100 before scaling.

| Pillar | Exact calculation | Maximum |
| --- | --- | ---: |
| Benchmark leadership | 12 when 65-session benchmark-relative return is positive; 8 when RS-line new-high/blue-dot is true | 20 |
| Multi-horizon RS | `10 × rs_rating_1m / 100 + 10 × rs_rating_3m / 100` | 20 |
| Trend integrity | 8 for stage 1/2; 8 for MA alignment; 4 for no hard structural invalidation | 20 |
| Structure/tightness | 8 for a primary pattern; 4 for squeeze; 3 for tight closes ≥ 3; 3 for quiet days ≥ 3; 2 for volume dry-up | 20 |
| Liquidity/freshness | 10 for resolved liquidity pass; 10 for usable/current feature status | 20 |

A row that has a numeric score but fails an eligibility threshold remains
ineligible. The score is retained as evidence when safe to compute, but survivor
views include only `correction_survivor: true`. If any score input is unknown,
the score is `null`; missing values are never treated as zero.

## Action-State Precedence

The policy evaluates states in this exact order and returns the first match:

1. **Exit Risk** — a hard structural invalidation is active, or live watchlist
   stewardship reports `exit_risk`.
2. **Deteriorating** — a confirmed current-versus-prior deterioration signal is
   active, including live stewardship `deteriorating`. Absence of prior-run data
   is not deterioration.
3. **Event Risk** — the event calendar is available and an event falls inside the
   existing Setup Engine caution window.
4. **Extended** — the existing Setup Engine extension flag is active.
5. **Data Limited** — any required current-snapshot input or explicit event
   availability is unknown. Prior-run availability is required only when a
   surface asks for cross-run deterioration.
6. **Setup Ready** — the stock is an eligible survivor, Setup Engine readiness
   passes, the existing early-entry-zone rule passes, and no blocking operational
   flag is active.
7. **Watch** — the current evidence is complete but none of the preceding states
   applies.

`strengthening` remains a stewardship/evidence label and does not become an
eighth Action State. A watchlist row can therefore be both “Strengthening” and
“Setup Ready,” which is useful rather than contradictory.

## Market Posture

Both Scan evidence and Daily Snapshot panels show the date-pinned Market
Exposure stance and benchmark alongside survivor data when available. The UI
labels it as context. It does not change eligibility, score, state precedence, or
sort order.

If posture is unavailable, survivor rows remain visible and the UI shows
“Market posture unavailable.” A missing posture must not be converted into
`data_limited`, because it is advisory rather than a stock-level required input.

## Product Surfaces

### Live and static Scan

Both surfaces receive a predefined **Correction Survivors** preset with identical
filter and sort semantics:

- `correction_survivor = true`;
- primary sort: `resilience_score` descending;
- secondary stable sort: the repository's normal symbol ordering.

The shared Results table gains an Action State column using a shared
`ActionStateBadge`. Selecting the badge opens an `OpportunityEvidenceDrawer`
that displays score pillars, passed/failed checks, blocking warnings, key metric
values, Market/MIC, benchmark, and as-of provenance. The drawer is independent
of chart availability and does not require full Setup Engine payloads.

The static preset remains in `backend/app/services/preset_screens.py`. The live
preset is added through a new forward-only Alembic migration rather than editing
the historical seed migration. A contract test compares the two definitions so
their filters and ordering cannot drift silently.

### Live and static Daily Snapshot

A shared `CorrectionSurvivorsPanel` summarizes:

- survivor count,
- counts by Action State,
- the highest-resilience survivors,
- visible Market posture and as-of provenance.

The live Daily Snapshot obtains rows from the live service. Static Home derives
the panel from the already-downloaded scan chunks and the same predefined preset,
avoiding another bundle or a browser-side policy implementation. Empty results
show a valid zero-result state; incomplete source chunks show an explicit
unavailable/incomplete state.

### Live Watchlist

The watchlist table adds Action State as a separate overlay next to its existing
stewardship status. The backend supplies the current opportunity projection plus
the optional stewardship state to the same precedence function. Existing
stewardship fields, transitions, and US-only scope remain unchanged.

There is no static watchlist equivalent in this release.

## Querying and Serialization

Both scan filter-field registries and the feature-store query mapper must expose
the three flat fields with typed null handling. Scan response schemas and
repository extended-field mapping must carry both flat values and the compact
evidence object.

Static export includes this compact projection even though it continues calling
its row loader without full Setup Engine payloads. The static bundle schema or
manifest feature version is incremented so stale consumers can distinguish
pre-feature bundles. Mixed old/new chunks degrade per row: old rows display “Not
computed” and do not enter the survivor preset.

The policy is materialized during feature generation, not calculated in scan
queries. This keeps filtering cheap and guarantees that API and static output
refer to the exact result that was evaluated for the snapshot.

## Data Normalization and Degraded Behavior

- Normalize `next_earnings_date` from supported persisted string, datetime, or
  date representations before policy evaluation.
- Store event-calendar availability separately from “no upcoming event.” An
  unavailable calendar yields `data_limited`; an available calendar with no
  event does not.
- Reject or warn on benchmark dates that do not match the row's declared
  point-in-time policy. Do not silently use a future benchmark value.
- Preserve null for unavailable numeric evidence; do not coerce it to zero.
- Keep a survivor row usable when Market posture is absent.
- Keep current-only Scan rows usable when prior-run evidence is absent. Only a
  watchlist/cross-run view that requests deterioration requires prior-run
  availability for that aspect of its state.
- If policy computation fails for an individual row, persist a structured
  `data_limited` result with a safe reason code and continue the batch. If the
  entire policy/materialization stage fails, fail the owning feature run rather
  than publish a partially indistinguishable snapshot.

## Testing

### Backend domain tests

- Cover every survivor gate at its pass/fail boundary.
- Verify all five score pillars, clamping, rounding, maximum score, and null
  propagation.
- Parameterize every pair of competing Action States to prove precedence.
- Prove unavailable event data differs from an available calendar with no event.
- Prove Market posture cannot change stock-level eligibility, score, or state.
- Prove hard invalidation can produce `exit_risk` even when other evidence is
  missing.
- Prove absent prior-run evidence does not invent deterioration.

### Backend integration and contract tests

- Verify feature persistence and repository mapping round-trip the flat and
  nested fields.
- Verify filtering and descending sort for the Correction Survivors preset.
- Verify live and static predefined preset definitions are semantically equal.
- Verify static serialization includes compact evidence while excluding full
  `se_explain` and `se_candidates` payloads.
- Verify old snapshots and mixed static chunks do not classify absent payloads as
  `watch`.
- Verify event-date normalization for date, datetime, and supported string forms.
- Verify a row-level computation failure is explicit and a stage-level failure
  prevents a misleading successful run.

### Frontend tests

- Render every Action State, `data_limited`, and “Not computed” distinctly.
- Verify shared Results table behavior in live and static modes.
- Verify the evidence drawer works when chart data and full Setup Engine data are
  absent.
- Verify Daily Snapshot counts and ranking use persisted fields only.
- Verify empty, incomplete, stale, and unavailable states.
- Verify watchlist stewardship and Action State remain separate columns.

### End-to-end fixtures

Create one deterministic Market snapshot containing examples for every Action
State and one legacy row without the new contract. Exercise it through both the
live API and static build, then assert equivalent preset membership, ordering,
badge labels, and evidence provenance.

## Rollout

### Release A1: Shared Scan contract

- Add the domain policy and assembly service.
- Materialize and query the versioned projection.
- Add the live and static predefined preset with parity coverage.
- Add the shared Results table column, badge, and evidence drawer.
- Rebuild affected feature snapshots and static bundles after deployment.

The feature is hidden when the bundle/API capability version is absent. Old
snapshots remain readable and display “Not computed.”

### Release A2: Daily and watchlist workflow

- Add the shared Daily Snapshot survivor panel to live and static surfaces.
- Add the separate Action State overlay to the live watchlist.
- Add telemetry for survivor counts, state distributions, unknown-input rates,
  and evidence-drawer usage without recording user-sensitive watchlist content.

### Release B: Setup Follow-Through

Extend validation records to include Market/MIC, policy version, survivor status,
Action State at signal time, pattern family, market posture, and entry profile.
Then publish one-, five-, and later-session return, MFE, MAE, and invalidation
outcomes by cohort. Release B must not retroactively infer missing dimensions
from current data.

## Acceptance Criteria

- The same snapshot row produces identical survivor status, score, Action State,
  and evidence in the live app and static site.
- The Correction Survivors preset has identical live/static semantics and stable
  ordering.
- Every displayed state has machine-readable reasons and point-in-time
  provenance.
- Missing data is visible and cannot silently become zero, `watch`, or a false
  no-event result.
- Market posture is visible context and has no hidden scoring effect.
- Watchlist stewardship remains intact and independently understandable.
- Static bundles gain compact evidence without gaining the full Setup Engine
  payload.
- Existing snapshots remain readable through an explicit “Not computed” state.
