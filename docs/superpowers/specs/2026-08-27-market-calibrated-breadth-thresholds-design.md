# Market-Calibrated Breadth Thresholds Design

**Date:** 2026-08-27

## Objective

Replace the revision-2 StockBee USD-liquidity policy with fixed,
market-calibrated thresholds expressed in each market's primary trading
currency. Remove historical FX from breadth calculation, preserve one shared
calculation engine for live, backfill, attribution, and static workflows, and
cut all breadth-enabled markets over to calculation revision 3.

This design supersedes the USD-normalized liquidity, historical-FX, and
revision-2 cutover decisions in
`docs/superpowers/specs/2026-08-25-shared-market-breadth-design.md`. All other
formula, universe, UI, and API decisions in that document remain in force.

## Product Decisions

- StockBee eligibility is market-relative rather than normalized to one USD
  liquidity threshold.
- Every breadth-enabled market uses one fixed, documented policy containing:
  primary currency, minimum 20-session average traded value, minimum daily
  share volume, and minimum raw reference price 20 sessions ago.
- The policy values are initial settings. They are deliberately rounded and
  loosely calibrated; runtime calculations do not optimize or recalculate them.
- The existing US settings remain numerically unchanged, but US moves to
  calculation revision 3 with every other breadth-enabled market.
- Historical and current FX are not inputs to any breadth formula.
- FX services and stored FX data remain available to fundamentals, valuation,
  and other non-breadth consumers.
- A listing whose currency differs from its market policy currency is excluded
  from StockBee eligibility only. It can still contribute to advancing,
  declining, T2108, 52-week high/low, and ATR context indicators.
- AU, SG, and MY remain breadth-disabled. Runtime bootstrap, daily pipelines,
  and static export must not calculate or require breadth or breadth-derived
  exposure for them.
- Revision 2 is not retained as a selectable methodology. Revision guards hide
  old rows, and atomic rebuild activation replaces them with revision-3 rows.

## Analysis-Only Calibration

The calibration was a one-time analysis performed on 2026-08-27. It is not an
application service, scheduled task, command, or committed calibration tool.
Only the selected policy and this evidence are permanent.

### Inputs

The analysis used the latest market-specific assets from the GitHub releases:

- `daily-price-data`: two-year raw OHLCV bundles;
- `weekly-reference-data`: active market universe and primary currency.

The following daily-price assets were used:

| Market | Currency | Daily-price asset | As-of date | Complete recent features |
|---|---|---|---:|---:|
| US | USD | `daily-price-us-20260826.json.gz` | 2026-08-26 | 9,995 |
| CA | CAD | `daily-price-ca-20260826.json.gz` | 2026-08-26 | 3,656 |
| DE | EUR | `daily-price-de-20260825.json.gz` | 2026-08-25 | 1,415 |
| HK | HKD | `daily-price-hk-20260826.json.gz` | 2026-08-26 | 2,762 |
| IN | INR | `daily-price-in-20260826.json.gz` | 2026-08-26 | 4,688 |
| JP | JPY | `daily-price-jp-20260826.json.gz` | 2026-08-26 | 3,708 |
| KR | KRW | `daily-price-kr-20260826.json.gz` | 2026-08-26 | 2,683 |
| TW | TWD | `daily-price-tw-20260826.json.gz` | 2026-08-26 | 1,085 |
| CN | CNY | `daily-price-cn-20260805.json.gz` | 2026-08-05 | 5,197 |

The corresponding `weekly-reference-*-20260822-*.json.gz` assets supplied the
active universe and currency. Those artifacts predate explicit common-stock
classification in their serialized rows. The analysis therefore followed the
current importer default: active non-manual rows not explicitly marked false
were treated as common stocks. This is acceptable for initial calibration but
is recorded as a limitation. Runtime revision-3 calculation continues to use
the authoritative point-in-time `is_common_stock` classification.

### Method

For each symbol with at least 21 price sessions and a latest bar no more than
seven calendar days behind the bundle as-of date, the analysis calculated:

```text
adtv20_local = mean(raw_close * volume over the latest 20 sessions)
typical_volume = median(volume over the latest 20 sessions)
reference_price_local = raw close exactly 20 sessions earlier
```

The existing US policy produced these reference pass rates:

- ADTV eligibility: 7,693 / 9,995 = 76.97%;
- typical volume at least 100,000 among liquid stocks: 66.62%;
- reference price at least USD 5 among liquid stocks: 85.92%.

