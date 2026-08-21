# Correction Survivors and Action State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one snapshot-native Correction Survivors policy and Action State workflow that behaves identically in live and static Scan, adds survivor context to both Daily Snapshot surfaces, and overlays the state on the live watchlist.

**Architecture:** A pure backend domain policy calculates eligibility, the five-pillar resilience score, and deterministic state precedence. The scan orchestrator assembles point-in-time inputs and persists a versioned compact projection in each result row; both SQL adapters, HTTP schemas, static export, and shared React components consume that projection without recalculating policy. Daily Snapshot aggregates persisted fields, while watchlist stewardship overlays cross-run state through the same precedence function.

**Tech Stack:** Python 3, frozen dataclasses and enums, FastAPI/Pydantic, SQLAlchemy/PostgreSQL JSON, Alembic, pytest, React, Material UI, TanStack Query/Virtual, Vitest, React Testing Library.

**Spec:** `docs/superpowers/specs/2026-08-21-correction-survivors-action-state-design.md`

## Global Constraints

- Public policy version is exactly `correction-survivors-v1`; nested schema version is integer `1`.
- Allowed Action States, in precedence order, are `exit_risk`, `deteriorating`, `event_risk`, `extended`, `data_limited`, `setup_ready`, and `watch`.
- Old rows without `opportunity_state` expose `action_state: null` and render “Not computed”; they are never inferred as `watch` or `data_limited`.
- `correction_survivor` is an eligibility result; `resilience_score` is a zero-to-100 explanation/sort key and cannot override failed gates.
- Market posture is advisory and cannot change survivor eligibility, score, or Action State.
- Use the existing Market-aware `minVolume` policy; do not add an absolute USD liquidity rule.
- Static bundles include compact opportunity evidence and continue excluding full `se_explain` and `se_candidates`.
- Watchlist stewardship remains a separate status and remains US-scoped.
- Static mode remains read-only and gains no user watchlist or telemetry writes.
- Static pages expose the workflow only when `marketEntry.features.opportunity_state === true`; a new-capability bundle may still contain mixed legacy rows, which render “Not computed” per row.
- Setup Follow-Through cohort analysis is outside this plan.

---

### Task 1: Pure Opportunity-State Domain Policy

**Files:**
- Create: `backend/app/domain/scanning/opportunity_state.py`
- Create: `backend/tests/unit/domain/test_opportunity_state.py`
- Modify: `backend/app/domain/scanning/__init__.py`

**Interfaces:**
- Consumes: only Python values; no database, clock, pandas, service, or settings imports.
- Produces: `ActionState`, `InvalidationEvidence`, `OpportunityInputs`, `OpportunityStateResult`, `EventDateAvailability`, `normalize_event_date(raw, key_present)`, `evaluate_opportunity_state(inputs)`, `opportunity_result_from_projection(projection)`, and `overlay_stewardship_state(result, stewardship_status, prior_run_available)`.

- [ ] **Step 1: Write failing tests for event normalization, every eligibility boundary, the exact score, and all state-precedence collisions**

```python
def complete_inputs(**changes):
    values = dict(
        market="US", mic="XNAS", as_of_date=date(2026, 8, 21),
        benchmark_symbol="SPY", benchmark_as_of_date=date(2026, 8, 21),
        benchmark_relative_return_65d=0.08,
        rs_rating_1m=90.0, rs_rating_3m=80.0,
        rs_line_new_high=True, rs_line_blue_dot=False,
        stage=2, ma_alignment=True,
        invalidation_evidence_available=True, invalidation_flags=(),
        setup_payload_available=True, pattern_primary="vcp",
        squeeze=True, tight_closes_count=3, quiet_days_count=3,
        volume_vs_50d=0.70, volume_dry_up_max=0.80,
        liquidity_available=True, liquidity_passes=True,
        feature_status="complete", is_scannable=True,
        event_calendar_available=True, earnings_soon=False,
        setup_ready=True, in_early_zone=True, extended=False,
        prior_run_required=False, prior_run_available=False,
        deterioration_confirmed=False, stewardship_status=None,
    )
    values.update(changes)
    return OpportunityInputs(**values)


def test_complete_survivor_has_exact_score_and_setup_ready_state():
    result = evaluate_opportunity_state(complete_inputs())
    assert result.correction_survivor is True
    assert result.resilience_score == 97.0
    assert result.action_state is ActionState.SETUP_READY


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"invalidation_flags": (InvalidationEvidence("breaks_50d_support", True),)}, ActionState.EXIT_RISK),
        ({"deterioration_confirmed": True}, ActionState.DETERIORATING),
        ({"earnings_soon": True}, ActionState.EVENT_RISK),
        ({"extended": True}, ActionState.EXTENDED),
        ({"event_calendar_available": False}, ActionState.DATA_LIMITED),
        ({"setup_ready": False}, ActionState.WATCH),
    ],
)
def test_action_state_precedence(changes, expected):
    assert evaluate_opportunity_state(complete_inputs(**changes)).action_state is expected


def test_higher_precedence_known_risk_wins_over_missing_data():
    inputs = complete_inputs(
        event_calendar_available=False,
        invalidation_flags=(InvalidationEvidence("breaks_50d_support", True),),
    )
    assert evaluate_opportunity_state(inputs).action_state is ActionState.EXIT_RISK


def test_invalid_event_string_is_unavailable_not_no_event():
    normalized = normalize_event_date("not-a-date", key_present=True)
    assert normalized.available is False
    assert normalized.value is None
    assert normalized.reason == "invalid_next_earnings_date"


def test_future_benchmark_date_is_rejected_as_data_limited():
    result = evaluate_opportunity_state(complete_inputs(
        benchmark_as_of_date=date(2026, 8, 22),
    ))
    assert result.action_state is ActionState.DATA_LIMITED
    assert "future_benchmark_date" in result.failed_checks


def test_projection_round_trip_preserves_typed_state():
    original = evaluate_opportunity_state(complete_inputs())
    restored = opportunity_result_from_projection(original.projection())
    assert restored == original
```

Also parameterize each leadership, trend, structure, liquidity, freshness, and required-evidence field independently. Assert missing score inputs return `resilience_score is None`, missing posture is not an input, absent prior-run data is ignored when `prior_run_required=False`, and stewardship `exit_risk` outranks a persisted `setup_ready` result.

- [ ] **Step 2: Run the domain tests and verify the module is missing**

Run: `cd backend && ./venv/bin/pytest tests/unit/domain/test_opportunity_state.py -q`

Expected: FAIL during collection with `ModuleNotFoundError: app.domain.scanning.opportunity_state`.

- [ ] **Step 3: Implement the immutable policy types and exact calculations**

