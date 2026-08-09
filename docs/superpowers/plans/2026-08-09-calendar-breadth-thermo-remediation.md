# Calendar and Breadth Thermo-Review Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve calendar and static-breadth behavior while replacing parallel eligibility maps and giant-script orchestration with typed, focused components and declarative reviewed calendar inputs.

**Architecture:** Keep `BreadthCalculatorService.backfill_range()` as a compatibility facade over one typed historical executor. Move static breadth preparation into a coordinator, and compile schema-validated reviewed calendar JSON into the existing annual manifests.

**Tech Stack:** Python 3.11, SQLAlchemy, pytest, immutable dataclasses, checked-in JSON calendar data, GitHub Actions.

## Global Constraints

- Retain backward compatibility for existing `BreadthCalculatorService.backfill_range()` callers.
- Preserve the existing database and static-artifact schemas.
- Preserve date-specific breadth eligibility and deterministic signatures.
- Preserve official/provisional calendar semantics and non-blocking warnings.
- Hard-fail only when the requested calculation date is outside verified coverage.
- Do not add runtime network access.
- Use red-green-refactor for every production boundary.
- End with every touched production and test module below 1,000 lines.

---

## File Structure

### Create

- `backend/app/services/breadth_backfill.py`: typed plan, legacy normalization, historical execution, and typed result.
- `backend/app/services/static_breadth_history_coordinator.py`: row reuse, repair planning, execution, assessment, and diagnostics.
- `backend/app/domain/markets/reviewed_calendar_input.py`: schema-validating reviewed-fact loader.
- `backend/data/market_calendars/inputs/reviewed_official_calendars.json`: source and closure facts.
- `backend/tests/unit/test_breadth_backfill.py`: historical backfill contract and execution.
- `backend/tests/unit/test_static_breadth_history_coordinator.py`: static breadth coordination.
- `backend/tests/unit/domain/markets/test_reviewed_calendar_input.py`: input validation.

### Modify

- `backend/app/services/breadth_calculator_service.py`: compatibility facade and daily behavior.
- `backend/app/services/static_breadth_eligibility.py`: authoritative per-date eligibility record.
- `backend/app/scripts/export_static_site.py`: thin coordinator caller.
- `backend/app/scripts/build_market_calendar_data.py`: input-driven generator.
- Existing breadth, export, and calendar tests: retain coverage while splitting by responsibility.

---

### Task 1: Make Historical Breadth Eligibility Atomic

**Files:**
- Create: `backend/app/services/breadth_backfill.py`
- Modify: `backend/app/services/static_breadth_eligibility.py`
- Create: `backend/tests/unit/test_breadth_backfill.py`
- Test: `backend/tests/unit/test_static_breadth_eligibility.py`

**Interfaces:**
- Produces `BreadthEligibleUniverse`, `BreadthBackfillPlan.from_legacy()`, and `StaticBreadthDateEligibility`.
- Uses `static_breadth_eligibility_signature()` as the sole signature function.

- [ ] **Step 1: Write failing contract tests**

Test canonical sorting/deduplication, a matching signature, half-supplied legacy maps, missing requested dates, and a mismatched signature. The central assertion is:

```python
day = date(2026, 3, 20)
plan = BreadthBackfillPlan.from_legacy(
    dates=[day],
    eligible_symbols_by_date={day: ("BBB", "AAA", "AAA")},
    eligibility_signatures_by_date={
        day: static_breadth_eligibility_signature(("AAA", "BBB"))
    },
)
assert plan.universe_for(day).symbols == ("AAA", "BBB")
```

- [ ] **Step 2: Run tests and verify RED**

Run `cd backend && ./venv/bin/pytest tests/unit/test_breadth_backfill.py -q`.
Expected: collection fails because the typed plan does not exist.

- [ ] **Step 3: Implement immutable contracts**

`BreadthEligibleUniverse` binds `calculation_date`, canonical `symbols`, and the derived `eligibility_signature`. `BreadthBackfillPlan` stores ordered dates and an optional immutable per-date universe mapping. `from_legacy()` requires both maps or neither, requires all dates, and validates signatures.

- [ ] **Step 4: Replace eligibility parallel state**

Add `StaticBreadthDateEligibility(calculation_date, candidate_count, eligible_symbols, universe_policy, eligibility_signature)` and make `StaticBreadthEligibility.by_date` authoritative. Retain the five existing `*_by_date` names as read-only compatibility properties.

- [ ] **Step 5: Verify GREEN**

