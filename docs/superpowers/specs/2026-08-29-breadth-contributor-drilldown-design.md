# Breadth Contributor Drilldown Design

**Date:** 2026-08-29

## Objective

Let a user click a membership-count cell in the Breadth page's Recent History
table and inspect the stocks that produced that exact count. The dialog has a
compact stock list and an expandable IBD-group summary. It works for every
breadth-enabled market in both the live application and the static site.

The feature must preserve the existing breadth formulas and aggregate history.
It adds a canonical contributor snapshot beside each aggregate row so the
displayed count, stock list, and group totals all come from the same calculation.

This design extends the revision-3 market-calibrated calculation defined in:

- `docs/superpowers/specs/2026-08-25-shared-market-breadth-design.md`
- `docs/superpowers/specs/2026-08-27-market-calibrated-breadth-thresholds-design.md`

It does not introduce a selectable calculation version or preserve an alternate
formula. `calculation_revision` remains `3`. The contributor payload's schema
identifier is an API/static-file compatibility identifier, not a formula
revision.

## Product Decisions

- Enable drilldown for the latest 20 completed breadth sessions in every market
  whose market-catalog entry declares `breadth=True`.
- Make the ten Primary/Secondary membership counts and the 10x ATR count
  interactive.
- Do not make ratios, T2108, broad-universe counts, health-bar values, or other
  context metrics interactive in this feature.
- Show a compact stock table containing ticker, company, frozen IBD group,
  formula-aligned qualifying value, and one-day adjusted change.
- Add an expandable IBD Groups tab to the same dialog.
- Freeze company name and IBD group into each dated contributor snapshot. A
  later classification change must not rewrite an earlier snapshot.
- Put unclassified stocks in `No Group` and keep that group last in the group
  summary.
- Persist contributor snapshots produced by the canonical engine. Do not
  recalculate formulas when a cell is clicked and do not embed all contributors
  in the main breadth-history payload.
- Keep live and static rendering on one shared component and one shared payload
  contract.
- Keep the existing aggregate breadth API, database rows, formulas, and
  calculation revision backward compatible.

## Interactive Indicators

The shared indicator registry is the authority for clickability, labels,
direction, aggregate field mapping, qualifying-value formatting, and sorting.
The table, dialog, API validation, exporter, and reconciliation tests use this
registry rather than independent lists.

| Aggregate field | Dialog label | Snapshot signal | Qualifying value | Stock order |
|---|---|---|---|---|
| `stocks_up_4pct` | Up 4%+ Today | `up_4pct` | 1-day adjusted return | highest first |
| `stocks_down_4pct` | Down 4%+ Today | `down_4pct` | 1-day adjusted return | lowest first |
| `stocks_up_25pct_quarter` | Up 25%+ Quarter | `up_25pct_quarter` | gain from trailing 65-session low | highest first |
| `stocks_down_25pct_quarter` | Down 25%+ Quarter | `down_25pct_quarter` | decline from trailing 65-session high | lowest first |
| `stocks_up_25pct_month` | Up 25%+ Month | `up_25pct_month` | 20-session adjusted return | highest first |
| `stocks_down_25pct_month` | Down 25%+ Month | `down_25pct_month` | 20-session adjusted return | lowest first |
| `stocks_up_50pct_month` | Up 50%+ Month | `up_50pct_month` | 20-session adjusted return | highest first |
| `stocks_down_50pct_month` | Down 50%+ Month | `down_50pct_month` | 20-session adjusted return | lowest first |
| `stocks_up_13pct_34days` | Up 13%+ / 34 Days | `up_13pct_34days` | gain from trailing 34-session low | highest first |
| `stocks_down_13pct_34days` | Down 13%+ / 34 Days | `down_13pct_34days` | decline from trailing 34-session high | lowest first |
| `atr_10x_extension_count` | 10x ATR Extension | `atr_10x_extension` | extension ratio in ATR multiples | highest first |

The qualifying values use the same unrounded features used by the canonical
predicate. Rounding occurs only during serialization or display. The one-day
change column always shows adjusted close-to-close return, independent of the
selected signal.

A stock can qualify for several signals on one date. It is stored once for that
date, with each qualifying signal and value in its signal map.

## Selected Architecture

### Canonical calculation output

