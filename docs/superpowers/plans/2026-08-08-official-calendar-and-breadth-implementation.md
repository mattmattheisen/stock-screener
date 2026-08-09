# Official Calendar Coverage and Historical Breadth Eligibility Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make official calendar coverage explicit and expiring, publish non-blocking weekly warnings, generate provisional calendars through 2030, and validate static breadth against a date-specific eligible universe instead of the current active universe.

**Architecture:** Add a checked-in calendar manifest registry in the Market domain and inject it into `MarketCalendarService`, where official sessions override pinned provider calendars and future requests beyond `verified_through` fail. Add a read-only audit CLI/workflow for warning bands. For breadth, resolve point-in-time candidates per calculation date, classify price-history eligibility before calculation, pass only eligible symbols into the calculator, and compare persisted scan counts with the corresponding date-specific denominator.

**Tech Stack:** Python 3.11, dataclasses, JSON, SQLAlchemy, pytest, `exchange-calendars`, `pandas-market-calendars`, GitHub Actions YAML.

---

### Task 1: Add the calendar manifest domain contract

**Files:**

- Create: `backend/app/domain/markets/calendar_coverage.py`
- Create: `backend/tests/unit/domain/markets/test_calendar_coverage.py`
- Create: `backend/tests/fixtures/market_calendars/minimal-index.json`
- Create: `backend/tests/fixtures/market_calendars/kr/2026.json`

**Step 1: Write failing parser and invariant tests**

Cover:

- schema version 1 parsing;
- source name, URL, and `checked_at` are mandatory;
- `verified_through` cannot exceed the last official annual file;
- official and provisional annual files cannot overlap for one year;
- session dates must match the declared year, be unique, and be sorted;
- the entry Market/MIC must match the index and Market Catalog;
- all supported Market codes must appear exactly once;
- provisional coverage must reach `2030-12-31`;
- optional close exceptions must reference declared sessions.

Run:

```bash
cd backend && ../backend/venv/bin/pytest tests/unit/domain/markets/test_calendar_coverage.py -q
```

Expected: FAIL because `app.domain.markets.calendar_coverage` does not exist.

**Step 2: Implement immutable manifest types and loader**

Add:

```python
@dataclass(frozen=True, slots=True)
class CalendarSource:
    name: str
    url: str
    checked_at: date

@dataclass(frozen=True, slots=True)
class AnnualCalendarManifest:
    market: str
    mic: str
    year: int
    status: Literal["official", "provisional"]
    sessions: tuple[date, ...]
    close_exceptions: Mapping[date, time]
    source: CalendarSource
    provider: str | None = None
    provider_version: str | None = None

@dataclass(frozen=True, slots=True)
class MarketCalendarCoverage:
    market: str
    mic: str
    verified_through: date
    source: CalendarSource
    annual: Mapping[int, AnnualCalendarManifest]
```

Expose `CalendarCoverageRegistry.load(root, market_catalog=...)`,
`coverage_for(market, mic=None)`, and `official_sessions(market, start, end)`.
Reject malformed data with `CalendarManifestError`; do not silently skip files.

**Step 3: Run the focused tests**

Expected: PASS.

**Step 4: Commit**

```bash
git add backend/app/domain/markets/calendar_coverage.py \
  backend/tests/unit/domain/markets/test_calendar_coverage.py \
  backend/tests/fixtures/market_calendars
git commit -m "feat: define official calendar coverage manifests"
```

### Task 2: Add reproducible provisional-calendar generation

**Files:**

- Create: `backend/app/services/calendar_manifest_generation.py`
- Create: `backend/app/scripts/generate_market_calendar_manifests.py`
- Create: `backend/tests/unit/test_calendar_manifest_generation.py`

**Step 1: Write failing generation tests**

Use fake provider calendars to assert:

- years 2027–2030 are produced deterministically;
- output is sorted JSON with a trailing newline;
- provider name/version are recorded;
- an out-of-bounds provider never silently produces weekdays;
- an explicit normalized session input can create an `official` file;
- generation refuses to overwrite an official year with provisional data;
- `--check` reports drift without writing.

Run:

```bash
cd backend && ../backend/venv/bin/pytest tests/unit/test_calendar_manifest_generation.py -q
```