```python
POLICY_VERSION = "correction-survivors-v1"
SCHEMA_VERSION = 1


class ActionState(str, Enum):
    EXIT_RISK = "exit_risk"
    DETERIORATING = "deteriorating"
    EVENT_RISK = "event_risk"
    EXTENDED = "extended"
    DATA_LIMITED = "data_limited"
    SETUP_READY = "setup_ready"
    WATCH = "watch"


@dataclass(frozen=True)
class InvalidationEvidence:
    code: str
    is_hard: bool


@dataclass(frozen=True)
class OpportunityStateResult:
    correction_survivor: bool
    resilience_score: float | None
    action_state: ActionState
    passed_checks: tuple[str, ...]
    failed_checks: tuple[str, ...]
    warnings: tuple[str, ...]
    action_reasons: tuple[str, ...]
    metrics: dict[str, object]
    data_availability: dict[str, str]
    market: str | None
    mic: str | None
    as_of_date: date | None
    benchmark_symbol: str | None
    benchmark_as_of_date: date | None

    def projection(self) -> dict[str, object]:
        evidence = {
            "schema_version": SCHEMA_VERSION,
            "policy_version": POLICY_VERSION,
            "as_of_date": self.as_of_date.isoformat() if self.as_of_date else None,
            "market": self.market,
            "mic": self.mic,
            "benchmark_symbol": self.benchmark_symbol,
            "benchmark_as_of_date": self.benchmark_as_of_date.isoformat() if self.benchmark_as_of_date else None,
            "passed_checks": list(self.passed_checks),
            "failed_checks": list(self.failed_checks),
            "warnings": list(self.warnings),
            "metrics": self.metrics,
            "data_availability": self.data_availability,
            "action_reasons": list(self.action_reasons),
        }
        return {
            "correction_survivor": self.correction_survivor,
            "resilience_score": self.resilience_score,
            "action_state": self.action_state.value,
            "opportunity_state": evidence,
        }


@dataclass(frozen=True)
class EventDateAvailability:
    value: date | None
    available: bool
    reason: str | None = None


def normalize_event_date(raw: object, *, key_present: bool) -> EventDateAvailability:
    if not key_present:
        return EventDateAvailability(None, False, "missing_event_calendar")
    if raw is None:
        return EventDateAvailability(None, True)
    if isinstance(raw, datetime):
        return EventDateAvailability(raw.date(), True)
    if isinstance(raw, date):
        return EventDateAvailability(raw, True)
    if isinstance(raw, str):
        try:
            return EventDateAvailability(date.fromisoformat(raw[:10]), True)
        except ValueError:
            return EventDateAvailability(None, False, "invalid_next_earnings_date")
    return EventDateAvailability(None, False, "invalid_next_earnings_date")
```

Implement `OpportunityInputs` with the exact named fields used by `complete_inputs`. Required-data detection must distinguish unknown from false. Compute the five pillars as:

```python
leadership = (12 if inputs.benchmark_relative_return_65d > 0 else 0) + (
    8 if inputs.rs_line_new_high or inputs.rs_line_blue_dot else 0
)
multi_horizon = 10 * clamp(inputs.rs_rating_1m) / 100 + 10 * clamp(inputs.rs_rating_3m) / 100
trend = 8 * (inputs.stage in (1, 2)) + 8 * bool(inputs.ma_alignment) + 4 * (not hard_invalidation)
structure = (
    8 * bool(inputs.pattern_primary)
    + 4 * bool(inputs.squeeze)
    + 3 * (inputs.tight_closes_count >= 3)
    + 3 * (inputs.quiet_days_count >= 3)
    + 2 * (inputs.volume_vs_50d <= inputs.volume_dry_up_max)
)
tradability = 10 * bool(inputs.liquidity_passes) + 10 * (
    inputs.feature_status == "complete" and inputs.is_scannable is True
)
score = round(leadership + multi_horizon + trend + structure + tradability, 1)
```

Eligibility is `required_complete and leadership_gate and trend_gate and structure_gate and liquidity_gate and freshness_gate`. Resolve Action State in the seven-item order from Global Constraints. `opportunity_result_from_projection` returns `None` for an absent legacy payload and rejects a malformed present payload. `overlay_stewardship_state` must preserve all evidence, add a stewardship reason, and return the original result when no higher-priority overlay applies.

Benchmark provenance is point-in-time: a benchmark date after the row `as_of_date` adds `future_benchmark_date`, makes required evidence incomplete, and cannot contribute to eligibility or score. A non-future date mismatch adds `benchmark_date_lag` to warnings but remains admissible because exchange holidays can differ; the persisted dates make that lag auditable.

- [ ] **Step 4: Run the domain tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/domain/test_opportunity_state.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the pure policy**

```bash
git add backend/app/domain/scanning/opportunity_state.py backend/app/domain/scanning/__init__.py backend/tests/unit/domain/test_opportunity_state.py
git commit -m "feat: add correction survivor domain policy"
```

### Task 2: Truthful Setup-Engine Risk Evidence

**Files:**
- Modify: `backend/app/analysis/patterns/models.py`
- Modify: `backend/app/analysis/patterns/report.py`
- Modify: `backend/app/scanners/setup_engine_screener.py`
- Modify: `backend/tests/unit/test_setup_engine_report_schema.py`
- Modify: `backend/tests/unit/test_setup_engine_screener.py`

**Interfaces:**
- Consumes: `normalize_event_date` from Task 1.
- Produces: every serialized invalidation flag carries `is_hard: bool`; persisted string/datetime/date earnings values are normalized before Setup Engine risk evaluation.

- [ ] **Step 1: Add failing contract and pipeline tests**

```python
def test_invalidation_payload_preserves_hardness():
    payload = InvalidationFlag("breaks_50d_support", is_hard=True).to_payload()
    assert payload["is_hard"] is True


def test_iso_earnings_date_triggers_event_flag(setup_engine_scanner, stock_data):
    stock_data.fundamentals["next_earnings_date"] = "2026-08-25"
    stock_data.price_data.index = stock_data.price_data.index[:-1].append(
        pd.DatetimeIndex(["2026-08-21"])
    )
    result = setup_engine_scanner.scan_stock("TEST", stock_data, {})
    flags = result.details["setup_engine"]["explain"]["invalidation_flags"]
    assert next(flag for flag in flags if flag["code"] == "earnings_soon")["is_hard"] is False
```

- [ ] **Step 2: Run targeted Setup Engine tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_setup_engine_report_schema.py tests/unit/test_setup_engine_screener.py -q`

Expected: FAIL because `is_hard` is dropped and string dates are skipped.

- [ ] **Step 3: Preserve hardness and use the shared date normalizer**

Add `is_hard: bool` to `InvalidationFlagPayload`, emit it in `InvalidationFlag.to_payload()`, and validate it in `validate_setup_engine_payload`. Replace the date-only branch in `SetupEngineScanner` with:

```python
fundamentals = data.fundamentals if isinstance(data.fundamentals, dict) else {}
event_date = normalize_event_date(
    fundamentals.get("next_earnings_date"),
    key_present="next_earnings_date" in fundamentals,
)
next_earnings_date = event_date.value if event_date.available else None
```

Keep Setup Engine permissive when the calendar is unavailable; the opportunity policy, not Setup Engine readiness, owns `data_limited`.

- [ ] **Step 4: Run Setup Engine contract tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_setup_engine_report_schema.py tests/unit/test_setup_engine_screener.py tests/unit/test_operational_flags.py -q`

Expected: PASS.

- [ ] **Step 5: Commit truthful risk evidence**

```bash
git add backend/app/analysis/patterns/models.py backend/app/analysis/patterns/report.py backend/app/scanners/setup_engine_screener.py backend/tests/unit/test_setup_engine_report_schema.py backend/tests/unit/test_setup_engine_screener.py
git commit -m "fix: preserve setup risk evidence"
```

### Task 3: Assemble and Materialize the Opportunity Projection

**Files:**
- Create: `backend/app/services/opportunity_state_service.py`
- Create: `backend/tests/unit/services/test_opportunity_state_service.py`
- Modify: `backend/app/scanners/scan_orchestrator.py`
- Modify: `backend/tests/unit/test_scan_orchestrator.py`
- Modify: `backend/tests/unit/use_cases/feature_store/test_build_daily_snapshot.py`

**Interfaces:**
- Consumes: `evaluate_opportunity_state`, `SetupEngineParameters`, `resolve_default_scan_filters`, `StockData`, and the orchestrator result dictionary.
- Produces: `build_opportunity_projection(result, stock_data, parameters) -> dict[str, object]` and `build_data_limited_projection(result, stock_data, reason) -> dict[str, object]`.

- [ ] **Step 1: Add failing assembly tests for Market/MIC, benchmark dates, liquidity, event availability, and safe degraded output**

