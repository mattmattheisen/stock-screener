# Calendar and Breadth Thermo-Review Remediation Design

**Date:** 2026-08-09

## Objective

Address the structural findings from the thermo-nuclear code-quality review
without changing static-site behavior, persisted breadth semantics, calendar
coverage policy, or existing `BreadthCalculatorService.backfill_range()` callers.

## Constraints

- Retain backward compatibility for `BreadthCalculatorService.backfill_range()`.
- Preserve date-specific historical-breadth eligibility and deterministic
  eligibility signatures.
- Preserve the existing database schema and static-export diagnostics.
- Preserve official-versus-provisional calendar behavior, the weekly audit, and
  non-blocking expiry warnings.
- Continue to hard-fail only when the requested calculation date lies outside
  verified official coverage.
- Keep all generated calendar manifests deterministic and drift-checkable.

## Selected Architecture

### Typed breadth plan behind a compatibility facade

`BreadthCalculatorService.backfill_range()` remains available with its existing
arguments. It becomes a compatibility facade that normalizes those arguments
into one validated `BreadthBackfillPlan` and delegates execution.

The plan contains an ordered collection of `BreadthEligibleUniverse` values.
Each value binds a calculation date to its canonical symbol tuple and eligibility
signature. The signature is derived from the canonical symbols at the boundary;
callers cannot independently supply a conflicting signature. A legacy call with
no explicit eligibility produces the current-active-universe plan used today.

For backward compatibility, calls that supply both legacy maps are accepted and
validated. Calls that supply only one map, omit a requested date, or provide a
signature inconsistent with the canonical symbols raise `ValueError` rather than
creating an ambiguous execution mode.

The historical execution algorithm moves to a focused executor. It owns batch
price loading, per-date calculation, rolling ratios, persistence, and typed
execution results. The facade retains dependency construction and conversion to
the legacy result dictionary. This leaves one calculation path and brings
`breadth_calculator_service.py` below 1,000 lines.

### Static breadth coordinator

A `StaticBreadthHistoryCoordinator` becomes the canonical owner of static
breadth preparation. It receives a session factory, price cache, calendar/date
resolver, eligibility classifier, and calculator factory through explicit
dependencies.

Its `ensure()` operation owns:

1. target-date selection;
2. existing-row loading;
3. eligibility classification;
4. row reuse and signature validation;
5. repair-window planning;
6. breadth execution and assessment; and
7. typed diagnostics.

The static-export CLI calls the coordinator and serializes its result. Console
messages remain compatible, but no database or breadth policy stays in the CLI
module.

### Declarative reviewed calendar inputs

Reviewed source metadata and official closure dates move from executable Python
to a schema-versioned JSON input under `backend/data/market_calendars/inputs/`.
The input records each Market's source, verified-through year, checked date, and
official weekday closures by year.

The calendar builder validates and loads this input, then uses the existing
manifest generator to produce annual session manifests. CN and SG provisional
generation strategies remain code because they are algorithms, while reviewed
facts become data. The existing `--check` workflow continues to compare generated
output byte-for-byte with checked-in manifests.

### Test decomposition

The test suite is divided by behavior rather than by the former large module:

- static export refresh tests retain general daily-refresh behavior;
- static breadth history tests cover coordination, reuse, repair, and diagnostics;
- breadth calculator tests retain daily calculation behavior;
- breadth backfill tests cover compatibility normalization and execution.

Shared fixtures move only when they represent stable test-domain builders. Test
splitting must not weaken assertions or replace behavioral checks with source
inspection.

## Data Flow

For static breadth, the CLI resolves the requested Market/date and invokes the
coordinator. The coordinator resolves date-specific eligibility and constructs a
validated plan. The compatibility facade delegates that plan to the historical
executor. The executor persists rows with signatures derived from the exact
eligible symbols. The coordinator assesses scanned-versus-eligible coverage and
returns diagnostics to the CLI.

For calendar maintenance, the builder loads the reviewed JSON input, validates
Market completeness and official-year coverage, generates official sessions and
provisional sessions, and checks or writes the same manifest layout consumed by
`CalendarCoverageRegistry`.

## Error Handling

- Incomplete or inconsistent legacy eligibility arguments fail at the facade
  boundary with a specific `ValueError`.
- Empty eligible universes retain the existing hard-failure assessment.
- Calculation and cache errors retain their current classification.
- Invalid reviewed calendar input fails generation before any manifest is
  written. Generation continues to plan all output before performing writes.
- Calendar expiry and audit warning behavior is unchanged.

## Verification

Implementation follows red-green-refactor cycles for each new boundary:

1. typed eligibility-plan validation and legacy conversion;
2. executor delegation and result compatibility;
3. static coordinator behavior and CLI delegation;
4. calendar input loading and deterministic drift checks; and
5. test-module decomposition.

Focused breadth, static-export, calendar-generation, workflow, and schema tests
must pass after their respective refactors. The final gate is the complete
backend unit suite plus calendar drift/audit checks. File-size checks must confirm
that production and touched test modules no longer cross 1,000 lines.

## Non-Goals

- Changing breadth formulas or the 70-observation eligibility threshold.
- Changing database columns or static artifact schemas.
- Adding live network calendar retrieval.
- Changing supported Markets, Market/MIC mappings, or provisional coverage dates.
- Refactoring unrelated static-export or daily breadth behavior.