Extend the pure breadth domain output with contributor values; do not add a
second attribution calculator. For every symbol and target date, the existing
engine already produces `SymbolBreadthSignals`. The same feature row supplies
the qualifying values and one-day return.

The engine emits two coordinated results for a target date:

1. the existing `BreadthDailyResult` aggregate; and
2. a `BreadthContributorSnapshotResult` containing only symbols that qualify
   for at least one interactive indicator.

The contributor result contains:

```text
market
calculation_date
calculation_revision
contributors[]:
    symbol
    company_name
    ibd_industry_group
    daily_change_pct
    signals: {signal_key: qualifying_value}
```

Formula functions remain responsible for features and signal predicates.
Engine orchestration decides which qualifying values to include. Persistence,
the API, and the static exporter consume the result but may not recreate signal
membership from prices.

Metadata is resolved before calculation through a date-effective snapshot
loader. It normalizes blank classifications to `No Group`. Future daily runs
freeze the metadata known for that calculation date. Historical backfill uses
canonical point-in-time universe/reference metadata; when a group is absent for
that date it records `No Group` rather than substituting a newer classification.

### Persistence

Use a parent snapshot table plus contributor rows:

```text
market_breadth_contributor_snapshots
    id
    market
    date
    calculation_revision
    schema_id                         # breadth-contributors-v1
    created_at
    UNIQUE (market, date)

market_breadth_contributors
    id
    snapshot_id                       # FK with cascade delete
    symbol
    company_name
    ibd_industry_group
    daily_change_pct
    signals_json
    UNIQUE (snapshot_id, symbol)
```

The parent has a composite foreign key to the aggregate row's `(market, date)`
with cascade delete. Revision is a stale-data guard, not part of the identity,
so only one contributor snapshot can exist for a market/date. Index the parent
by `(market, date)` and children by `snapshot_id`. A signal index is unnecessary
because the read path loads one date and filters its small set of contributor
rows in memory. `signals_json` is a map of known registry keys to finite numeric
qualifying values; unknown keys, booleans, nulls, and nonfinite numbers are
invalid.

The parent is required even when there are no contributors. Its presence means
the date was calculated successfully; an absent parent means drilldown data is
unavailable. The aggregate and its parent/child contributor snapshot are
replaced in one database transaction. Before commit, persistence verifies that
the number of contributor rows containing each signal equals its aggregate
count. Any mismatch aborts the whole date write.

Retain contributor snapshots for the latest 20 completed breadth sessions per
market. Retention applies only to contributor data; existing aggregate breadth
history remains unchanged. Pruning runs after the new date commits and never
deletes the just-written or still-retained sessions.

### Live API

Add two read-only endpoints under the existing breadth route:

```text
GET /v1/breadth/contributors/index?market=US
GET /v1/breadth/contributors?market=US&date=2026-08-28
```

The index advertises the available dates, schema identifier, and calculation
revision for at most the latest 20 completed sessions:

```json
{
  "schema": "breadth-contributors-v1",
  "market": "US",
  "calculation_revision": 3,
  "dates": ["2026-08-28", "2026-08-27"]
}
```

The dates are newest first. The date endpoint returns one
`breadth-contributors-v1` document:

```json
{
  "schema": "breadth-contributors-v1",
  "market": "US",
  "date": "2026-08-28",
  "calculation_revision": 3,
  "contributors": [
    {
      "symbol": "EXAMPLE",
      "company_name": "Example Company",
      "ibd_industry_group": "Semiconductors",
      "daily_change_pct": 6.41,
      "signals": {
        "up_4pct": 6.41,
        "up_25pct_month": 31.72
      }
    }
  ]
}
```

The endpoint rejects unsupported markets through the existing breadth market
guard. A date that is not advertised returns `404` as unavailable. A stored
snapshot that conflicts with the active schema, calculation revision, aggregate
row, or signal counts returns `409` as inconsistent data and is omitted from
the index. Neither condition changes the aggregate breadth response.

The frontend loads the index with the breadth page. It requests a date document
only after the first eligible cell for that date is clicked, then caches the
document by market/date/schema/revision. Clicking another metric in the same
row filters the cached contributors without another request.

### Static contract

Keep the main market breadth document small. Export contributor availability
and date shards separately:

```text
markets/us/breadth/contributors/index.json
markets/us/breadth/contributors/2026-08-28.json
```

The index and date document use the same fields and semantics as the live API.
Paths are generated for every breadth-enabled market. Static validation checks:

- index market, schema identifier, and calculation revision;
- no more than the latest 20 completed sessions are advertised;
- every advertised shard exists and matches its path's market and date;
- every signal count reconciles with the corresponding aggregate row; and
- no contributor shard outside the retained set is published.

Contributor files are additive. A static bundle without them remains valid and
renders the aggregate table with noninteractive cells. A new bundle advertises
drilldown only after its index and all listed shards validate. An optional
contributor failure must not remove a previously valid market or invalidate its
aggregate breadth page.

The existing static-only ±4% group-attribution calculation must stop evaluating
prices independently. If the broader `By Group` page remains visible, its data
is derived from the canonical contributor snapshots so it cannot disagree with
the clicked-cell dialog.

## User Interface

### Recent History table

`BreadthHistoryTable` receives contributor availability and an open-dialog
callback. For an advertised date, a nonzero interactive metric renders as a
full-cell button while preserving the existing heatmap background and white
text. Hover and keyboard focus add a visible outline, and the tooltip reads
`View N contributing stocks`.

The following remain plain cells:

- zero counts;
- unavailable or inconsistent contributor dates;
- sessions older than the latest 20 available sessions; and
- nonmembership fields such as five- and ten-day ratios, T2108, and Broad
  Universe.

The table keeps its Primary, Secondary, and Context group boundaries. Making a
cell interactive must not widen the table or reintroduce horizontal scrolling
at the supported desktop layout.

### Contributor dialog

Use one shared dialog component in the live and static pages. It is centered on
desktop and near full-screen on narrow mobile viewports. Its header shows the
selected metric label, date, and aggregate count. Closing the dialog returns
focus to the cell that opened it.

The dialog contains two tabs:

1. **Stocks** — compact columns for ticker, company, frozen IBD group,
   qualifying value, and one-day change. Positive and negative values use the
   existing breadth color language. Long company/group text truncates with a
   tooltip rather than widening the dialog.
2. **IBD Groups** — rows show group name, contributor count, and share of the
   selected signal. Groups sort by count descending and then name; `No Group`
   is always last. Each row expands to the same compact stock fields and uses
   the selected signal's stock ordering.

The selected signal controls filtering, label text, qualifying-value format,
and order through the shared indicator registry. Down-signal rows show the most
negative qualifying value first. The 10x ATR value is formatted as an `x`
multiple; return and distance values are formatted as percentages.

Loading, retryable failure, empty, and unavailable states stay inside the
dialog. A failed contributor request does not replace or hide the Recent
History table. If a payload count disagrees with the clicked aggregate despite
server/export validation, the dialog shows an inconsistency warning and does
not present the list as authoritative.

## Data Flow

### Daily calculation

```text
point-in-time universe, metadata, OHLCV, market policy
    -> canonical breadth engine
    -> aggregate result + contributor snapshot result
    -> reconcile all 11 signal counts
    -> atomically replace aggregate and contributor snapshot
    -> prune contributor snapshots beyond latest 20 sessions
    -> live availability/date endpoints and static date shards
    -> shared table and contributor dialog
```

### Dialog interaction

```text
page loads contributor index
    -> eligible table cells become buttons
    -> user clicks one metric/date
    -> fetch or reuse cached date document
    -> registry filters and sorts matching contributors
    -> Stocks or IBD Groups tab renders from the same filtered list
```

## Migration and Rollout

The database migration is additive: create the two contributor tables and
indexes without modifying `market_breadth` or changing calculation revision 3.
Deploy readers so missing snapshots are treated as unavailable, then enable the
writer/backfill.

Run a one-time backfill for the latest 20 completed canonical breadth sessions
in every breadth-enabled market:

1. load the same point-in-time universe, local-currency policy, OHLCV, and
   date-effective metadata required by revision 3;
2. run the canonical engine for the target sessions;
3. compare all 11 reconstructed contributor counts with the existing aggregate
   rows; and
4. commit a market's 20 snapshots only when every target date reconciles.