Expected: FAIL because the generator is absent.

**Step 2: Implement generator service and CLI**

The service accepts a provider adapter and an explicit `[start, end]`. It must use
provider sessions, not weekday synthesis. The CLI supports:

```text
--root PATH
--market MARKET (repeatable; default all)
--through-year 2030
--status provisional|official
--official-sessions PATH
--source-name NAME
--source-url URL
--checked-at YYYY-MM-DD
--check
```

Official import requires an explicit normalized input file and provenance.

**Step 3: Run tests and a deterministic dry run in a temporary directory**

```bash
cd backend && ../backend/venv/bin/pytest tests/unit/test_calendar_manifest_generation.py -q
tmp_dir="$(mktemp -d)"
cd backend && ../backend/venv/bin/python -m app.scripts.generate_market_calendar_manifests \
  --root "$tmp_dir" --market US --through-year 2030 --status provisional
```

Expected: tests PASS; generated US files end at 2030.

**Step 4: Commit**

```bash
git add backend/app/services/calendar_manifest_generation.py \
  backend/app/scripts/generate_market_calendar_manifests.py \
  backend/tests/unit/test_calendar_manifest_generation.py
git commit -m "feat: generate provisional calendar manifests"
```

### Task 3: Check in source-attributed coverage for every Market

**Files:**

- Create: `backend/data/market_calendars/index.json`
- Create: `backend/data/market_calendars/{us,hk,in,jp,kr,tw,cn,ca,de,sg,au,my}/*.json`
- Create: `backend/tests/unit/test_market_calendar_data.py`

**Step 1: Write a failing repository-data test**

Load the real data root and assert:

- exact parity with `get_market_catalog().supported_market_codes()`;
- every Market has at least current-year official coverage;
- every Market has provisional files through 2030;
- official files have first-party exchange provenance;
- known 2026 closures are absent from official sessions for KR, TW, SG, MY, CN,
  and JP;
- no official file claims a year not supported by its cited publication.

Run:

```bash
cd backend && ../backend/venv/bin/pytest tests/unit/test_market_calendar_data.py -q
```

Expected: FAIL because the real manifest root is absent.

**Step 2: Collect and normalize official schedules**

Use first-party exchange publications only. Record the exact source URL and
`checked_at` in each Market entry/file. At minimum verify 2026 for all Markets,
including these previously misclassified closures:

- KR: `2026-05-25`, `2026-06-03`, `2026-07-17`;
- TW: `2026-02-12`, `2026-02-20`;
- SG: `2026-01-01`, `2026-02-17`, `2026-02-18`, `2026-04-03`, `2026-05-01`, `2026-06-01`;
- MY: `2026-03-23`, `2026-06-01`, `2026-06-17`;
- CN: `2026-01-01`, `2026-01-02`, `2026-02-16` through `2026-02-23`,
  `2026-04-06`, `2026-05-01`, `2026-05-04`, `2026-05-05`, `2026-06-19`;
- JP: retain the known official overrides already represented in code.

If an official 2027+ publication is available, include it and advance only that
Market's `verified_through`. Never label provider-generated 2028–2030 dates
official without an exchange publication.

**Step 3: Generate provisional years through 2030**

Run the generator for all Markets. For provider-bounded CN/SG years, supply a
reviewed provisional input rather than enabling weekday fallback. Mark every such
file `provisional` and preserve provider/source notes.

**Step 4: Run real-data and parser tests**

```bash
cd backend && ../backend/venv/bin/pytest \
  tests/unit/domain/markets/test_calendar_coverage.py \
  tests/unit/test_calendar_manifest_generation.py \
  tests/unit/test_market_calendar_data.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add backend/data/market_calendars backend/tests/unit/test_market_calendar_data.py
git commit -m "data: add verified and provisional market calendars"
```

### Task 4: Enforce verified coverage in `MarketCalendarService`

**Files:**

- Modify: `backend/app/services/market_calendar_service.py`
- Modify: `backend/app/domain/markets/calendar_policy.py`
- Modify: `backend/tests/unit/test_market_calendar_service.py`
- Modify: `backend/tests/unit/test_market_calendar_service_engine.py`

**Step 1: Write failing boundary and precedence tests**

Add tests for:

- an official session list overriding provider-reported false sessions;
- exact `verified_through` success;
- the next day raising `CalendarCoverageExpired` with Market, requested date,
  verified date, source URL, and operations-doc path;
- `trading_days` guarding `end`, while provider history before the first official
  annual file remains available;
- `session_anchors` inheriting the as-of guard;
- `last_completed_trading_day` failing when the Market-local current date exceeds
  verified coverage;
- no CN/SG future weekday fallback;
- injected fake registries preserving unit-test isolation;
- official close exceptions taking precedence for completion checks.

Run:

```bash
cd backend && ../backend/venv/bin/pytest \
  tests/unit/test_market_calendar_service.py \
  tests/unit/test_market_calendar_service_engine.py -q
```

Expected: FAIL on the new contract.

**Step 2: Implement the coverage guard and official overlay**

Add `CalendarCoverageExpired(RuntimeError)` and inject
`calendar_coverage_registry`. Remove `WEEKDAY_BOUNDS_FALLBACK_MARKETS` and its
future synthesis helpers. Preserve `session_overrides` as an explicit test and
emergency compatibility hook, but load repository official sessions before
provider results.

Use one internal method:

```python
def _require_verified_calculation_date(
    self, market: str, requested_date: date, *, mic: str | None = None
) -> MarketCalendarCoverage:
    ...
```

Call it exactly once at each public boundary so range lookbacks do not fail merely
because their historical start predates checked-in files.

**Step 3: Run focused and downstream date-resolution tests**

```bash
cd backend && ../backend/venv/bin/pytest \
  tests/unit/test_market_calendar_service.py \
  tests/unit/test_market_calendar_service_engine.py \
  tests/unit/test_calendar_benchmark_invariants.py \
  tests/unit/test_static_rrg_history_bundle.py -q
```

Expected: PASS.

**Step 4: Commit**

```bash
git add backend/app/services/market_calendar_service.py \
  backend/app/domain/markets/calendar_policy.py \
  backend/tests/unit/test_market_calendar_service.py \
  backend/tests/unit/test_market_calendar_service_engine.py
git commit -m "feat: enforce verified market calendar coverage"
```

### Task 5: Add non-blocking calendar audit reporting

**Files:**

- Create: `backend/app/services/calendar_coverage_audit.py`
- Create: `backend/app/scripts/audit_market_calendars.py`
- Create: `backend/tests/unit/test_calendar_coverage_audit.py`

**Step 1: Write failing warning-band and output tests**

Parameterize 181, 180, 90, 60, 30, 0, and negative remaining days. Assert:

- 181 days emits no age warning;
- 180/90/60/30 use the correct active severity band without duplicate bands;
- expired is still a warning;
- every age state exits zero;
- malformed manifests exit nonzero;
- Markdown has Market, MIC, verified-through, days remaining, status, source;
- `--github-actions` emits escaped `::warning::` lines and appends the summary;
- a provisional horizon before 2030 warns without failing.

Run:

```bash
cd backend && ../backend/venv/bin/pytest tests/unit/test_calendar_coverage_audit.py -q
```

Expected: FAIL because the audit is absent.

**Step 2: Implement pure audit service and thin CLI**

Keep date injection in the service for deterministic tests. The CLI defaults to
the repository manifest root and current UTC date, supports `--as-of`,
`--github-actions`, and `--root`, and returns zero for warning states.

**Step 3: Run tests and inspect local report**

```bash
cd backend && ../backend/venv/bin/pytest tests/unit/test_calendar_coverage_audit.py -q
cd backend && ../backend/venv/bin/python -m app.scripts.audit_market_calendars --as-of 2026-08-08
```

Expected: PASS and a 12-Market table.

**Step 4: Commit**

```bash
git add backend/app/services/calendar_coverage_audit.py \
  backend/app/scripts/audit_market_calendars.py \
  backend/tests/unit/test_calendar_coverage_audit.py
git commit -m "feat: report market calendar expiry warnings"
```

### Task 6: Add weekly and static-workflow audit steps

**Files:**

- Create: `.github/workflows/market-calendar-audit.yml`
- Modify: `.github/workflows/static-site.yml`
- Modify: `backend/tests/unit/test_static_workflow_markets.py`
- Create: `backend/tests/unit/test_market_calendar_audit_workflow.py`