```python
def test_build_projection_uses_market_benchmark_and_local_liquidity(stock_data, result):
    stock_data.market = "HK"
    stock_data.exchange = "HKEX"
    stock_data.benchmark_symbol = "^HSI"
    result["avg_dollar_volume"] = 9_000_000
    projection = build_opportunity_projection(result, stock_data, SetupEngineParameters())
    evidence = projection["opportunity_state"]
    assert evidence["market"] == "HK"
    assert evidence["mic"] == "XHKG"
    assert evidence["benchmark_symbol"] == "^HSI"
    assert evidence["metrics"]["liquidity_floor_local"] == 8_000_000
    assert evidence["metrics"]["liquidity_passes"] is True


def test_missing_event_key_is_data_limited(stock_data, result):
    stock_data.fundamentals.pop("next_earnings_date", None)
    projection = build_opportunity_projection(result, stock_data, SetupEngineParameters())
    assert projection["action_state"] == "data_limited"
    assert projection["opportunity_state"]["data_availability"]["event_calendar"] == "unavailable"
```

- [ ] **Step 2: Run the new service and orchestrator tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/services/test_opportunity_state_service.py tests/unit/test_scan_orchestrator.py -q`

Expected: FAIL because the service and projection do not exist.

- [ ] **Step 3: Implement the assembler and attach it once in the orchestrator**

```python
def build_opportunity_projection(
    result: Mapping[str, object],
    stock_data: StockData,
    parameters: SetupEngineParameters,
) -> dict[str, object]:
    setup = result.get("setup_engine") if isinstance(result.get("setup_engine"), dict) else None
    fundamentals = stock_data.fundamentals if isinstance(stock_data.fundamentals, dict) else {}
    event = normalize_event_date(
        fundamentals.get("next_earnings_date"),
        key_present="next_earnings_date" in fundamentals,
    )
    market = str(stock_data.market or "").upper() or None
    liquidity_floor = resolve_default_scan_filters(market).get("minVolume")
    avg_dollar_volume = finite_float(result.get("avg_dollar_volume"))
    flags = tuple(parse_invalidation_flags(setup)) if setup is not None else ()
    inputs = OpportunityInputs(
        market=market,
        mic=SecurityMasterResolver.resolve_exchange_mic(market, stock_data.exchange),
        as_of_date=last_frame_date(stock_data.price_data),
        benchmark_symbol=stock_data.benchmark_symbol,
        benchmark_as_of_date=last_frame_date(stock_data.benchmark_data),
        benchmark_relative_return_65d=number_from(setup, "rs_vs_spy_65d"),
        rs_rating_1m=finite_float(result.get("rs_rating_1m")),
        rs_rating_3m=finite_float(result.get("rs_rating_3m")),
        rs_line_new_high=bool_from(setup, "rs_line_new_high"),
        rs_line_blue_dot=bool_from(setup, "rs_line_blue_dot"),
        stage=integer_or_none(result.get("stage")),
        ma_alignment=bool_or_none(result.get("ma_alignment")),
        invalidation_evidence_available=setup is not None,
        invalidation_flags=flags,
        setup_payload_available=setup is not None,
        pattern_primary=text_or_none(setup, "pattern_primary"),
        squeeze=bool_from(setup, "bb_squeeze"),
        tight_closes_count=integer_from(setup, "tight_closes_count"),
        quiet_days_count=integer_from(setup, "quiet_days_10d"),
        volume_vs_50d=number_from(setup, "volume_vs_50d"),
        volume_dry_up_max=parameters.volume_vs_50d_max_for_ready,
        liquidity_available=liquidity_floor is not None and avg_dollar_volume is not None,
        liquidity_passes=(avg_dollar_volume >= liquidity_floor) if liquidity_floor is not None and avg_dollar_volume is not None else None,
        feature_status=text_or_none(result, "data_status"),
        is_scannable=bool_or_none(result.get("is_scannable")),
        event_calendar_available=event.available,
        earnings_soon=event_is_inside_window(event.value, last_frame_date(stock_data.price_data), parameters.earnings_soon_window_days) if event.available else None,
        setup_ready=bool_from(setup, "setup_ready"),
        in_early_zone=bool_from(setup, "in_early_zone"),
        extended=bool_from(setup, "extended_from_pivot"),
    )
    return evaluate_opportunity_state(inputs).projection()
```

Build effective parameters with `build_setup_engine_parameters((criteria or {}).get("setup_engine_parameters"))`. In `_combine_results`, attach the projection after `avg_dollar_volume` is known and before return. Attach an explicit data-limited projection to `_insufficient_data_result`. Unexpected policy assembly errors must produce a structured `data_limited` projection with reason `opportunity_policy_error`; add a chunk-level assertion in the feature snapshot use case that every persisted non-error row has all four opportunity keys, so systemic omission fails the run rather than publishing an indistinguishable partial snapshot.

- [ ] **Step 4: Run materialization tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/services/test_opportunity_state_service.py tests/unit/test_scan_orchestrator.py tests/unit/use_cases/feature_store/test_build_daily_snapshot.py -q`

Expected: PASS, including a snapshot-row round trip with the four new keys.

- [ ] **Step 5: Commit materialization**

```bash
git add backend/app/services/opportunity_state_service.py backend/app/scanners/scan_orchestrator.py backend/tests/unit/services/test_opportunity_state_service.py backend/tests/unit/test_scan_orchestrator.py backend/tests/unit/use_cases/feature_store/test_build_daily_snapshot.py
git commit -m "feat: materialize opportunity state in scans"
```

### Task 4: Query, Repository, HTTP, and Static Row Contract

**Files:**
- Create: `backend/app/schemas/opportunity_state.py`
- Modify: `backend/app/schemas/scanning.py`
- Modify: `backend/app/infra/query/feature_store_query.py`
- Modify: `backend/app/infra/query/scan_result_query.py`
- Modify: `backend/app/infra/db/repositories/feature_store_repo.py`
- Modify: `backend/app/infra/db/repositories/scan_result_repo.py`
- Modify: `backend/app/domain/scanning/scan_filter_fields.json`
- Modify: `frontend/src/features/scan/scanFilterFields.json`
- Modify: `frontend/src/features/scan/defaultFilters.js`
- Modify: `frontend/src/static/scanClient.js`
- Modify: `backend/app/services/static_site_export_service.py`
- Modify: `backend/tests/integration/test_feature_store_scan_results.py`
- Modify: `backend/tests/integration/test_scan_result_repo_enrichment.py`
- Modify: `backend/tests/unit/test_feature_store_query_builder.py`
- Modify: `backend/tests/unit/test_static_site_export_service.py`
- Modify: `frontend/src/static/scanClient.test.js`

**Interfaces:**
- Consumes: four top-level keys materialized by Task 3.
- Produces: typed `OpportunityStateResponse`; filter/sort fields `correction_survivor`, `resilience_score`, `action_state`; static scan schema `static-scan-v2`; scan- and Market-manifest capability `features.opportunity_state`.

- [ ] **Step 1: Write failing mapping, filtering, sorting, legacy-null, and compact-static tests**

```python
def test_feature_row_maps_compact_opportunity_contract(feature_row, joined):
    feature_row.details_json.update(OPPORTUNITY_PROJECTION)
    item = _map_feature_to_scan_result(feature_row, joined, False, include_setup_payload=False)
    response = ScanResultItem.from_domain(item, include_setup_payload=False)
    assert response.correction_survivor is True
    assert response.resilience_score == 84.0
    assert response.action_state == "setup_ready"
    assert response.opportunity_state.policy_version == "correction-survivors-v1"
    assert response.se_explain is None


def test_legacy_row_keeps_not_computed_nulls(feature_row, joined):
    item = _map_feature_to_scan_result(feature_row, joined, False)
    response = ScanResultItem.from_domain(item)
    assert response.correction_survivor is None
    assert response.resilience_score is None
    assert response.action_state is None
    assert response.opportunity_state is None
```