Each non-US raw threshold was selected at the corresponding market quantile,
then rounded to a simple local value. The target was directional, not an
acceptance gate. No threshold is recalculated at runtime, and no test asserts
that future market coverage must remain near these percentages.

### Selected Initial Policies

| Market | Currency | Min ADTV20 local | Min daily shares | Min reference price local | ADTV pass | Typical-volume pass among liquid | Reference-price pass among liquid |
|---|---|---:|---:|---:|---:|---:|---:|
| US | USD | 250,000 | 100,000 | 5.00 | 77.0% | 66.6% | 85.9% |
| CA | CAD | 5,000 | 5,000 | 0.30 | 75.7% | 67.6% | 86.5% |
| DE | EUR | 5,000 | 300 | 8.00 | 74.8% | 68.4% | 85.8% |
| HK | HKD | 20,000 | 150,000 | 0.20 | 77.4% | 68.2% | 86.4% |
| IN | INR | 100,000 | 15,000 | 15.00 | 76.5% | 66.2% | 86.1% |
| JP | JPY | 8,000,000 | 50,000 | 500 | 77.0% | 64.0% | 86.6% |
| KR | KRW | 100,000,000 | 50,000 | 2,000 | 74.7% | 66.1% | 82.3% |
| TW | TWD | 3,500,000 | 400,000 | 20.00 | 76.6% | 66.5% | 84.5% |
| CN | CNY | 50,000,000 | 10,000,000 | 5.00 | 80.0% | 60.2% | 86.4% |

The calibration's median-volume measurement stabilizes the one-time suggestion.
The production StockBee daily predicate remains unchanged in shape: it compares
the target session's actual volume to the fixed policy threshold and requires
target-session volume to exceed prior-session volume.

## Permanent Architecture

### Market policy

Add one immutable `BreadthMarketPolicy` value with this contract:

```python
@dataclass(frozen=True, slots=True)
class BreadthMarketPolicy:
    market: str
    currency: str
    min_adtv_local: float
    min_daily_volume: int
    min_month_reference_price_local: float
```

A single registry owns the nine policies in the selected table. Lookup accepts
a normalized breadth-enabled market code and fails for unsupported or missing
entries. Tests enforce exact key parity with the market catalog's `breadth`
capability.

`BreadthFormulaPolicy` retains formula-wide settings such as ATR period and
extension threshold. It no longer owns USD liquidity, USD reference-price, or
FX-age settings.

### Local-currency features

`prepare_feature_frame` no longer accepts an FX series. It prepares:

```text
raw_close_local = raw close
traded_value_local = raw_close_local * volume
adtv20_local = rolling 20-session mean of traded_value_local
raw_close_local_20 = raw close shifted by 20 sessions
```

Adjusted OHLC continues to drive returns, rolling extrema, moving averages,
ATR, T2108, and high/low signals exactly as in revision 2.

For a symbol whose currency matches the market policy:

```text
stockbee_liquidity_eligible = adtv20_local >= min_adtv_local
stockbee_month_eligible =
    stockbee_liquidity_eligible
    and raw_close_local_20 >= min_month_reference_price_local
```

The daily +4%/-4% predicates require target-session volume greater than or
equal to `min_daily_volume` and greater than prior-session volume.

For a symbol whose currency does not match the policy currency, every StockBee
eligibility flag is false. Broad context eligibility is evaluated normally.
The symbol is not silently converted or compared against the wrong currency.

### Shared engine and adapters

`BreadthEngineRequest` carries a `BreadthMarketPolicy` instead of
`fx_by_currency`. The pure engine remains provider-free and database-free.

`BreadthCalculatorService` stops loading historical FX and delegates with the
policy resolved for its market. Live calculation, gap fill, historical rebuild,
group attribution, and static section building continue to use the same engine
and policy registry. No adapter may define its own thresholds.

The general `FXService`, `fx_rates` table, and fundamentals currency conversion
remain unchanged because they serve non-breadth domains.

### Capability gating

The market catalog remains authoritative. Bootstrap plans, daily market
pipelines, and static export include breadth and breadth-derived exposure only
when `capabilities.breadth` is true. For breadth-disabled markets, snapshot and
static publication must not fail merely because breadth or exposure is absent.

This gating change does not enable new breadth markets. It corrects orchestration
to match the existing catalog and frontend behavior.

## Revision 3 and Existing Databases

Set `CURRENT_BREADTH_CALCULATION_REVISION = 3`. Revision is a stale-data guard,
not a user-selectable formula version.