**Step 1: Write failing workflow-structure tests**

Assert:

- the new workflow has `workflow_dispatch` and exactly one weekly cron;
- it installs pinned backend requirements and invokes
  `app.scripts.audit_market_calendars --github-actions`;
- the audit command is not marked `continue-on-error`, because the command itself
  returns success for expiry warnings but must expose corrupt manifests;
- static-site runs the same audit before `build-market`;
- no warning condition is used in job `if` expressions or matrix selection.

Run:

```bash
cd backend && ../backend/venv/bin/pytest \
  tests/unit/test_market_calendar_audit_workflow.py \
  tests/unit/test_static_workflow_markets.py -q
```

Expected: FAIL until workflows are added.

**Step 2: Implement workflows**

Use a single weekly schedule, for example Saturday `07:10 UTC`, plus manual
dispatch. Add a lightweight `calendar-audit` job to static-site and make market
selection depend on its successful schema validation, not on warning age.

**Step 3: Run workflow tests**

Expected: PASS.

**Step 4: Commit**

```bash
git add .github/workflows/market-calendar-audit.yml \
  .github/workflows/static-site.yml \
  backend/tests/unit/test_market_calendar_audit_workflow.py \
  backend/tests/unit/test_static_workflow_markets.py
git commit -m "ci: audit market calendar coverage weekly"
```

### Task 7: Add date-specific breadth eligibility classification

**Files:**

- Create: `backend/app/services/static_breadth_eligibility.py`
- Create: `backend/tests/unit/test_static_breadth_eligibility.py`

**Step 1: Write failing eligibility tests**

Build database fixtures covering two calculation dates and assert:

- point-in-time membership differs by date;
- unsupported price symbols are excluded and reported;
- a symbol with 69 observations is ineligible and becomes eligible at 70;
- a symbol without an exact-date OHLC row is ineligible for that date only;
- null/non-finite OHLC rows are not valid observations;
- exclusion samples are bounded and deterministic;
- point-in-time fallback policy is recorded explicitly;
- zero candidate and zero eligible counts remain distinguishable.

Run:

```bash
cd backend && ../backend/venv/bin/pytest tests/unit/test_static_breadth_eligibility.py -q
```

Expected: FAIL because the service is absent.

**Step 2: Implement the classifier**

Return:

```python
@dataclass(frozen=True, slots=True)
class StaticBreadthEligibility:
    eligible_symbols_by_date: Mapping[date, tuple[str, ...]]
    candidate_counts_by_date: Mapping[date, int]
    eligible_counts_by_date: Mapping[date, int]
    universe_policy_by_date: Mapping[date, str]
    unsupported_symbols: tuple[str, ...]
    insufficient_history_symbols: tuple[str, ...]
    exact_date_gap_symbols: tuple[str, ...]
```

Resolve membership with `CurrentActiveFallbackUniverseResolver`, filter through
`split_supported_price_symbols`, and query valid `StockPrice` rows in chunks.
Eligibility is exact-date OHLC plus at least 70 valid observations through that
date. Do not perform provider fetches.

**Step 3: Run focused tests**

Expected: PASS.

**Step 4: Commit**

```bash
git add backend/app/services/static_breadth_eligibility.py \
  backend/tests/unit/test_static_breadth_eligibility.py
git commit -m "feat: classify date-specific breadth eligibility"
```

### Task 8: Make breadth backfill consume explicit eligible symbols

**Files:**

- Modify: `backend/app/services/breadth_calculator_service.py`
- Modify: `backend/app/services/breadth_coverage.py`
- Modify: `backend/tests/unit/test_breadth_calculator_service.py`
- Modify: `backend/tests/unit/test_breadth_coverage.py`

**Step 1: Write failing explicit-universe tests**

Assert that `backfill_range(..., eligible_symbols_by_date=...)`:

- loads the union of supplied eligible symbols once in batches;
- never scans a symbol on a date where it is absent from the supplied set;
- returns `eligible_stocks_by_date` and `scanned_stocks_by_date`;
- preserves calculation errors separately;
- keeps existing behavior when the optional mapping is omitted.

Run:

