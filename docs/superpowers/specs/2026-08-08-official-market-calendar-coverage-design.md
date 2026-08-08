# Official Market Calendar Coverage Design

**Date:** 2026-08-08

## Objective

Make every production calculation date depend on an explicitly verified market
calendar while retaining the pinned Python calendar libraries as useful schedule
engines. Replace the silent CN/SG weekday fallback, preserve historical provider
behavior, publish provisional schedules through 2030 for planning, and make
calendar maintenance visible before verified future coverage expires.

## Decisions

- The official exchange calendar is the source of truth for session membership.
- Calendar data is updated when an exchange publishes or revises its schedule,
  normally once per year. A scheduled audit runs weekly year-round.
- Audit warnings never block CI or publication.
- A market operation hard-fails only when its requested calculation date is later
  than that market's `verified_through` date.
- Existing historical provider data remains usable. The new boundary protects the
  unverified future; it is not a retrospective lower bound.
- Provisional provider-derived calendars are generated through 2030, but are not
  accepted as verified production dates.
- The contract applies to all supported Markets and remains keyed by the Market's
  canonical primary MIC unless a caller explicitly requests another MIC.

## Alternatives Considered

### Closure overrides only

Keep a small list of dates where provider libraries disagree with official
exchanges. This is compact, but it leaves the provider's implicit future bounds
and assumptions as the real contract and cannot express an auditable expiry.

### Versioned official session manifests

Check in normalized, source-attributed calendar manifests and put an explicit
verified boundary in front of the provider adapters. This is the selected design
because it is deterministic, reviewable, testable, and independent of runtime
network access.

### Live calendar vendor

Resolve sessions from a hosted market-data/calendar API. This may be fresher, but
adds credentials, availability, cost, and runtime network dependencies to every
calendar decision. It is not selected.

## Data Model

Calendar policy lives under `backend/app/domain/markets/` and checked-in calendar
data lives under `backend/data/market_calendars/`.

The root index records one entry per canonical Market:

```json
{
  "schema_version": 1,
  "generated_at": "2026-08-08",
  "provisional_through": "2030-12-31",
  "markets": {
    "KR": {
      "mic": "XKRX",
      "verified_through": "2026-12-31",
      "source": {
        "name": "Korea Exchange market calendar",
        "url": "https://global.krx.co.kr/contents/GLB/05/0501/0501060000/GLB0501060000.jsp",
        "checked_at": "2026-08-08"
      },
      "years": {
        "2026": "kr/2026.json",
        "2027": "kr/2027.provisional.json"
      }
    }
  }
}
```

Each annual file records:

- `market`, canonical `mic`, and `year`;
- `status`: `official` or `provisional`;
- the source URL and retrieval/check date;
- normalized session dates;
- optional close-time exceptions when an official schedule publishes them;
- the pinned provider name and version used to generate provisional data.

Official files are hand-reviewable normalized snapshots. Runtime code never
scrapes exchange websites. Provisional files are reproducibly generated from the
pinned Python packages and exist to expose future assumptions and produce useful
diffs when official data becomes available.

## Runtime Semantics

`MarketCalendarService` receives a calendar-coverage registry in addition to its
provider adapters.

For `is_trading_day(market, day)`, `trading_days(market, start, end)`, and calls
that derive anchors:

1. Normalize Market/MIC facts through the existing Market Catalog.
2. Validate the requested calculation date against `verified_through`.
3. If the requested date is later, raise `CalendarCoverageExpired` containing
   Market, requested date, verified-through date, source URL, and update guidance.
4. Inside verified coverage, official session membership overrides the provider.
5. Historical dates not represented by checked-in annual files continue through
   the pinned provider so existing historical calculations remain compatible.

For a range, `end` is the requested calculation date. Lookback dates before the
first checked-in official year may still use provider history. For
`last_completed_trading_day`, the Market-local current date is checked before a
session is selected. `session_anchors` inherits the as-of guard.

The CN/SG weekday-bounds fallback is removed for future dates. It may not turn an
unverified weekday into a production trading session. Intraday open/close logic
continues to use provider schedules where available; checked-in exceptional close
times override provider hours.

## Coverage and Warning Policy

The audit computes calendar days between its evaluation date and each Market's
`verified_through` date and emits GitHub Actions `warning` annotations at these
thresholds:

- 180 days remaining;
- 90 days remaining;
- 60 days remaining;
- 30 days remaining;
- expired.

Thresholds are descriptive severity bands, not separate repeated events. Every
warning remains non-blocking. The report also warns when:

- the checked-in provisional horizon ends before 2030-12-31;
- a manifest is missing source provenance;
- an official session file differs structurally from its index metadata;
- a generated provisional file is not reproducible with the pinned provider;
- an official year and its provisional predecessor differ, so a reviewer can
  inspect the expected holiday changes.

Invalid manifest schema or corrupt calendar data is a test failure because the
repository artifact itself is unusable. Expiring or expired coverage is only an
audit warning; production calendar access enforces expiry at the requested date.

## Weekly Automation

Add `.github/workflows/market-calendar-audit.yml` with a weekly schedule and
manual dispatch. It installs the minimum backend dependencies and runs a CLI that:

1. validates every supported Market is present;
2. validates official and provisional manifests;
3. checks warning thresholds and the 2030 provisional horizon;
4. writes a Markdown table to `GITHUB_STEP_SUMMARY`;
5. emits non-blocking Actions warning annotations.

The static-site workflow runs the same report in non-blocking mode before its
market matrix. A warning is therefore visible both in the dedicated weekly audit
and in normal publication runs. Static export code is not taught to suppress
`CalendarCoverageExpired`; if the selected calculation date is beyond verified
coverage, that market's export fails normally.

## Historical Breadth Eligibility

Static breadth history must not reuse the Market RS current-price percentage as
both its threshold and its universe definition. Those are different contracts:

- current-price coverage asks whether enough of today's active Market universe
  has a usable current adjusted price;
- historical-breadth eligibility asks which symbols can mathematically contribute
  a 63-session breadth observation on each historical calculation date.

The existing `BreadthHistoryPriceCoverageService` becomes the authoritative
preflight for breadth readiness. For each calculation date, a symbol is breadth
eligible only when it:

1. belongs to the resolved point-in-time Market universe for that date;
2. is supported by the configured price-symbol provider;
3. has an exact valid OHLC observation on that date; and
4. has at least 70 valid observations through that date, which is the calculator's
   existing requirement for a 63-session change.

This is a date-specific denominator. A recent listing can become eligible later
in the backfill window, and a currently active symbol is not retroactively counted
before it joined the Market universe. Symbols with missing or incomplete history
remain visible in diagnostics and in the separate price-history refresh result;
they are not misclassified as calculation failures for dates on which they could
not contribute a valid breadth observation.

`BreadthCalculatorService.backfill_range` accepts the resolved candidate universe
and returns `eligible_stocks_by_date` alongside `scanned_stocks_by_date`. Static
breadth assessment then validates the scanned count against the eligible count for
the same date. Calculation errors remain hard failures. A non-empty date with zero
eligible symbols also remains a hard failure, so an empty or broken price cache
cannot pass by shrinking the denominator to zero.

The current-price threshold remains unchanged for the daily-price and Market RS
gates. Historical breadth gets a separate policy name and diagnostics, with no
implicit call to `market_current_price_min_coverage`. Existing breadth records are
revalidated against recomputed date-specific eligibility before being reused.

The static artifact status records, per backfill:

- point-in-time candidate count and universe policy;
- eligible count and scanned count by date;
- unsupported-symbol count;
- insufficient-history count;
- exact-date price-gap count;
- a bounded sample for each exclusion reason.

If point-in-time membership cannot be reconstructed, the existing explicit
current-active fallback policy may be used, but the fallback is named in status
diagnostics. It must not be presented as point-in-time coverage.

## Maintenance Procedure

`docs/OPERATIONS.md` will document the annual workflow:

1. Run the calendar audit weekly; no routine manual weekly edit is required.
2. When an exchange publishes or revises a schedule, capture the official source
   URL and publication/check date.
3. Generate the candidate normalized year file.
4. Review its diff against the provisional file and the official publication.
5. Promote that year to `official`, advance `verified_through`, and regenerate
   provisional schedules so coverage still reaches 2030.
6. Run manifest, calendar-service, and static-export date-resolution tests.

Emergency closure notices use the same procedure and may shorten or amend an
already official year. Price-bar absence can trigger investigation but is never
itself authoritative calendar evidence.

## Error Handling and Compatibility

- `CalendarCoverageExpired` is distinct from provider bounds and schedule errors.
- Error text includes an actionable path to the maintenance documentation.
- Warning/audit commands return success for all age states, including expiry.
- Schema corruption, unsupported Markets, duplicate sessions, weekend sessions
  without explicit authorization, and mismatched Market/MIC metadata return
  failure.
- Existing dependency injection for fake providers and session overrides remains
  available so unrelated unit tests do not require filesystem fixtures.

## Test Strategy

Unit tests cover:

- manifest parsing and schema validation;
- all supported Markets in the index;
- official-over-provider precedence for known 2026 KR, TW, SG, MY, and CN dates;
- provider history before the checked-in official window;
- exact-boundary success and next-day `CalendarCoverageExpired` failure;
- range guards using the range end as the calculation date;
- no CN/SG weekday fallback after verified coverage;
- 180/90/60/30/expired warning bands always returning success;
- provisional horizon validation through 2030;
- deterministic CLI Markdown and Actions annotations.

Breadth-specific tests cover:

- current active symbols excluded from dates before their point-in-time entry;
- recent listings becoming eligible only after their seventieth observation;
- exact-date gaps excluded from eligibility but reported diagnostically;
- calculation errors still hard-failing an otherwise eligible date;
- a zero-eligible date failing rather than passing vacuously;
- different eligible denominators across a multi-date backfill;
- current-price thresholds remaining unchanged and independent;
- US, DE, and HK regression fixtures that previously compared scanned history to
  the full current active universe.

Workflow tests verify the weekly schedule, manual dispatch, non-blocking warning
step, and static-site integration. Existing Market calendar and static artifact
tests remain regression coverage.

## Out of Scope

- Purchasing or integrating a live calendar vendor.
- Treating missing price bars as proof of a closure.
- Automatically committing scraped exchange pages.
- Solving AU price-coverage or CN bootstrap-duration failures; those remain
  independent fixes identified by the workflow review.