Add SQL tests that filter `correction_survivor=True`, filter `action_state in ("setup_ready",)`, and sort `resilience_score DESC NULLS LAST, symbol ASC` in both adapters. Add static export assertions that compact evidence survives while `se_explain` and `se_candidates` remain absent, and that both the scan manifest and its owning Market manifest publish `features.opportunity_state: true`.

- [ ] **Step 2: Run contract tests**

Run: `cd backend && ./venv/bin/pytest tests/integration/test_feature_store_scan_results.py tests/integration/test_scan_result_repo_enrichment.py tests/unit/test_feature_store_query_builder.py tests/unit/test_static_site_export_service.py -q`

Run: `cd frontend && npx vitest run src/static/scanClient.test.js`

Expected: FAIL because fields are neither registered nor serialized.

- [ ] **Step 3: Add the typed contract and both adapter bindings**

```python
class OpportunityStateResponse(BaseModel):
    schema_version: Literal[1]
    policy_version: Literal["correction-survivors-v1"]
    as_of_date: str | None = None
    market: str | None = None
    mic: str | None = None
    benchmark_symbol: str | None = None
    benchmark_as_of_date: str | None = None
    passed_checks: list[str] = Field(default_factory=list)
    failed_checks: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    data_availability: dict[str, str] = Field(default_factory=dict)
    action_reasons: list[str] = Field(default_factory=list)
```

Add optional fields to `ScanResultItem`, copy them from `extended_fields` in `from_domain`, and copy them from top-level row details in both repository mappers. Add these bindings to both query adapters:

```python
"correction_survivor": ("correction_survivor",),
"resilience_score": ("resilience_score",),
"action_state": ("action_state",),
```

Add the same three entries to both filter JSON files: range/sortable `resilience_score`, boolean/sortable `correction_survivor` with legacy key `correctionSurvivor`, and categorical/sortable `action_state` with the seven fixed options. Add `correctionSurvivor: null` to frontend defaults. Extend `sortStaticScanRows` so `resilience_score` descending uses numeric comparison with nulls last and symbol as the stable tie-break, matching SQL. Bump `SCAN_BUNDLE_SCHEMA_VERSION` to `static-scan-v2`, add `features.opportunity_state: true` to new scan and Market manifests, and leave the compact projection untouched by `_details_without_setup_payload`.

- [ ] **Step 4: Run adapter, schema, contract-drift, and static tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/domain/test_filter_capabilities.py tests/unit/test_feature_store_query_builder.py tests/integration/test_feature_store_scan_results.py tests/integration/test_scan_result_repo_enrichment.py tests/unit/test_static_site_export_service.py -q`

Run: `cd frontend && npx vitest run src/static/scanClient.test.js src/features/scan/filterExpression.test.js`

Expected: PASS.

- [ ] **Step 5: Commit the delivery contract**

```bash
git add backend/app/schemas/opportunity_state.py backend/app/schemas/scanning.py backend/app/infra/query/feature_store_query.py backend/app/infra/query/scan_result_query.py backend/app/infra/db/repositories/feature_store_repo.py backend/app/infra/db/repositories/scan_result_repo.py backend/app/domain/scanning/scan_filter_fields.json frontend/src/features/scan/scanFilterFields.json frontend/src/features/scan/defaultFilters.js frontend/src/static/scanClient.js backend/app/services/static_site_export_service.py backend/tests/integration/test_feature_store_scan_results.py backend/tests/integration/test_scan_result_repo_enrichment.py backend/tests/unit/test_feature_store_query_builder.py backend/tests/unit/test_static_site_export_service.py frontend/src/static/scanClient.test.js
git commit -m "feat: expose opportunity state in scan rows"
```

### Task 5: Correction Survivors Preset and Database Indexes

**Files:**
- Modify: `backend/app/services/preset_screens.py`
- Create: `backend/alembic/versions/20260821_0028_seed_correction_survivors_preset.py`
- Create: `backend/tests/unit/test_seed_correction_survivors_preset_migration.py`
- Modify: `backend/tests/unit/test_preset_screens.py`
- Modify: `backend/tests/unit/test_feature_store_index_drift.py`
- Modify: `frontend/src/features/scan/hooks/useScanFilterPresets.test.jsx`
- Modify: `frontend/src/static/pages/StaticScanPage.test.jsx`

**Interfaces:**
- Consumes: `correctionSurvivor` and `resilience_score` from Task 4.
- Produces: static preset id `correction_survivors`; live preset name `Correction Survivors`; PostgreSQL indexes for survivor filtering and resilience sorting.

- [ ] **Step 1: Add failing static/live parity, migration safety, and preset-selection tests**

```python
def test_correction_survivor_preset_contract():
    screen = next(item for item in PRESET_SCREENS if item["id"] == "correction_survivors")
    assert screen["filters"] == {"correctionSurvivor": True}
    assert screen["sort_by"] == "resilience_score"
    assert screen["sort_order"] == "desc"


def test_live_seed_matches_static_semantics():
    static = next(item for item in PRESET_SCREENS if item["id"] == "correction_survivors")
    live = migration.CORRECTION_SURVIVORS_PRESET
    assert live["filter_overrides"] == static["filters"]
    assert (live["sort_by"], live["sort_order"]) == (static["sort_by"], static["sort_order"])
```

Migration tests must prove upgrade skips a pre-existing user preset, records only inserted ids, downgrade removes only an unchanged migration-owned row, and preserves a user-edited seeded row.

- [ ] **Step 2: Run preset and migration tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_preset_screens.py tests/unit/test_seed_correction_survivors_preset_migration.py tests/unit/test_feature_store_index_drift.py -q`

Run: `cd frontend && npx vitest run src/features/scan/hooks/useScanFilterPresets.test.jsx src/static/pages/StaticScanPage.test.jsx`

Expected: FAIL because the preset and migration do not exist.

- [ ] **Step 3: Add the preset, forward-only seed, and matching indexes**

```python
CORRECTION_SURVIVORS_PRESET = {
    "name": "Correction Survivors",
    "description": "Leaders that held trend and relative-strength evidence through a correction.",
    "filter_overrides": {"correctionSurvivor": True},
    "sort_by": "resilience_score",
    "sort_order": "desc",
}
```

The migration revision is `20260821_0028` with `down_revision = "20260808_0027"`. Build the live full filter shape by adding `correctionSurvivor: None` to the migration's local empty shape and overlaying `True`. Use the audit-table ownership pattern from `20260523_0019_seed_pocket_pivot_pattern_filter_presets.py`.

On PostgreSQL create:

```sql
CREATE INDEX IF NOT EXISTS ix_sfd_run_correction_survivor
ON stock_feature_daily (run_id, (lower(details_json ->> 'correction_survivor')));

CREATE INDEX IF NOT EXISTS ix_sfd_run_resilience_score
ON stock_feature_daily (run_id, (CAST(details_json ->> 'resilience_score' AS FLOAT)));
```

Extend the index drift test so the resilience expression matches `json_number`; compile the boolean predicate and assert it uses the same top-level JSON key. The preset description, filter, and sort must match static exactly apart from terminal punctuation conventions already used by live seeds.