There is no new database column and no Alembic schema change. Existing rows are
handled by the existing shadow rebuild workflow:

1. Revision-3 code causes revision-aware reads to ignore revision-2 rows.
2. Rebuild every breadth-enabled market/date into the staging tables using the
   fixed market policies.
3. Validate manifests, denominators, ratios, signatures, and revision 3.
4. Pause breadth-dependent writers and take the operational backup.
5. Atomically activate the staging dataset; activation deletes all existing
   `market_breadth` rows and inserts only validated revision-3 rows.
6. Rebuild `market_exposure`, group attribution, UI snapshots, and static
   artifacts from revision-3 breadth.
7. Clear breadth/exposure snapshot caches and resume writers.

US participates in the same purge and rebuild even though its numerical
thresholds are unchanged. A deployment with no completed revision-3 rebuild
returns unavailable breadth rather than serving revision-2 data.

Static artifact validation requires revision 3 and a `breadth-r3` source marker.
Revision-1 or revision-2 fallbacks must not be published as current data. The
deployment may retain diagnostics, but an affected market is reported
unavailable until a current revision-3 artifact exists.

## API and UI Contract

All existing breadth field names and types remain unchanged. Update the
`calculation_revision` description and fixtures from 2 to 3.

Tooltips and documentation replace USD language with the selected market's
local thresholds. The breadth response remains flat; the permanent threshold
registry is server-side policy and does not require a new public API field.

The UI continues to display broad context indicators even when a
currency-mismatched listing is ineligible for StockBee metrics. Denominators
make the difference explicit.

## Error Handling

- Missing or invalid raw local prices exclude the symbol only from affected
  StockBee metrics.
- Missing or invalid adjusted history follows existing metric-specific
  eligibility rules.
- A currency mismatch excludes StockBee eligibility but never fails the entire
  market/date calculation.
- A breadth-enabled market with no registered policy fails before calculation.
- A breadth-disabled market skips breadth-dependent workflow stages.
- Static publication never substitutes an older calculation revision.
- A market/date result still commits atomically or not at all.

## Testing

### Policy tests

- Registry keys exactly equal catalog breadth-enabled market codes.
- Every policy has the expected market, currency, and selected threshold values.
- Unsupported-market lookup fails clearly.
- US retains 250,000 ADTV, 100,000 shares, and USD 5.

### Formula and engine tests

- ADTV uses raw local close times volume with no FX input.
- Every local threshold passes at equality and fails immediately below it.
- The daily volume predicate uses the market-specific threshold.
- Monthly reference-price eligibility uses the market-specific local threshold.
- Currency mismatch disables only StockBee eligibility.
- Advancing/declining, T2108, 52-week high/low, and ATR remain available for a
  currency-mismatched symbol.
- The engine and calculator do not call `FXService` for breadth.
- All canonical results carry calculation revision 3.

### Workflow and migration tests

- Live, backfill, attribution, and static fixtures produce identical results
  from the same market policy.
- Bootstrap, daily pipeline, and static export omit breadth-dependent stages for
  AU, SG, and MY.
- Revision-aware reads reject revision 2.
- Shadow rebuild validation and activation require revision 3.
- Static validation rejects revision-1/revision-2 fallback artifacts.
- Existing additive API fields remain backward compatible.

## Documentation

- This design is the authoritative calibration record.
- User-facing breadth documentation lists each fixed market policy and explains
  that thresholds are local, initial, and manually maintained.
- Formula tooltips identify local ADTV, local reference price, and local daily
  volume without referring to FX.
- Release notes explain the revision-3 rebuild and temporary unavailability
  behavior for installations upgrading an existing database.

## Completion Criteria

- Breadth has no runtime or static dependency on historical FX.
- One registry owns fixed policies for every breadth-enabled market.
- All live, backfill, attribution, and static calculations use the same policy.
- Every served breadth row and current static artifact is revision 3.
- Revision-2 data is atomically replaced, not exposed as a parallel formula.
- Breadth-disabled markets are not blocked by missing breadth or exposure.
- Thresholds and calibration evidence are documented.
- Relevant backend, migration/rebuild, static export, and frontend tests pass.

## Non-Goals

- Runtime percentile calibration or automatic threshold adjustment.
- A committed calibration CLI or scheduled calibration job.
- Cross-market conversion of breadth liquidity into USD.
- Removing FX from fundamentals, valuation, or other non-breadth domains.
- Enabling breadth for AU, SG, or MY.
- Redesigning StockBee signal percentages, ratios, T2108, high/low, or ATR
  formulas.