If any date fails, leave that market's contributor feature unavailable and
produce an operator report identifying the market, date, signal, aggregate
count, and reconstructed count. Never alter existing aggregate history merely
to make a contributor backfill reconcile.

After backfill, the normal breadth writer stores aggregate and contributor data
for each new session in one transaction. The static deployment remains
backward compatible: old artifacts continue working without drilldowns, and
new contributor files are activated only after validation. This prevents an
optional new contract from repeating the prior failure mode where a static run
removed otherwise valid markets.

## Error Handling and Observability

- Formula or count reconciliation failure aborts the date transaction and logs
  structured market/date/signal/count details.
- A missing date snapshot is a feature-availability condition, not an aggregate
  breadth failure.
- Schema or calculation-revision mismatch is treated as inconsistent data and
  is never silently accepted.
- Invalid contributor metadata uses `No Group`; invalid required price features
  continue to follow the canonical metric-eligibility rules.
- Live API and static validator reject duplicate symbols within one snapshot.
- Backfill reports success/failure by market and the number of committed dates.
- UI request failure is retryable in the dialog and does not discard a
  previously cached valid date document.

## Verification Strategy

### Domain and persistence tests

- Every one of the 11 signal keys uses the existing canonical predicate and the
  documented qualifying value.
- Exact formula boundaries produce the same contributor membership and
  aggregate count.
- A stock that qualifies for multiple signals is stored once with multiple
  signal entries.
- Frozen company/group metadata remains unchanged when the current
  classification later changes.
- Missing classification becomes `No Group`.
- Each signal's contributor count exactly equals its aggregate field.
- A zero-contributor day still creates a complete parent snapshot.
- Reconciliation failure rolls back aggregate and contributor writes.
- Retention keeps exactly the latest 20 completed sessions per market without
  changing aggregate history.

### API and static tests

- All and only breadth-enabled markets pass the market guard and export paths.
- Index and date documents have live/static schema parity.
- Unsupported, unavailable, and revision-mismatched requests have distinct,
  stable responses.
- Static validation detects missing shards, duplicate symbols, wrong
  market/date, revision mismatch, excess dates, and per-signal count mismatch.
- A contributor-export failure does not remove a valid aggregate market from
  the static site.
- A legacy static bundle without contributor files still renders normally.

### Frontend tests

- Only eligible, nonzero cells in advertised sessions are keyboard- and
  pointer-interactive.
- Clicking a cell opens the correct metric/date/count and lazily loads one date.
- Switching metrics in the same row reuses the cached date document.
- Stocks use the correct qualifier label, format, and direction-aware ordering.
- Group counts/shares reconcile with the filtered stock list, expand correctly,
  and keep `No Group` last.
- Loading, retry, empty, unavailable, and inconsistent states are contained in
  the dialog.
- Focus returns to the source cell after close.
- The shared dialog works on live and static pages and remains usable on mobile.
- Interactivity does not widen the Recent History table at the supported
  desktop viewport.

### End-to-end acceptance

For a sampled up signal, down signal, and ATR signal in US and at least one
non-US market:

1. the clicked count equals the Stocks-tab row count;
2. expanded group stock counts sum to the same total;
3. live and static payloads contain the same contributors for the same
   market/date/revision; and
4. a session older than the retained 20 remains visible as aggregate history
   but is not interactive.

## Out of Scope

- Changing any revision-3 breadth formula, threshold, eligible universe, or
  aggregate field.
- Contributor drilldown for ratios, advancing/declining, 52-week highs/lows,
  T2108, or Broad Universe.
- More than 20 retained contributor sessions per market.
- Clipboard export, liquidity columns, charts inside the dialog, or navigation
  from a ticker to another page.
- Reclassifying old snapshots after an IBD-group mapping changes.
- A second calculation path for static export or UI requests.

## Success Criteria

- Users can open any supported nonzero count from the latest 20 sessions and
  see the exact stocks behind it.
- Stocks and expandable IBD groups reconcile exactly to the displayed count.
- Company/group classification is historically stable after snapshot creation.
- All breadth-enabled markets receive identical behavior, with `No Group`
  covering missing classifications.
- Live and static pages share the contract and UI behavior.
- Aggregate breadth history and legacy static bundles continue to work without
  contributor data.
- No click-time formula calculation or independent attribution formula remains.