- [ ] **Step 4: Run preset, migration, and UI-selection tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_preset_screens.py tests/unit/test_seed_correction_survivors_preset_migration.py tests/unit/test_feature_store_index_drift.py -q`

Run: `cd frontend && npx vitest run src/features/scan/hooks/useScanFilterPresets.test.jsx src/static/pages/StaticScanPage.test.jsx`

Expected: PASS.

- [ ] **Step 5: Commit preset parity**

```bash
git add backend/app/services/preset_screens.py backend/alembic/versions/20260821_0028_seed_correction_survivors_preset.py backend/tests/unit/test_seed_correction_survivors_preset_migration.py backend/tests/unit/test_preset_screens.py backend/tests/unit/test_feature_store_index_drift.py frontend/src/features/scan/hooks/useScanFilterPresets.test.jsx frontend/src/static/pages/StaticScanPage.test.jsx
git commit -m "feat: add correction survivors preset"
```

### Task 6: Shared Action Badge and Evidence Drawer

**Files:**
- Create: `frontend/src/features/opportunityState/actionState.js`
- Create: `frontend/src/components/shared/ActionStateBadge.jsx`
- Create: `frontend/src/components/shared/ActionStateBadge.test.jsx`
- Create: `frontend/src/components/shared/OpportunityEvidenceDrawer.jsx`
- Create: `frontend/src/components/shared/OpportunityEvidenceDrawer.test.jsx`

**Interfaces:**
- Consumes: `action_state`, `resilience_score`, and `opportunity_state` row fields.
- Produces: `ActionStateBadge({ state, onClick })` and `OpportunityEvidenceDrawer({ open, row, onClose, onEvidenceOpen })`.

- [ ] **Step 1: Add failing rendering and interaction tests for all states and legacy rows**

```jsx
it.each([
  ['exit_risk', 'Exit Risk'], ['deteriorating', 'Deteriorating'],
  ['event_risk', 'Event Risk'], ['extended', 'Extended'],
  ['data_limited', 'Data Limited'], ['setup_ready', 'Setup Ready'],
  ['watch', 'Watch'], [null, 'Not computed'],
])('renders %s as %s', (state, label) => {
  render(<ActionStateBadge state={state} />);
  expect(screen.getByText(label)).toBeInTheDocument();
});