Run `cd backend && ./venv/bin/pytest tests/unit/test_breadth_backfill.py tests/unit/test_static_breadth_eligibility.py -q`.

- [ ] **Step 6: Commit**

Commit as `refactor: make breadth eligibility atomic`.

### Task 2: Extract the Historical Breadth Executor

**Files:**
- Modify: `backend/app/services/breadth_backfill.py`
- Modify: `backend/app/services/breadth_calculator_service.py`
- Modify: `backend/tests/unit/test_breadth_backfill.py`
- Modify: `backend/tests/unit/test_breadth_calculator_service.py`

**Interfaces:**
- Consumes `BreadthBackfillPlan`.
- Produces `BreadthBackfillExecutor.execute(...) -> BreadthBackfillResult`.
- Preserves the dictionary returned by public `backfill_range()`.

- [ ] **Step 1: Move backfill tests and add a failing delegation test**

Move tests for explicit universes, ratios, cache-only gaps/errors, unsupported symbols, target-date cache requirements, sparse dates, exact bars, and vectorized thresholds into `test_breadth_backfill.py`. Add a test patching `BreadthBackfillExecutor.execute()` and assert the facade passes one validated plan.

- [ ] **Step 2: Verify RED**

Run `cd backend && ./venv/bin/pytest tests/unit/test_breadth_backfill.py -q`.
Expected: the delegation assertion fails because the algorithm remains inline.

- [ ] **Step 3: Extract one execution path**

Move the batch loop, per-date symbol selection, rolling-ratio timeline, and bulk persistence to `BreadthBackfillExecutor`. Move helpers used only by backfill with it. Extract genuinely shared metric primitives as direct module functions imported by both modules; do not introduce callback bags or duplicate the algorithm.

The compatibility facade must preserve cache-only policy translation and fallback calendar resolution, normalize legacy maps through `BreadthBackfillPlan.from_legacy()`, construct the executor from `db`, `price_cache`, and `market`, and return `result.to_legacy_dict()`.

- [ ] **Step 4: Verify GREEN**

Run `cd backend && ./venv/bin/pytest tests/unit/test_breadth_backfill.py tests/unit/test_breadth_calculator_service.py tests/unit/test_breadth_coverage.py -q`.

- [ ] **Step 5: Check decomposition**

Run `wc -l backend/app/services/breadth_calculator_service.py backend/app/services/breadth_backfill.py`; both must be below 1,000 lines.

- [ ] **Step 6: Commit**

Commit as `refactor: extract breadth backfill executor`.

### Task 3: Extract Static Breadth History Coordination

**Files:**
- Create: `backend/app/services/static_breadth_history_coordinator.py`
- Modify: `backend/app/scripts/export_static_site.py`
- Create: `backend/tests/unit/test_static_breadth_history_coordinator.py`
- Modify: `backend/tests/unit/test_export_static_site_refresh.py`

**Interfaces:**
- Produces `StaticBreadthHistoryRequest`, `StaticBreadthHistoryResult.as_dict()`, and `StaticBreadthHistoryCoordinator.ensure()`.
- Consumes the typed eligibility and existing breadth assessment contracts.

- [ ] **Step 1: Move policy scenarios to a new test module**

Move every `_ensure_breadth_history` scenario and stable builder. Exercise the wished-for coordinator API for missing rows, incomplete rows, signature mismatch, repair-window expansion, valid reuse, tolerated early gaps, calculation errors, undercoverage, zero eligibility, and smaller historical universes. Retain one export test for wrapper delegation.

- [ ] **Step 2: Verify RED**

Run `cd backend && ./venv/bin/pytest tests/unit/test_static_breadth_history_coordinator.py -q`.
Expected: import failure for the coordinator.

- [ ] **Step 3: Implement coordinator models and flow**

The request binds Market, as-of date, minimum trading days, and lookback days. The result holds status and immutable diagnostics. The coordinator owns dates, existing-row reads, eligibility, signature reuse, repair dates, calculator execution, assessment, and diagnostics. Inject session, date generation, eligibility classification, price cache, and calculator construction through explicit named dependencies.

- [ ] **Step 4: Thin the CLI wrapper**

Keep `_ensure_breadth_history()` for compatibility, but reduce it to request construction, coordinator invocation, compatible console output, and `result.as_dict()`.

- [ ] **Step 5: Verify GREEN and sizes**

Run `cd backend && ./venv/bin/pytest tests/unit/test_static_breadth_history_coordinator.py tests/unit/test_export_static_site_refresh.py tests/unit/test_static_breadth_assessment.py -q`.
Then verify both touched test modules are below 1,000 lines and `export_static_site.py` is materially smaller than 1,530 lines.

