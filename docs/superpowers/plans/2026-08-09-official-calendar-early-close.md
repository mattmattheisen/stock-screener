# Official Calendar Early-Close Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve reviewed official exceptional close times through deterministic calendar generation so provider-unavailable static exports recognize completed early-close sessions.

**Architecture:** Add an optional immutable exceptional-close mapping to the reviewed calendar input, propagate it through the existing official-manifest generator, and populate checked-in reviewed facts from official exchange schedules. The existing manifest reader and `MarketCalendarService` already consume `close_exceptions`, so their public interfaces remain unchanged.

**Tech Stack:** Python 3.11, dataclasses, JSON, pytest, pandas timestamps, checked-in deterministic calendar manifests.

## Global Constraints

- Exceptional times are exchange-local ISO times.
- The reviewed JSON addition is optional and remains schema version 1.
- Existing loader and generator callers remain backward compatible.
- Only official exchange material may establish reviewed exceptional-close facts.
- Invalid reviewed facts hard-fail generation; warnings and verified-coverage policy remain unchanged.
- Production code follows red-green-refactor: every behavior change starts with an observed failing test.

---

### Task 1: Parse and validate reviewed exceptional closes

**Files:**
- Modify: `backend/app/domain/markets/reviewed_calendar_input.py`
- Test: `backend/tests/unit/domain/markets/test_reviewed_calendar_input.py`

**Interfaces:**
- Consumes: optional JSON `markets.<MARKET>.close_exceptions.<YEAR>.<DATE> = "HH:MM:SS"`
- Produces: `ReviewedCalendarInput.close_exceptions_for(market: str, year: int) -> Mapping[date, time]`

- [ ] **Step 1: Write failing loader tests**

Add a reviewed early close to `_payload()` and assert the typed accessor result:

```python
assert reviewed.close_exceptions_for("US", 2026) == {
    date(2026, 11, 27): time(13, 0)
}
```

Add focused tests showing that an omitted field returns an empty immutable mapping and that invalid time text, a cross-year date, and a date also present in `closures` raise `ReviewedCalendarInputError` with field-specific messages.

- [ ] **Step 2: Run the focused loader tests and verify RED**

Run: `cd backend && ./venv/bin/pytest tests/unit/domain/markets/test_reviewed_calendar_input.py -q`

Expected: FAIL because `close_exceptions_for` does not exist.

- [ ] **Step 3: Implement the typed optional mapping**

Add `time` to the datetime imports, add
`close_exceptions: Mapping[int, Mapping[date, time]]` to
`ReviewedMarketCalendar`, parse optional `close_exceptions` for official years,
validate every date/time and closure conflict, wrap nested mappings with
`MappingProxyType`, and expose the accessor. Treat a missing field or missing
year as an empty immutable mapping.

- [ ] **Step 4: Run the loader tests and verify GREEN**

Run: `cd backend && ./venv/bin/pytest tests/unit/domain/markets/test_reviewed_calendar_input.py -q`

Expected: all tests pass.

### Task 2: Propagate exceptional closes into official manifests

**Files:**
- Modify: `backend/app/services/calendar_manifest_generation.py`
- Modify: `backend/app/scripts/build_market_calendar_data.py`
- Test: `backend/tests/unit/test_calendar_manifest_generation.py`
- Test: `backend/tests/unit/test_market_calendar_data.py`

**Interfaces:**
- Consumes: `Mapping[date, time]` from `ReviewedCalendarInput.close_exceptions_for()`
- Produces: existing annual-manifest JSON field `close_exceptions: Mapping[str, str]`

- [ ] **Step 1: Write failing generator tests**

Call `import_official_closures(..., close_exceptions={date(2027, 11, 26): time(13, 0)})` and assert:

```python
assert payload["close_exceptions"] == {"2027-11-26": "13:00:00"}
```

Add a test that a weekend, closure, or otherwise non-generated session raises
`CalendarManifestGenerationError` containing `exceptional close must be a session`.