it('renders compact evidence without chart or setup payloads', () => {
  render(<OpportunityEvidenceDrawer open row={OPPORTUNITY_ROW} onClose={vi.fn()} />);
  expect(screen.getByText('Resilience score')).toBeInTheDocument();
  expect(screen.getByText('SPY')).toBeInTheDocument();
  expect(screen.getByText('XNAS')).toBeInTheDocument();
  expect(screen.queryByText('Chart')).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run component tests**

Run: `cd frontend && npx vitest run src/components/shared/ActionStateBadge.test.jsx src/components/shared/OpportunityEvidenceDrawer.test.jsx`

Expected: FAIL because the components do not exist.

- [ ] **Step 3: Implement centralized labels/colors and the drawer**

```javascript
export const ACTION_STATE_META = Object.freeze({
  exit_risk: { label: 'Exit Risk', color: 'error' },
  deteriorating: { label: 'Deteriorating', color: 'warning' },
  event_risk: { label: 'Event Risk', color: 'warning' },
  extended: { label: 'Extended', color: 'info' },
  data_limited: { label: 'Data Limited', color: 'default' },
  setup_ready: { label: 'Setup Ready', color: 'success' },
  watch: { label: 'Watch', color: 'default' },
});

export function actionStateMeta(state) {
  return ACTION_STATE_META[state] ?? { label: 'Not computed', color: 'default' };
}
```

Use an interactive MUI `Chip` only when `onClick` exists. The drawer shows the badge, score, five named pillar values, passed/failed checks, warnings, action reasons, Market/MIC, benchmark and both dates. Fire `onEvidenceOpen(row)` once on closed-to-open transition; never include the symbol in the callback payload used for telemetry.

- [ ] **Step 4: Run shared component tests**

Run: `cd frontend && npx vitest run src/components/shared/ActionStateBadge.test.jsx src/components/shared/OpportunityEvidenceDrawer.test.jsx`

Expected: PASS.

- [ ] **Step 5: Commit shared presentation**

```bash
git add frontend/src/features/opportunityState/actionState.js frontend/src/components/shared/ActionStateBadge.jsx frontend/src/components/shared/ActionStateBadge.test.jsx frontend/src/components/shared/OpportunityEvidenceDrawer.jsx frontend/src/components/shared/OpportunityEvidenceDrawer.test.jsx
git commit -m "feat: add opportunity state presentation"
```

### Task 7: Shared Results Table Integration for Live and Static Scan

**Files:**
- Modify: `frontend/src/components/Scan/ResultsTable.jsx`
- Modify: `frontend/src/components/Scan/ResultsTable.test.jsx`
- Modify: `frontend/src/test/fixtures/setupEngineFixtures.js`
- Modify: `frontend/src/features/scan/components/ScanResultsSection.jsx`
- Modify: `frontend/src/features/scan/components/ScanResultsSection.test.jsx`
- Modify: `frontend/src/static/pages/StaticScanPage.jsx`
- Modify: `frontend/src/static/pages/StaticScanPage.test.jsx`

**Interfaces:**
- Consumes: shared badge/drawer from Task 6.
- Produces: sortable `resilience_score` column, Action State column, one table-level evidence drawer; `showOpportunityState` capability prop; optional `opportunityTelemetrySurface` prop (`"scan"` in live mode, undefined in static mode).

- [ ] **Step 1: Add failing live/static table tests**

```jsx
it('opens opportunity evidence without opening the chart', async () => {
  const onOpenChart = vi.fn();
  renderWithProviders(<ResultsTable {...defaultProps} results={[opportunityRow]} onOpenChart={onOpenChart} />);
  await userEvent.click(screen.getByText('Setup Ready'));
  expect(screen.getByRole('presentation')).toHaveTextContent('Resilience score');
  expect(onOpenChart).not.toHaveBeenCalled();
});

it('renders legacy rows as Not computed', () => {
  renderWithProviders(<ResultsTable {...defaultProps} results={[legacyRow]} />);
  expect(screen.getByText('Not computed')).toBeInTheDocument();
});
```

Add a static-page test using a row with no chart bundle; the Action State drawer must still open.

Add a legacy-bundle test with no `marketEntry.features.opportunity_state`: the Correction Survivors preset and both new columns are absent. Add a mixed-row test with the capability enabled: legacy rows inside that new bundle render “Not computed.”

- [ ] **Step 2: Run Results table and static Scan tests**

Run: `cd frontend && npx vitest run src/components/Scan/ResultsTable.test.jsx src/features/scan/components/ScanResultsSection.test.jsx src/static/pages/StaticScanPage.test.jsx`

Expected: FAIL because the columns and drawer are absent.

- [ ] **Step 3: Add the columns, one selected-row state, and memo dependencies**

```jsx
const [opportunityRow, setOpportunityRow] = useState(null);

// Column definitions, adjacent to the Setup Engine columns.
{ id: 'resilience_score', label: 'Res', sortable: true, width: 48 },
{ id: 'action_state', label: 'Action', sortable: true, width: 105 },

<ActionStateBadge
  state={row.action_state}
  onClick={row.opportunity_state ? (event) => {
      event.stopPropagation();
      onOpenOpportunity(row);
    } : undefined}
/>

<OpportunityEvidenceDrawer
  open={Boolean(opportunityRow)}
  row={opportunityRow}
  onClose={() => setOpportunityRow(null)}
  onEvidenceOpen={handleOpportunityEvidenceOpen}
/>
```

Update the virtual-row memo comparator for `resilience_score`, `action_state`, and `opportunity_state`. Increase table minimum width by the exact 153 pixels only when `showOpportunityState` is true. Default `showOpportunityState` to true for the live component path and pass it explicitly from `StaticScanPage` as `marketEntry.features?.opportunity_state === true`. Filter the `correction_survivors` preset from the static preset list when that capability is absent. Pass `opportunityTelemetrySurface="scan"` from the live `ScanResultsSection`; do not pass it from `StaticScanPage`.

- [ ] **Step 4: Run shared Scan UI tests**

Run: `cd frontend && npx vitest run src/components/Scan/ResultsTable.test.jsx src/components/Scan/ResultsTable.market.test.jsx src/features/scan/components/ScanResultsSection.test.jsx src/static/pages/StaticScanPage.test.jsx`

Expected: PASS.

- [ ] **Step 5: Commit live/static Scan UI**

```bash
git add frontend/src/components/Scan/ResultsTable.jsx frontend/src/components/Scan/ResultsTable.test.jsx frontend/src/test/fixtures/setupEngineFixtures.js frontend/src/features/scan/components/ScanResultsSection.jsx frontend/src/features/scan/components/ScanResultsSection.test.jsx frontend/src/static/pages/StaticScanPage.jsx frontend/src/static/pages/StaticScanPage.test.jsx
git commit -m "feat: show action state in scan results"
```

### Task 8: Live Daily Snapshot Survivor Aggregation

**Files:**
- Modify: `backend/app/services/daily_snapshot_service.py`
- Modify: `backend/tests/unit/test_daily_snapshot_service.py`

**Interfaces:**
- Consumes: persisted query fields from Task 4.
- Produces: Daily Snapshot schema version `4` and `correction_survivors = {available, complete, count, counts_by_action_state, rows}`.

- [ ] **Step 1: Add failing aggregate, posture-independence, empty, and unavailable tests**

```python
def test_daily_snapshot_contains_ranked_survivor_summary(snapshot_fixture):
    payload = build_daily_snapshot_payload(**snapshot_fixture)
    summary = payload["correction_survivors"]
    assert summary["available"] is True
    assert summary["complete"] is True
    assert summary["count"] == 3
    assert summary["counts_by_action_state"]["setup_ready"] == 1
    assert [row["symbol"] for row in summary["rows"]] == ["AAA", "BBB", "CCC"]


def test_missing_market_posture_does_not_remove_survivors(snapshot_fixture, monkeypatch):
    monkeypatch.setattr(daily_snapshot_service, "build_exposure_payload", lambda *args, **kwargs: None)
    payload = build_daily_snapshot_payload(**snapshot_fixture)
    assert payload["correction_survivors"]["count"] == 3
```

- [ ] **Step 2: Run Daily Snapshot service tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_daily_snapshot_service.py -q`

Expected: FAIL because the aggregate is absent.

- [ ] **Step 3: Generalize the query helper and build exact counts**

Change `_query_scan_rows` to accept `sort`, `per_page`, and `include_sparklines`, and return `(rows, total)`. Query the top 20 with `BooleanFilter("correction_survivor", True)` and `SortSpec("resilience_score", DESC)`. For each of the seven Action States, execute a count query using the survivor boolean plus `CategoricalFilter("action_state", (state,))`; read `result.page.total` and serialize at most one row. When there is no scan, return:

```python
{
    "available": False,
    "complete": False,
    "count": 0,
    "counts_by_action_state": {state: 0 for state in ACTION_STATE_VALUES},
    "rows": [],
}
```

When a scan exists and has zero survivors, return `available=True`, `complete=True`, and zero counts. Increment `DAILY_SNAPSHOT_SCHEMA_VERSION` to `4`, which automatically rotates the Redis and memory cache key.

- [ ] **Step 4: Run Daily Snapshot tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_daily_snapshot_service.py -q`

Expected: PASS.

- [ ] **Step 5: Commit live aggregation**

```bash
git add backend/app/services/daily_snapshot_service.py backend/tests/unit/test_daily_snapshot_service.py
git commit -m "feat: aggregate correction survivors in daily snapshot"
```

### Task 9: Shared Daily Survivor Panel in Live and Static Home

**Files:**
- Create: `frontend/src/features/opportunityState/correctionSurvivorSummary.js`
- Create: `frontend/src/features/opportunityState/correctionSurvivorSummary.test.js`
- Create: `frontend/src/components/shared/CorrectionSurvivorsPanel.jsx`
- Create: `frontend/src/components/shared/CorrectionSurvivorsPanel.test.jsx`
- Modify: `frontend/src/components/shared/DailyScanRowsTable.jsx`
- Modify: `frontend/src/components/MarketScan/DailyMarketSnapshotTab.jsx`
- Modify: `frontend/src/components/MarketScan/DailyMarketSnapshotTab.test.jsx`
- Modify: `frontend/src/static/pages/StaticHomePage.jsx`
- Modify: `frontend/src/static/pages/StaticHomePage.test.jsx`

**Interfaces:**
- Consumes: live `correction_survivors`, static persisted scan rows, `marketEntry.features.opportunity_state`, and existing `market_health_exposure`.
- Produces: `buildCorrectionSurvivorSummary(rows, { complete })` and `CorrectionSurvivorsPanel({ summary, posture, ...chartProps })`.

- [ ] **Step 1: Add failing summary and parity tests**

```javascript
it('summarizes only persisted survivor rows with stable resilience ordering', () => {
  const summary = buildCorrectionSurvivorSummary(rows, { complete: true });
  expect(summary.count).toBe(2);
  expect(summary.counts_by_action_state.setup_ready).toBe(1);
  expect(summary.rows.map((row) => row.symbol)).toEqual(['AAA', 'BBB']);
});

it('marks a partial static chunk load incomplete', () => {
  expect(buildCorrectionSurvivorSummary(rows, { complete: false })).toMatchObject({
    available: false,
    complete: false,
  });
});
```

Add live and static page tests asserting the same survivor ordering, state counts, posture label, zero-result copy, and “Survivor data incomplete” copy. The static test must change the manifest preset filter/sort and prove the panel follows that manifest definition, so it cannot silently drift to a separately hard-coded filter.

Add a static legacy-capability test proving the entire survivor panel is absent when `features.opportunity_state` is missing; this must not be rendered as a valid zero-survivor result.

- [ ] **Step 2: Run panel and page tests**

Run: `cd frontend && npx vitest run src/features/opportunityState/correctionSurvivorSummary.test.js src/components/shared/CorrectionSurvivorsPanel.test.jsx src/components/MarketScan/DailyMarketSnapshotTab.test.jsx src/static/pages/StaticHomePage.test.jsx`

Expected: FAIL because the summary and panel do not exist.

- [ ] **Step 3: Implement persisted-field aggregation and shared presentation**

```javascript
export function buildCorrectionSurvivorSummary(rows, { complete }) {
  if (!complete) return { available: false, complete: false, count: 0, counts_by_action_state: {}, rows: [] };
  const survivors = rows
    .filter((row) => row.correction_survivor === true)
    .sort((left, right) => (
      (right.resilience_score ?? -Infinity) - (left.resilience_score ?? -Infinity)
      || String(left.symbol).localeCompare(String(right.symbol))
    ));
  return {
    available: true,
    complete: true,
    count: survivors.length,
    counts_by_action_state: countByActionState(survivors),
    rows: survivors.slice(0, 20),
  };
}
```

Extend `DailyScanRowsTable` with `scoreField="composite_score"`, `showActionState`, and `onOpenOpportunity`; use `resilience_score` for this panel. The panel renders total and seven state chips, posture `stance` with its date/benchmark, and the shared evidence drawer. If posture is absent, show “Market posture unavailable” without hiding rows.

Only load/aggregate the static survivor workflow when `marketEntry.features?.opportunity_state === true`. Resolve the `correction_survivors` entry from `scanBundleQuery.data.presetScreens`, apply it through the existing `buildFiltersFromPreset`, `filterStaticScanRows`, and `sortStaticScanRows` helpers, then pass those persisted rows to the summary helper. Change `StaticHomePage` chunk loading from `Promise.all` to `Promise.allSettled`, retain successful chunks, and return `complete: failedChunks.length === 0 && rowsBySymbol.size >= rows_total`. This permits the page to render existing sections while marking survivor aggregation incomplete. Live passes `opportunityTelemetrySurface="daily"`; static omits telemetry.

- [ ] **Step 4: Run Daily UI parity tests**

Run: `cd frontend && npx vitest run src/features/opportunityState/correctionSurvivorSummary.test.js src/components/shared/CorrectionSurvivorsPanel.test.jsx src/components/MarketScan/DailyMarketSnapshotTab.test.jsx src/static/pages/StaticHomePage.test.jsx`

Expected: PASS.

- [ ] **Step 5: Commit Daily survivor workflow**

```bash
git add frontend/src/features/opportunityState/correctionSurvivorSummary.js frontend/src/features/opportunityState/correctionSurvivorSummary.test.js frontend/src/components/shared/CorrectionSurvivorsPanel.jsx frontend/src/components/shared/CorrectionSurvivorsPanel.test.jsx frontend/src/components/shared/DailyScanRowsTable.jsx frontend/src/components/MarketScan/DailyMarketSnapshotTab.jsx frontend/src/components/MarketScan/DailyMarketSnapshotTab.test.jsx frontend/src/static/pages/StaticHomePage.jsx frontend/src/static/pages/StaticHomePage.test.jsx
git commit -m "feat: add correction survivors daily panel"
```

### Task 10: Live Watchlist Action-State Overlay

**Files:**
- Modify: `backend/app/schemas/user_watchlist.py`
- Modify: `backend/app/services/watchlist_stewardship_service.py`
- Modify: `backend/tests/unit/test_watchlist_stewardship_service.py`
- Modify: `frontend/src/components/MarketScan/WatchlistTable.jsx`
- Create: `frontend/src/components/MarketScan/WatchlistTable.test.jsx`

**Interfaces:**
- Consumes: persisted current projection and `overlay_stewardship_state` from Task 1.
- Produces: optional `correction_survivor`, `resilience_score`, `action_state`, and `opportunity_state` on `WatchlistStewardshipItem`; separate Stewardship and Action columns.

- [ ] **Step 1: Add failing backend overlay and frontend separation tests**

```python
def test_watchlist_exit_stewardship_overlays_setup_ready_projection(service, rows):
    rows.current.details_json.update(SETUP_READY_PROJECTION)
    item = service._build_item(current_row=rows.current, previous_row=rows.previous, **ITEM_ARGS)
    assert item.status == "exit_risk"
    assert item.action_state == "exit_risk"
    assert item.opportunity_state.action_reasons[-1] == "stewardship_exit_risk"


def test_legacy_watchlist_row_remains_not_computed(service, rows):
    item = service._build_item(current_row=rows.current, previous_row=rows.previous, **ITEM_ARGS)
    assert item.action_state is None
    assert item.opportunity_state is None
```

```jsx
it('shows stewardship and Action State as separate columns', async () => {
  renderWithProviders(<WatchlistTable {...props} />);
  expect(screen.getByRole('columnheader', { name: 'Stewardship' })).toBeInTheDocument();
  expect(screen.getByRole('columnheader', { name: 'Action' })).toBeInTheDocument();
  await userEvent.click(screen.getByText('Setup Ready'));
  expect(screen.getByText('Resilience score')).toBeInTheDocument();
});
```

- [ ] **Step 2: Run watchlist tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_watchlist_stewardship_service.py -q`

Run: `cd frontend && npx vitest run src/components/MarketScan/WatchlistTable.test.jsx`

Expected: FAIL because the overlay fields and Action column are absent.

- [ ] **Step 3: Overlay new rows while preserving legacy and stewardship semantics**

Parse the current row's four opportunity keys. If `opportunity_state` is absent, return null opportunity fields even when stewardship has a risk label. Otherwise call `opportunity_result_from_projection` and then:

```python
overlaid = overlay_stewardship_state(
    current_result,
    stewardship_status=status,
    prior_run_available=previous_row is not None,
)
```

Serialize the overlaid projection into `WatchlistStewardshipItem`. Rename the existing UI header from `Status` to `Stewardship`, add the shared Action State badge and one drawer, stop badge clicks from opening the chart, and pass telemetry surface `watchlist`.

- [ ] **Step 4: Run watchlist backend and frontend tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_watchlist_stewardship_service.py tests/unit/test_user_watchlists_data_endpoint.py -q`

Run: `cd frontend && npx vitest run src/components/MarketScan/WatchlistTable.test.jsx src/components/MarketScan/WatchlistsTab.test.jsx`

Expected: PASS.

- [ ] **Step 5: Commit the watchlist overlay**

```bash
git add backend/app/schemas/user_watchlist.py backend/app/services/watchlist_stewardship_service.py backend/tests/unit/test_watchlist_stewardship_service.py frontend/src/components/MarketScan/WatchlistTable.jsx frontend/src/components/MarketScan/WatchlistTable.test.jsx
git commit -m "feat: overlay action state on watchlists"
```

### Task 11: Privacy-Safe Opportunity Telemetry

**Files:**
- Modify: `backend/app/services/telemetry/schema.py`
- Modify: `backend/app/services/telemetry/per_market_telemetry.py`
- Modify: `backend/app/api/v1/telemetry.py`
- Modify: `backend/app/interfaces/tasks/feature_store_tasks.py`
- Modify: `backend/tests/unit/test_per_market_telemetry.py`
- Create: `backend/tests/unit/test_opportunity_telemetry_api.py`
- Modify: `frontend/src/api/telemetry.js`
- Create: `frontend/src/features/opportunityState/opportunityTelemetry.js`
- Create: `frontend/src/features/opportunityState/opportunityTelemetry.test.js`
- Modify: `frontend/src/components/shared/OpportunityEvidenceDrawer.jsx`

**Interfaces:**
- Consumes: published feature-run details and the optional telemetry surface props from Tasks 7, 9, and 10.
- Produces: `MetricKey.OPPORTUNITY_STATE`, `MetricKey.OPPORTUNITY_EVIDENCE_OPEN`, one snapshot gauge/event, and a symbol-free evidence-open counter.

- [ ] **Step 1: Add failing payload, database aggregation, endpoint-validation, and frontend best-effort tests**

```python
def test_opportunity_payload_contains_counts_but_no_symbols():
    payload = opportunity_state_payload(
        run_id=42, rows_total=100, survivor_count=12,
        action_state_counts={"setup_ready": 3, "data_limited": 4},
    )
    assert payload["unknown_input_rate"] == pytest.approx(0.04)
    assert "symbol" not in json.dumps(payload).lower()


def test_evidence_open_rejects_unknown_surface(client):
    response = client.post("/v1/telemetry/opportunity/evidence-open", json={"market": "US", "surface": "other"})
    assert response.status_code == 422
```

```javascript
it('sends only market and allowed surface and swallows network failure', async () => {
  apiClient.post.mockRejectedValue(new Error('offline'));
  await expect(recordOpportunityEvidenceOpen('US', 'scan')).resolves.toBeUndefined();
  expect(apiClient.post).toHaveBeenCalledWith('/v1/telemetry/opportunity/evidence-open', {
    market: 'US', surface: 'scan',
  });
});
```

- [ ] **Step 2: Run telemetry tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_per_market_telemetry.py tests/unit/test_opportunity_telemetry_api.py -q`

Run: `cd frontend && npx vitest run src/features/opportunityState/opportunityTelemetry.test.js`

Expected: FAIL because the metrics and endpoint do not exist.

- [ ] **Step 3: Add snapshot metrics and a symbol-free live usage counter**

```python
class MetricKey:
    OPPORTUNITY_STATE = "opportunity_state"
    OPPORTUNITY_EVIDENCE_OPEN = "opportunity_evidence_open"


def opportunity_state_payload(*, run_id, rows_total, survivor_count, action_state_counts):
    counts = {state: int(action_state_counts.get(state, 0)) for state in ACTION_STATE_VALUES}
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": int(run_id),
        "rows_total": int(rows_total),
        "survivor_count": int(survivor_count),
        "action_state_counts": counts,
        "unknown_input_rate": counts["data_limited"] / rows_total if rows_total else 0.0,
    }
```

Implement `record_opportunity_state_from_db(market, run_id)` as one PostgreSQL/SQLite-compatible read of top-level JSON keys, then `_set_gauge` and `_emit_pg`. Call it after a feature run publishes in `build_daily_snapshot`; telemetry remains best-effort and cannot fail publication. Add POST body literals `surface: Literal["scan", "daily", "watchlist"]` and record only a Redis day counter dimensioned by surface. The frontend helper validates the same surfaces, sends no symbol, and swallows failure. The drawer invokes it only when a live surface prop is present; static callers leave the prop undefined.

- [ ] **Step 4: Run telemetry and drawer tests**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_per_market_telemetry.py tests/unit/test_opportunity_telemetry_api.py -q`

Run: `cd frontend && npx vitest run src/features/opportunityState/opportunityTelemetry.test.js src/components/shared/OpportunityEvidenceDrawer.test.jsx`

Expected: PASS.

- [ ] **Step 5: Commit telemetry**

```bash
git add backend/app/services/telemetry/schema.py backend/app/services/telemetry/per_market_telemetry.py backend/app/api/v1/telemetry.py backend/app/interfaces/tasks/feature_store_tasks.py backend/tests/unit/test_per_market_telemetry.py backend/tests/unit/test_opportunity_telemetry_api.py frontend/src/api/telemetry.js frontend/src/features/opportunityState/opportunityTelemetry.js frontend/src/features/opportunityState/opportunityTelemetry.test.js frontend/src/components/shared/OpportunityEvidenceDrawer.jsx
git commit -m "feat: record opportunity workflow telemetry"
```

### Task 12: Cross-Surface Fixture, Regression Suite, and Release Verification

**Files:**
- Create: `backend/tests/fixtures/opportunity_state_snapshot.py`
- Create: `backend/tests/integration/test_opportunity_state_surface_parity.py`
- Create: `frontend/src/test/fixtures/opportunityStateFixtures.js`
- Create: `frontend/src/static/opportunityStateParity.test.jsx`
- Modify: `docs/superpowers/specs/2026-08-21-correction-survivors-action-state-design.md`

**Interfaces:**
- Consumes: all completed backend and frontend contracts.
- Produces: deterministic examples for seven Action States plus one legacy row; live/static membership, ordering, labels, and provenance parity evidence.

- [ ] **Step 1: Add a failing parity fixture test before wiring the final fixture**

```python
def test_live_and_static_contracts_match_for_all_action_states(tmp_path, parity_snapshot):
    live_rows = parity_snapshot.query_live_rows()
    static_rows = parity_snapshot.export_and_read_static_rows(tmp_path)
    assert [row["symbol"] for row in live_rows if row["correction_survivor"]] == [
        row["symbol"] for row in static_rows if row["correction_survivor"]
    ]
    assert normalize(live_rows) == normalize(static_rows)
    assert next(row for row in static_rows if row["symbol"] == "LEGACY")["action_state"] is None
```

- [ ] **Step 2: Run the parity test and verify the fixture is missing**

Run: `cd backend && ./venv/bin/pytest tests/integration/test_opportunity_state_surface_parity.py -q`

Expected: FAIL because `opportunity_state_snapshot.py` is absent.

- [ ] **Step 3: Build deterministic backend and frontend fixtures and document the shipped scope**

Create rows named `EXIT`, `DETERIORATING`, `EVENT`, `EXTENDED`, `LIMITED`, `READY`, `WATCH`, and `LEGACY`. Pin Market, MIC, benchmark, dates, score pillars, warnings, and action reasons. Assert live and static Correction Survivors preset membership and `resilience_score DESC, symbol ASC` ordering. Add the equivalent frontend fixture and render it through shared Scan and Daily components.

Exercise both static capability modes: missing/false hides the preset, columns, and Daily panel; true exposes the workflow while preserving “Not computed” for the `LEGACY` row.

Update the spec status line to:

```markdown
**Status:** Implemented in Releases A1 and A2; Setup Follow-Through remains deferred
```

Do not change the approved scoring or precedence text.

- [ ] **Step 4: Run targeted backend suites**

Run: `cd backend && ./venv/bin/pytest tests/unit/domain/test_opportunity_state.py tests/unit/services/test_opportunity_state_service.py tests/unit/test_setup_engine_report_schema.py tests/unit/test_setup_engine_screener.py tests/unit/test_feature_store_query_builder.py tests/unit/test_preset_screens.py tests/unit/test_seed_correction_survivors_preset_migration.py tests/unit/test_daily_snapshot_service.py tests/unit/test_watchlist_stewardship_service.py tests/unit/test_static_site_export_service.py tests/unit/test_per_market_telemetry.py tests/integration/test_feature_store_scan_results.py tests/integration/test_scan_result_repo_enrichment.py tests/integration/test_opportunity_state_surface_parity.py -q`

Expected: PASS.

- [ ] **Step 5: Run targeted frontend suites**

Run: `cd frontend && npx vitest run src/components/shared/ActionStateBadge.test.jsx src/components/shared/OpportunityEvidenceDrawer.test.jsx src/components/shared/CorrectionSurvivorsPanel.test.jsx src/components/Scan/ResultsTable.test.jsx src/components/MarketScan/DailyMarketSnapshotTab.test.jsx src/components/MarketScan/WatchlistTable.test.jsx src/static/pages/StaticScanPage.test.jsx src/static/pages/StaticHomePage.test.jsx src/static/opportunityStateParity.test.jsx`

Expected: PASS.

- [ ] **Step 6: Run full project verification**

Run: `cd backend && ./venv/bin/pytest`

Expected: PASS with no new failures.

Run: `cd frontend && npm run test:run && npm run lint && npm run build`

Expected: all tests pass, ESLint exits zero, and Vite production build completes.

- [ ] **Step 7: Validate migration direction and static rebuild behavior**

Run: `cd backend && ./venv/bin/alembic upgrade head`

Expected: revision `20260821_0028` applies, the two indexes exist on PostgreSQL, and Correction Survivors is inserted only when no same-name preset exists.

Run: `cd backend && ./venv/bin/python -m app.scripts.export_static_site --help`

Expected: command exits zero and documents the existing export invocation. Rebuild one fixture/static market in the repository's normal export test path and assert its scan manifest is `static-scan-v2` with `features.opportunity_state: true`.

- [ ] **Step 8: Commit parity evidence and implementation status**

```bash
git add backend/tests/fixtures/opportunity_state_snapshot.py backend/tests/integration/test_opportunity_state_surface_parity.py frontend/src/test/fixtures/opportunityStateFixtures.js frontend/src/static/opportunityStateParity.test.jsx docs/superpowers/specs/2026-08-21-correction-survivors-action-state-design.md
git commit -m "test: verify opportunity state surface parity"
```

## Deployment Notes

1. Apply Alembic revision `20260821_0028` before serving the new live preset.
2. Rebuild and publish current feature snapshots so rows receive the materialized projection; unrecomputed rows intentionally show “Not computed.”
3. Re-export static markets so scan manifests move to `static-scan-v2` and include the compact evidence contract.
4. Confirm each Market's survivor count, `data_limited` rate, benchmark identity, and latest snapshot date before enabling the preset broadly.
5. Keep Setup Follow-Through disabled until validation records are extended under a separate approved design and plan.