- [ ] **Step 6: Commit**

Commit as `refactor: extract static breadth coordination`.

### Task 4: Make Reviewed Calendar Facts Declarative

**Files:**
- Create: `backend/app/domain/markets/reviewed_calendar_input.py`
- Create: `backend/data/market_calendars/inputs/reviewed_official_calendars.json`
- Modify: `backend/app/scripts/build_market_calendar_data.py`
- Create: `backend/tests/unit/domain/markets/test_reviewed_calendar_input.py`
- Modify: `backend/tests/unit/test_market_calendar_data.py`

**Interfaces:**
- Produces `ReviewedCalendarInput.load()`, `source_for()`, `closures_for()`, and `official_through()`.
- Consumes `CalendarSource` and the Market Catalog.

- [ ] **Step 1: Write failing validation tests**

Test missing supported Markets, an official year absent from `closures`, closure dates outside their declared year, duplicate dates, invalid source metadata, and production-file completeness. An official year with no closures must be an explicit empty array.

- [ ] **Step 2: Verify RED**

Run `cd backend && ./venv/bin/pytest tests/unit/domain/markets/test_reviewed_calendar_input.py -q`.

- [ ] **Step 3: Transfer facts to schema-versioned JSON**

The root contains `schema_version`, `checked_at`, and `markets`. Each Market contains `source`, `official_through`, and a year-keyed `closures` object. Transfer existing facts exactly; do not refresh or infer dates during this refactor.

- [ ] **Step 4: Implement strict immutable loading**

Validate schema version, checked date, exact Market set, source text/URL, contiguous official years from 2026 through `official_through`, uniqueness, and year alignment.

- [ ] **Step 5: Simplify the builder**

Delete `OFFICIAL_SOURCES`, `REVIEWED_OFFICIAL_CLOSURES`, and `_reviewed_dates`. Preserve CN/SG provisional algorithms. Generate the identical index and annual manifests from the loader.

- [ ] **Step 6: Verify GREEN and deterministic drift**

Run:

```bash
cd backend && ./venv/bin/pytest tests/unit/domain/markets/test_reviewed_calendar_input.py tests/unit/test_market_calendar_data.py tests/unit/test_calendar_manifest_generation.py -q
cd backend && ./venv/bin/python -m app.scripts.build_market_calendar_data --check
```

- [ ] **Step 7: Commit**

Commit as `refactor: make reviewed calendars declarative`.

### Task 5: Run Final Quality Gates

**Files:**
- Modify: `docs/superpowers/plans/2026-08-09-calendar-breadth-thermo-remediation.md`
- Modify oversized tests only if responsibility splitting remains incomplete.

**Interfaces:**
- Produces the behaviorally equivalent, decomposed branch.

- [ ] **Step 1: Run focused suites**

Run all new tests plus existing breadth calculator, eligibility, assessment, export refresh, calendar data, manifest generation, and audit tests.

- [ ] **Step 2: Run calendar checks**

```bash
cd backend && ./venv/bin/python -m app.scripts.build_market_calendar_data --check
cd backend && ./venv/bin/python -m app.scripts.audit_market_calendars --as-of 2026-08-09
```

- [ ] **Step 3: Run the complete backend unit suite**

Run `cd backend && ./venv/bin/pytest tests/unit/ -q`.

- [ ] **Step 4: Enforce file-size gates**

Run `wc -l` on every new/touched breadth, export, calendar-builder, and split-test module. Every touched production and test module must be below 1,000 lines; `export_static_site.py` must be below its 1,530-line pre-remediation size.

- [ ] **Step 5: Check diff integrity**

Run `git diff --check`, `git status --short`, and inspect `git diff --stat $(git merge-base HEAD main)..HEAD`.

- [ ] **Step 6: Record exact verification and commit**

Replace the pending verification note below with commands, counts, and results. Commit as `test: verify calendar breadth remediation`.

## Implementation Verification

Verification is deliberately deferred to Task 5 because this document is the
pre-execution plan. Task 5 records the exact commands, test counts, line counts,
and calendar-check results before the implementation is declared complete.

## Plan Self-Review

- Every approved design requirement maps to a task.
- The legacy public method remains the compatibility entry point over one executor.
- Calendar facts move without being refreshed or reinterpreted.
- No task adds a migration, runtime network dependency, or artifact-schema change.
- Each production boundary begins with a focused failing test.