- [ ] **Step 2: Run generator tests and verify RED**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_calendar_manifest_generation.py -q`

Expected: FAIL because the official import functions do not accept or emit exceptional closes.

- [ ] **Step 3: Implement minimal propagation**

Add optional `close_exceptions: Mapping[date, time] | None = None` keyword
parameters to `import_official_year()` and `import_official_closures()`. Validate
the mapping keys against generated sessions and pass it to `_annual_payload()`.
Update `build()` to pass
`reviewed.close_exceptions_for(market, year)` for official years.

- [ ] **Step 4: Run generator and builder tests and verify GREEN**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_calendar_manifest_generation.py tests/unit/test_market_calendar_data.py -q`

Expected: all tests pass before production JSON is changed.

### Task 3: Add source-verified production facts and regenerate manifests

**Files:**
- Modify: `backend/data/market_calendars/inputs/reviewed_official_calendars.json`
- Modify: affected `backend/data/market_calendars/<market>/<year>.json` files
- Modify: `docs/OPERATIONS.md` if its operator schema example omits exceptional closes
- Test: `backend/tests/unit/test_market_calendar_data.py`

**Interfaces:**
- Consumes: official exchange schedules already cited by each reviewed market source
- Produces: reviewed exchange-local exceptional close facts for every official year where the source declares one

- [ ] **Step 1: Verify official facts**

For every market/year marked official, inspect the cited exchange schedule and
record only explicitly published shortened sessions. Cross-check provider output
only as a discovery aid; do not promote an exception without official support.

- [ ] **Step 2: Write a failing production-data assertion**

Add a representative assertion that loads the production reviewed input and
checks a verified early close, including its exact exchange-local `time`.

- [ ] **Step 3: Run the production-data test and verify RED**

Run: `cd backend && ./venv/bin/pytest tests/unit/domain/markets/test_reviewed_calendar_input.py tests/unit/test_market_calendar_data.py -q`

Expected: FAIL because the reviewed production JSON does not yet contain the fact.

- [ ] **Step 4: Add reviewed facts and regenerate**

Add the optional `close_exceptions` objects to affected markets, then run:

```bash
cd backend
./venv/bin/python -m app.scripts.build_market_calendar_data
./venv/bin/python -m app.scripts.build_market_calendar_data --check
```

Inspect the manifest diff and confirm that only expected `close_exceptions` fields changed.

- [ ] **Step 5: Run production-data tests and verify GREEN**

Run: `cd backend && ./venv/bin/pytest tests/unit/domain/markets/test_reviewed_calendar_input.py tests/unit/test_calendar_manifest_generation.py tests/unit/test_market_calendar_data.py -q`

Expected: all tests pass.

### Task 4: Prove provider-unavailable runtime behavior and publish the fix

**Files:**
- Test: `backend/tests/unit/test_market_calendar_service.py`
- Modify: PR review thread on GitHub after local verification

**Interfaces:**
- Consumes: generated official manifest `close_exceptions`
- Produces: regression proof that `last_completed_trading_day()` selects the current session after its exceptional close plus the existing 30-minute buffer

- [ ] **Step 1: Write or tighten the runtime regression test**

Build a registry fixture with a 13:00 official close, make the provider raise a
calendar-bounds error, set local time after 13:30 but before the regular close,
and assert the current date is returned.

- [ ] **Step 2: Demonstrate the regression test protects the reviewed path**

Run the test against a fixture without the generated exception and observe the
previous session; restore the generated exception and verify PASS.

- [ ] **Step 3: Run proportional verification**

Run focused calendar suites, the calendar manifest drift check, changed-file
lint, `git diff --check`, and the complete backend pytest suite.

- [ ] **Step 4: Commit and push**

Commit the test-first implementation and regenerated deterministic data, then
push `codex/calendar-coverage`.

- [ ] **Step 5: Reply and resolve the inline review thread**

Reply with the implementation summary and test evidence on comment
`PRRC_kwDOQ4Y4V87fEhW7`, then resolve thread
`PRRT_kwDOQ4Y4V86XjSJu` only after the pushed commit contains the fix.