```bash
cd backend && ../backend/venv/bin/pytest \
  tests/unit/test_breadth_calculator_service.py \
  tests/unit/test_breadth_coverage.py -q
```

Expected: FAIL on the new argument and diagnostics.

**Step 2: Implement the explicit-universe boundary**

Do not resolve point-in-time membership inside the calculator. The calculator
receives already normalized symbol sets, scans each date's set, and reports counts.
Keep provider/cache execution policy unchanged.

**Step 3: Run focused tests**

Expected: PASS.

**Step 4: Commit**

```bash
git add backend/app/services/breadth_calculator_service.py \
  backend/app/services/breadth_coverage.py \
  backend/tests/unit/test_breadth_calculator_service.py \
  backend/tests/unit/test_breadth_coverage.py
git commit -m "refactor: pass eligible universes into breadth backfill"
```

### Task 9: Replace the fixed breadth denominator in assessment

**Files:**

- Modify: `backend/app/services/static_market_coverage_policy.py`
- Modify: `backend/app/services/static_breadth_assessment.py`
- Modify: `backend/tests/unit/test_static_market_coverage_policy.py`
- Modify: `backend/tests/unit/test_static_breadth_assessment.py`

**Step 1: Write failing dynamic-denominator tests**

Replace fixed `minimum_stocks_scanned` fixtures with
`eligible_stocks_by_date`. Assert:

- scanned equals eligible passes;
- scanned below eligible fails for that date;
- different dates may have different denominators;
- zero eligible fails explicitly;
- calculation errors remain higher-priority failures;
- pre-warmup tolerance is preserved only where the existing policy permits it;
- `static_breadth_history_min_coverage` no longer calls or mirrors
  `market_current_price_min_coverage`;
- daily-price and Market RS thresholds retain their existing values.

Run:

```bash
cd backend && ../backend/venv/bin/pytest \
  tests/unit/test_static_market_coverage_policy.py \
  tests/unit/test_static_breadth_assessment.py -q
```

Expected: FAIL on the fixed denominator API.

**Step 2: Implement the independent policy**

Replace `static_breadth_minimum_validated_scan_count(supported_symbol_count, ...)`
with a date-specific helper whose default eligible scan floor is 100% of the
preclassified eligible set. Do not add market-specific breadth exceptions. Include
eligible and scanned values in error text and diagnostics.

**Step 3: Run tests**

Expected: PASS.

**Step 4: Commit**

```bash
git add backend/app/services/static_market_coverage_policy.py \
  backend/app/services/static_breadth_assessment.py \
  backend/tests/unit/test_static_market_coverage_policy.py \
  backend/tests/unit/test_static_breadth_assessment.py
git commit -m "fix: validate breadth against eligible history"
```

### Task 10: Wire breadth eligibility into static export

**Files:**

- Modify: `backend/app/scripts/export_static_site.py`
- Modify: `backend/tests/unit/test_export_static_site_refresh.py`
- Modify: `backend/tests/unit/test_export_static_site_script.py`

**Step 1: Write failing orchestration regressions**

Add fixtures representing the prior US, DE, and HK failures:

- full current active universe is larger than the historical eligible universe;
- existing rows are reused when scanned count satisfies that date's eligible count;
- only deficient dates are recomputed;
- recomputation receives `eligible_symbols_by_date`;
- status diagnostics include candidate/eligible/scanned counts and fallback policy;
- zero eligible and calculation errors still prevent exposure.

Run:

```bash
cd backend && ../backend/venv/bin/pytest \
  tests/unit/test_export_static_site_refresh.py \
  tests/unit/test_export_static_site_script.py -q
```

Expected: FAIL while export uses `_static_breadth_supported_symbol_count`.

**Step 2: Integrate the classifier**

In `_ensure_breadth_history`:

1. classify eligibility for all target dates;
2. validate existing rows against per-date eligible counts;
3. pass eligible sets for recompute dates into `backfill_range`;
4. assess scanned versus eligible maps;
5. add bounded eligibility diagnostics to the returned status.

Delete `_static_breadth_supported_symbol_count` after callers are migrated.

**Step 3: Run static export and breadth suites**

```bash
cd backend && ../backend/venv/bin/pytest \
  tests/unit/test_export_static_site_refresh.py \
  tests/unit/test_export_static_site_script.py \
  tests/unit/test_static_breadth_assessment.py \
  tests/unit/test_breadth_calculator_service.py -q
```

Expected: PASS.

**Step 4: Commit**

```bash
git add backend/app/scripts/export_static_site.py \
  backend/tests/unit/test_export_static_site_refresh.py \
  backend/tests/unit/test_export_static_site_script.py
git commit -m "fix: use eligible universes for static breadth"
```

### Task 11: Document calendar operations and failure semantics

**Files:**

- Modify: `docs/OPERATIONS.md`
- Modify: `docs/LIVE_APP_GUIDE.md`
- Create: `backend/tests/unit/test_calendar_operations_docs.py`

**Step 1: Write a failing documentation contract test**

Assert the operations guide includes:

- annual update-on-publication responsibility;
- weekly audit cadence;
- 180/90/60/30/expired non-blocking warnings;
- hard failure only when requested date exceeds `verified_through`;
- official versus provisional meaning;
- commands to audit, generate, import, diff, test, and advance coverage;
- first-party source provenance requirement;
- emergency closure procedure;
- no-bar data is evidence for investigation, not a closure authority.

Run:

```bash
cd backend && ../backend/venv/bin/pytest tests/unit/test_calendar_operations_docs.py -q
```

Expected: FAIL until documentation is updated.

**Step 2: Write the runbook and user-facing note**

Include copy-paste commands and the manifest paths. State clearly: routine manual
updates are annual/on-publication; the weekly job only audits and warns.

**Step 3: Run docs test**

Expected: PASS.

**Step 4: Commit**

```bash
git add docs/OPERATIONS.md docs/LIVE_APP_GUIDE.md \
  backend/tests/unit/test_calendar_operations_docs.py
git commit -m "docs: add market calendar maintenance runbook"
```

### Task 12: Run integrated verification

**Files:**

- Modify only if a verified regression requires a scoped fix.

**Step 1: Run calendar, breadth, static-export, and workflow suites**

```bash
cd backend && ../backend/venv/bin/pytest \
  tests/unit/domain/markets/test_calendar_coverage.py \
  tests/unit/test_calendar_manifest_generation.py \
  tests/unit/test_market_calendar_data.py \
  tests/unit/test_market_calendar_service.py \
  tests/unit/test_market_calendar_service_engine.py \
  tests/unit/test_calendar_coverage_audit.py \
  tests/unit/test_market_calendar_audit_workflow.py \
  tests/unit/test_static_breadth_eligibility.py \
  tests/unit/test_breadth_calculator_service.py \
  tests/unit/test_breadth_coverage.py \
  tests/unit/test_static_market_coverage_policy.py \
  tests/unit/test_static_breadth_assessment.py \
  tests/unit/test_export_static_site_refresh.py \
  tests/unit/test_export_static_site_script.py \
  tests/unit/test_static_workflow_markets.py \
  tests/unit/test_calendar_operations_docs.py -q
```

Expected: PASS.

**Step 2: Run all backend unit tests**

```bash
cd backend && ../backend/venv/bin/pytest tests/unit/ -q
```

Expected: PASS.

**Step 3: Validate generated data and reports**

```bash
cd backend && ../backend/venv/bin/python -m app.scripts.generate_market_calendar_manifests \
  --root data/market_calendars --through-year 2030 --status provisional --check
cd backend && ../backend/venv/bin/python -m app.scripts.audit_market_calendars --as-of 2026-08-08
git diff --check
git status --short
```

Expected: no generation drift; a 12-Market audit report; no whitespace errors;
only intentional changes present.

**Step 4: Commit any verified final adjustments**

If no adjustments are required, do not create an empty commit. Otherwise:

```bash
git add <scoped-files>
git commit -m "test: complete calendar and breadth verification"
```

### Task 13: Review branch readiness

Use `superpowers:requesting-code-review` to review the full branch diff against
`docs/superpowers/specs/2026-08-08-official-market-calendar-coverage-design.md`.
Resolve only verified findings, rerun affected tests, then use
`superpowers:verification-before-completion` before claiming success. Finally use
`superpowers:finishing-a-development-branch` to present merge/push/PR choices.
