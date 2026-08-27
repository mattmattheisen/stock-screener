# Market-Calibrated Breadth Thresholds Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace breadth's historical-FX dependency with one revision-3 shared calculation layer using fixed, documented local-market StockBee thresholds.

**Architecture:** A new immutable market-policy registry supplies local ADTV, daily-volume, and reference-price thresholds to the existing pure breadth engine. Live, backfill, attribution, and static adapters resolve that same policy and pass raw local OHLCV without FX; catalog capability gates keep breadth-disabled markets out of breadth and exposure workflows. Existing API field names remain stable while revision-aware reads, rebuild activation, and static artifact validation enforce an atomic revision-3 cutover.

**Tech Stack:** Python 3, FastAPI, pandas, SQLAlchemy, Celery, pytest, React, Vitest, Docker/static JSON artifacts

**Spec:** `docs/superpowers/specs/2026-08-27-market-calibrated-breadth-thresholds-design.md`

## Global Constraints

- Use one shared calculation layer for live, backfill, attribution, and static breadth; no adapter-specific formulas or thresholds.
- Set `CURRENT_BREADTH_CALCULATION_REVISION = 3`; revision 2 is not a selectable methodology and must not be served after cutover.
- Do not add a schema migration, runtime calibration service, scheduled calibration task, committed calibration CLI, or daily FX dependency.
- Leave `FXService` and stored FX data intact for fundamentals, valuation, scanning, and other non-breadth consumers.
- A currency mismatch disables only StockBee eligibility; broad context indicators still calculate from adjusted local prices.
- AU, SG, and MY remain breadth-disabled and must skip breadth and breadth-derived exposure without blocking snapshots or static publication.
- Preserve existing breadth API field names and types.
- Preserve all unrelated user-owned working-tree files.

---

### Task 1: Add the canonical market-policy registry and revision-3 contract

**Files:**
- Create: `backend/app/services/breadth/market_policy.py`
- Modify: `backend/app/services/breadth/types.py`
- Modify: `backend/app/services/breadth/__init__.py`
- Test: `backend/tests/unit/test_breadth_market_policy.py`
- Test: `backend/tests/unit/domain/test_market_catalog.py`

**Interfaces:**
- Consumes: `get_market_catalog().market_codes_with_capability("breadth")` from `app.domain.markets.catalog`.
- Produces: `BreadthMarketPolicy`, `BREADTH_MARKET_POLICIES`, and `get_breadth_market_policy(market: str) -> BreadthMarketPolicy`.
- Produces: `BreadthFormulaPolicy(calculation_revision=3, atr_period=14, atr_extension_threshold=10.0)` with no liquidity or FX fields.

- [ ] **Step 1: Write the failing registry and parity tests**

```python
from app.domain.markets.catalog import get_market_catalog
from app.services.breadth.market_policy import (
    BREADTH_MARKET_POLICIES,
    get_breadth_market_policy,
)
from app.services.breadth.types import (
    CURRENT_BREADTH_CALCULATION_REVISION,
    BreadthMarketPolicy,
)


def test_breadth_market_policy_keys_match_catalog_capability():
    expected = set(get_market_catalog().market_codes_with_capability("breadth"))
    assert set(BREADTH_MARKET_POLICIES) == expected


def test_breadth_market_policies_store_selected_local_thresholds():
    assert get_breadth_market_policy("us") == BreadthMarketPolicy(
        market="US", currency="USD", min_adtv_local=250_000,
        min_daily_volume=100_000, min_month_reference_price_local=5.0,
    )
    assert get_breadth_market_policy("CA").min_adtv_local == 5_000
    assert get_breadth_market_policy("DE").min_daily_volume == 300
    assert get_breadth_market_policy("HK").min_month_reference_price_local == 0.20
    assert get_breadth_market_policy("IN").min_daily_volume == 15_000
    assert get_breadth_market_policy("JP").min_adtv_local == 8_000_000
    assert get_breadth_market_policy("KR").min_month_reference_price_local == 2_000
    assert get_breadth_market_policy("TW").min_daily_volume == 400_000
    assert get_breadth_market_policy("CN").min_adtv_local == 50_000_000


def test_unsupported_market_policy_lookup_fails_closed():
    with pytest.raises(ValueError, match="Breadth is not supported for market AU"):
        get_breadth_market_policy("au")


def test_current_breadth_revision_is_three():
    assert CURRENT_BREADTH_CALCULATION_REVISION == 3
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_breadth_market_policy.py tests/unit/domain/test_market_catalog.py -q`

Expected: FAIL because `market_policy.py` and revision 3 do not exist.

- [ ] **Step 3: Add the immutable policy and exact nine-market registry**

```python
# backend/app/services/breadth/types.py
CURRENT_BREADTH_CALCULATION_REVISION = 3


@dataclass(frozen=True, slots=True)
class BreadthMarketPolicy:
    market: str
    currency: str
    min_adtv_local: float
    min_daily_volume: int
    min_month_reference_price_local: float


@dataclass(frozen=True, slots=True)
class BreadthFormulaPolicy:
    calculation_revision: int = CURRENT_BREADTH_CALCULATION_REVISION
    atr_period: int = 14
    atr_extension_threshold: float = 10.0
```

```python
# backend/app/services/breadth/market_policy.py
BREADTH_MARKET_POLICIES = {
    "US": BreadthMarketPolicy("US", "USD", 250_000, 100_000, 5.00),
    "CA": BreadthMarketPolicy("CA", "CAD", 5_000, 5_000, 0.30),
    "DE": BreadthMarketPolicy("DE", "EUR", 5_000, 300, 8.00),
    "HK": BreadthMarketPolicy("HK", "HKD", 20_000, 150_000, 0.20),
    "IN": BreadthMarketPolicy("IN", "INR", 100_000, 15_000, 15.00),
    "JP": BreadthMarketPolicy("JP", "JPY", 8_000_000, 50_000, 500.00),
    "KR": BreadthMarketPolicy("KR", "KRW", 100_000_000, 50_000, 2_000.00),
    "TW": BreadthMarketPolicy("TW", "TWD", 3_500_000, 400_000, 20.00),
    "CN": BreadthMarketPolicy("CN", "CNY", 50_000_000, 10_000_000, 5.00),
}


def get_breadth_market_policy(market: str) -> BreadthMarketPolicy:
    market_code = str(market or "").strip().upper()
    try:
        return BREADTH_MARKET_POLICIES[market_code]
    except KeyError as exc:
        raise ValueError(f"Breadth is not supported for market {market_code or '<missing>'}") from exc
```

Export the new type and lookup from `breadth/__init__.py`. Keep registry parity as a test rather than an import-time catalog dependency, so the domain value module remains lightweight.

- [ ] **Step 4: Run the focused tests and confirm GREEN**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_breadth_market_policy.py tests/unit/domain/test_market_catalog.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the policy contract**

```bash
git add backend/app/services/breadth/types.py backend/app/services/breadth/market_policy.py backend/app/services/breadth/__init__.py backend/tests/unit/test_breadth_market_policy.py backend/tests/unit/domain/test_market_catalog.py
git commit -m "feat: add market-calibrated breadth policies"
```

### Task 2: Convert the shared formulas and engine from USD to local inputs

**Files:**
- Modify: `backend/app/services/breadth/formulas.py`
- Modify: `backend/app/services/breadth/engine.py`
- Test: `backend/tests/unit/test_breadth_formulas.py`
- Test: `backend/tests/unit/test_breadth_engine.py`

**Interfaces:**
- Consumes: `BreadthMarketPolicy` and `BreadthFormulaPolicy` from Task 1.
- Produces: `prepare_feature_frame(prices: pd.DataFrame, *, atr_period: int = 14) -> pd.DataFrame`.
- Produces: `signal_flags_at(feature_frame, calculation_date, formula_policy, market_policy, *, stockbee_currency_matches=True)`.
- Produces: `BreadthEngineRequest(..., market_policy: BreadthMarketPolicy, policy: BreadthFormulaPolicy = ...)` without `fx_by_currency`.

- [ ] **Step 1: Rewrite formula and engine tests for local values and currency mismatch**

```python
def test_prepare_feature_frame_uses_raw_local_traded_value():
    result = prepare_feature_frame(_prices(close=80.0, volume=200_000))
    assert result.iloc[-1].raw_close_local == pytest.approx(80.0)
    assert result.iloc[-1].traded_value_local == pytest.approx(16_000_000.0)
    assert "fx_to_usd" not in result
    assert "adtv20_usd" not in result


@pytest.mark.parametrize(
    ("market_policy", "adtv", "volume", "reference_price", "eligible"),
    [
        (BreadthMarketPolicy("CA", "CAD", 5_000, 5_000, 0.30), 5_000, 5_000, 0.30, True),
        (BreadthMarketPolicy("CA", "CAD", 5_000, 5_000, 0.30), 4_999.99, 5_000, 0.30, False),
        (BreadthMarketPolicy("DE", "EUR", 5_000, 300, 8.00), 5_000, 299, 8.00, False),
        (BreadthMarketPolicy("HK", "HKD", 20_000, 150_000, 0.20), 20_000, 150_000, 0.199, False),
    ],
)
def test_stockbee_local_threshold_boundaries(market_policy, adtv, volume, reference_price, eligible):
    row = _feature_row(
        adtv20_local=adtv,
        volume=volume,
        prior_volume=volume - 1,
        raw_close_local_20=reference_price,
    )
    signals = signal_flags_at(_frame(row), TARGET_DATE, BreadthFormulaPolicy(), market_policy)
    assert signals.eligibility.stockbee_month is eligible


def test_currency_mismatch_disables_only_stockbee_signals():
    result = BreadthEngine().calculate(BreadthEngineRequest(
        market="CA",
        dates=(TARGET_DATE,),
        universes_by_date={TARGET_DATE: _universe("USD")},
        prices_by_symbol={"CROSS": _long_prices()},
        market_policy=get_breadth_market_policy("CA"),
    ))[TARGET_DATE]
    assert result.eligibility.stockbee_daily_eligible_count == 0
    assert result.eligibility.advance_decline_eligible_count == 1
    assert result.eligibility.t2108_eligible_count == 1
    assert result.eligibility.high_low_52week_eligible_count == 1
    assert result.eligibility.atr_extension_eligible_count == 1
```

- [ ] **Step 2: Run formula and engine tests and confirm RED**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_breadth_formulas.py tests/unit/test_breadth_engine.py -q`

Expected: FAIL on the removed FX argument, missing local columns, and missing market policy.

- [ ] **Step 3: Implement local feature names and market-aware signal eligibility**

```python
# formulas.py
result["raw_close_local"] = raw_close
result["traded_value_local"] = result["raw_close_local"] * result["volume"]
result["adtv20_local"] = result["traded_value_local"].rolling(20, min_periods=20).mean()
result["raw_close_local_20"] = result["raw_close_local"].shift(20)

liquid = (
    stockbee_currency_matches
    and _finite(row.adtv20_local)
    and float(row.adtv20_local) >= market_policy.min_adtv_local
)
month = (
    liquid
    and _finite(row.adjusted_close, row.adjusted_close_20, row.raw_close_local_20)
    and float(row.raw_close_local_20) >= market_policy.min_month_reference_price_local
)
daily_volume_filter = (
    daily
    and float(row.volume) >= market_policy.min_daily_volume
    and float(row.volume) > float(row.prior_volume)
)
```

In `BreadthEngine.calculate`, validate `request.market_policy.market == request.market.upper()`, build every feature frame directly with `prepare_feature_frame(prices, atr_period=request.policy.atr_period)`, and pass `member.currency.upper() == request.market_policy.currency` into `signal_flags_at`. Replace the hard-coded revision-2 assertion with `CURRENT_BREADTH_CALCULATION_REVISION`.

- [ ] **Step 4: Run formula, engine, ratios, and universe tests and confirm GREEN**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_breadth_formulas.py tests/unit/test_breadth_engine.py tests/unit/test_breadth_ratios.py tests/unit/test_breadth_universe.py -q`

Expected: PASS, with exact-boundary behavior preserved.

- [ ] **Step 5: Commit the shared calculation change**

```bash
git add backend/app/services/breadth/formulas.py backend/app/services/breadth/engine.py backend/tests/unit/test_breadth_formulas.py backend/tests/unit/test_breadth_engine.py
git commit -m "refactor: calculate breadth in market-local units"
```

### Task 3: Remove breadth FX loading from live, backfill, attribution, and static adapters

**Files:**
- Modify: `backend/app/services/breadth_calculator_service.py`
- Modify: `backend/app/services/breadth_backfill.py`
- Modify: `backend/app/services/breadth_attribution_service.py`
- Modify: `backend/app/services/static_breadth_section_builder.py`
- Modify: `backend/tests/unit/test_breadth_calculator_service.py`
- Modify: `backend/tests/unit/test_breadth_backfill.py`
- Modify: `backend/tests/unit/test_breadth_attribution_service.py`
- Modify: `backend/tests/unit/test_static_breadth_section_builder.py`
- Modify: `backend/tests/unit/test_breadth_workflow_parity.py`

**Interfaces:**
- Consumes: `get_breadth_market_policy(market)` and the FX-free `BreadthEngineRequest` from Tasks 1-2.
- Produces: all four adapters passing the same `BreadthMarketPolicy`; none import, inject, load, or pass historical FX for breadth.
- Produces: attribution entry point accepting `market: str` and `currencies_by_symbol`, resolving the canonical policy internally.

- [ ] **Step 1: Add adapter regression tests proving FX is not touched and workflows agree**

```python
class ExplodingFXService:
    def get_historical_usd_rates(self, *args, **kwargs):
        raise AssertionError("breadth must not request FX")


def test_calculator_does_not_request_fx(db_session, price_provider):
    calculator = BreadthCalculatorService(db_session, price_provider=price_provider)
    calculator.calculate_daily_breadth(calculation_date=TARGET_DATE, market="CA")


def test_live_backfill_attribution_and_static_use_same_ca_policy(shared_inputs):
    expected = _calculate_with_engine(shared_inputs, market="CA")
    assert _calculate_live(shared_inputs, market="CA") == expected
    assert _calculate_backfill(shared_inputs, market="CA") == expected
    assert _calculate_attribution(shared_inputs, market="CA") == expected
    assert _calculate_static(shared_inputs, market="CA") == expected
```

Update existing constructors and fixtures so passing `fx_service=` is a test failure rather than a supported compatibility path. Update currency-mismatch attribution coverage to assert StockBee counts are zero while context counts remain populated.

- [ ] **Step 2: Run adapter tests and confirm RED**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_breadth_calculator_service.py tests/unit/test_breadth_backfill.py tests/unit/test_breadth_attribution_service.py tests/unit/test_static_breadth_section_builder.py tests/unit/test_breadth_workflow_parity.py -q`

Expected: FAIL because adapters still construct FX maps and the engine request no longer accepts them.

- [ ] **Step 3: Resolve the canonical policy once per adapter and delete breadth FX plumbing**

```python
market_policy = get_breadth_market_policy(market)
request = BreadthEngineRequest(
    market=market_policy.market,
    dates=calculation_dates,
    universes_by_date=universes_by_date,
    prices_by_symbol=prices_by_symbol,
    seed_counts=seed_counts,
    market_policy=market_policy,
    policy=formula_policy,
)
```

Delete `fx_service` constructor state, `_load_fx_for_prices`, `default_currency_for_market` fallback logic used only for breadth conversion, all `fx_by_currency` arguments, and all calls to historical FX loading in the calculator, backfill coordinator, attribution service, and static breadth input factory. Keep each universe member's actual currency so the engine can apply mismatch behavior.

- [ ] **Step 4: Run adapter and parity tests and confirm GREEN**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_breadth_calculator_service.py tests/unit/test_breadth_backfill.py tests/unit/test_breadth_attribution_service.py tests/unit/test_static_breadth_section_builder.py tests/unit/test_breadth_workflow_parity.py -q`

Expected: PASS, and `rg -n "fx_by_currency|_load_fx_for_prices|get_historical_usd_rates" backend/app/services/breadth* backend/app/services/static_breadth_section_builder.py` returns no breadth call sites.

- [ ] **Step 5: Commit the adapter cutover**

```bash
git add backend/app/services/breadth_calculator_service.py backend/app/services/breadth_backfill.py backend/app/services/breadth_attribution_service.py backend/app/services/static_breadth_section_builder.py backend/tests/unit/test_breadth_calculator_service.py backend/tests/unit/test_breadth_backfill.py backend/tests/unit/test_breadth_attribution_service.py backend/tests/unit/test_static_breadth_section_builder.py backend/tests/unit/test_breadth_workflow_parity.py
git commit -m "refactor: remove FX from breadth workflows"
```

### Task 4: Gate breadth and exposure by the market catalog

**Files:**
- Modify: `backend/app/domain/bootstrap/plan.py`
- Modify: `backend/app/tasks/daily_market_pipeline_tasks.py`
- Modify: `backend/app/scripts/export_static_site.py`
- Modify: `backend/tests/unit/domain/test_bootstrap_plan.py`
- Modify: `backend/tests/unit/test_daily_market_pipeline_tasks.py`
- Modify: `backend/tests/unit/test_export_static_site_script.py`

**Interfaces:**
- Consumes: `get_market_catalog().get(market).capabilities.breadth`.
- Produces: breadth and exposure stages only for breadth-capable markets; static skip payloads use `status="skipped"` and `reason="market_breadth_unsupported"`.
- Produces: snapshots and static market artifacts for unsupported markets without breadth or exposure.

- [ ] **Step 1: Add capability-gating tests for supported and unsupported markets**

```python
@pytest.mark.parametrize("market", ["AU", "SG", "MY"])
def test_bootstrap_omits_breadth_and_exposure_for_unsupported_markets(market):
    stage_keys = [stage.key for stage in _build_market_plan(market).stages]
    assert "breadth" not in stage_keys
    assert "exposure" not in stage_keys
    assert "snapshot" in stage_keys


@pytest.mark.parametrize("market", ["US", "CA", "DE", "HK", "IN", "JP", "KR", "TW", "CN"])
def test_daily_pipeline_keeps_breadth_and_exposure_for_supported_markets(market):
    names = [signature.task for signature in _build_daily_market_pipeline_signatures(market, TARGET_DATE)]
    assert "app.tasks.breadth_tasks.calculate_daily_breadth_with_gapfill" in names
    assert "app.tasks.breadth_tasks.calculate_market_exposure" in names


def test_static_refresh_skips_unsupported_breadth_but_builds_snapshot(monkeypatch):
    results = run_daily_refresh(markets=("SG",), as_of_date=TARGET_DATE)
    assert results["breadth_history"]["SG"] == {
        "status": "skipped", "reason": "market_breadth_unsupported"
    }
    assert results["market_exposure"]["SG"] == {
        "status": "skipped", "reason": "market_breadth_unsupported"
    }
    assert results["feature_snapshot"]["SG"]["status"] != "skipped"
```

- [ ] **Step 2: Run orchestration tests and confirm RED**

Run: `cd backend && ./venv/bin/pytest tests/unit/domain/test_bootstrap_plan.py tests/unit/test_daily_market_pipeline_tasks.py tests/unit/test_export_static_site_script.py -q`

Expected: FAIL because current orchestration schedules or requires breadth for every enabled market.

- [ ] **Step 3: Build breadth/exposure stage slices only when capability is enabled**

```python
supports_breadth = get_market_catalog().get(market).capabilities.breadth
if supports_breadth:
    stages.extend((breadth_stage, exposure_stage))
```

Apply the same condition when assembling Celery signatures: omit the breadth task, breadth guard, exposure task, and exposure guard together. In static refresh, precompute `supports_breadth_by_market`; for false entries store the two explicit skip payloads, do not call `_ensure_breadth_history` or `_compute_static_market_exposure`, and allow feature snapshot generation to continue because the skip payload contains no `error`.

- [ ] **Step 4: Run orchestration tests and confirm GREEN**

Run: `cd backend && ./venv/bin/pytest tests/unit/domain/test_bootstrap_plan.py tests/unit/test_daily_market_pipeline_tasks.py tests/unit/test_export_static_site_script.py -q`

Expected: PASS for both supported and unsupported market matrices.

- [ ] **Step 5: Commit capability-aware orchestration**

```bash
git add backend/app/domain/bootstrap/plan.py backend/app/tasks/daily_market_pipeline_tasks.py backend/app/scripts/export_static_site.py backend/tests/unit/domain/test_bootstrap_plan.py backend/tests/unit/test_daily_market_pipeline_tasks.py backend/tests/unit/test_export_static_site_script.py
git commit -m "fix: gate breadth workflows by market capability"
```

### Task 5: Enforce revision 3 in database rebuilds, reads, and static fallback selection

**Files:**
- Modify: `backend/app/services/breadth/rebuild.py`
- Modify: `backend/app/services/static_artifact_combiner.py`
- Modify: `backend/app/schemas/breadth.py`
- Modify: `backend/tests/unit/test_breadth_rebuild.py`
- Modify: `backend/tests/integration/test_breadth_revision_cutover.py`
- Modify: `backend/tests/unit/services/test_static_artifact_combiner.py`
- Modify: `backend/tests/unit/test_breadth_endpoints.py`
- Modify: `backend/tests/unit/test_ui_snapshot_service.py`

**Interfaces:**
- Consumes: `CURRENT_BREADTH_CALCULATION_REVISION == 3`.
- Produces: rebuild manifests with `liquidity="raw_close_local_x_volume_adtv20"`, fixed market-policy metadata, and no FX contract.
- Produces: static fallback compatibility requiring `breadth.json.payload.current.calculation_revision == 3` and `source_revision` ending in `|breadth-r3` whenever `entry.features.breadth` is true.

- [ ] **Step 1: Add cutover and fallback rejection tests**

```python
def test_activation_replaces_revision_two_rows_with_revision_three_rows(db_session, staged_rebuild):
    staged_rebuild.activate()
    revisions = {row.calculation_revision for row in db_session.query(MarketBreadth).all()}
    assert revisions == {3}


def test_fallback_breadth_revision_two_is_not_selected(tmp_path):
    _write_market_artifact(tmp_path / "fallback", market="CA", breadth_revision=2)
    with pytest.raises(NoPublishedStaticMarketArtifact):
        _combine(current=None, fallback=tmp_path / "fallback", required=("CA",))


def test_current_breadth_revision_three_and_marker_are_required(tmp_path):
    artifact = _write_market_artifact(tmp_path / "current", market="CA", breadth_revision=3)
    payload = json.loads((artifact / "breadth.json").read_text())
    payload["source_revision"] = "2026-08-27|breadth-r2"
    (artifact / "breadth.json").write_text(json.dumps(payload))
    with pytest.raises(StaticArtifactFormulaError, match="breadth revision"):
        _combine(current=tmp_path / "current", fallback=None, required=("CA",))
```

Also update endpoint and UI snapshot fixtures so revision-2 rows are absent/unavailable and revision-3 rows produce `breadth-r3`.

- [ ] **Step 2: Run migration and static validation tests and confirm RED**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_breadth_rebuild.py tests/integration/test_breadth_revision_cutover.py tests/unit/services/test_static_artifact_combiner.py tests/unit/test_breadth_endpoints.py tests/unit/test_ui_snapshot_service.py -q`

Expected: FAIL on stale hard-coded revision 2, old formula-contract text, and fallback selection accepting old breadth artifacts.

- [ ] **Step 3: Make the rebuild contract and static validator revision-aware**

```python
# rebuild.py manifest fragment
"calculation_revision": CURRENT_BREADTH_CALCULATION_REVISION,
"formula_contract": {
    "liquidity": "raw_close_local_x_volume_adtv20",
    "market_policy": "fixed_market_calibrated_thresholds",
    "currency_mismatch": "stockbee_ineligible_context_preserved",
},
```

Add a combiner helper that reads `breadth.json` only when the market entry advertises breadth, then validates both fields:

```python
current = payload.get("payload", {}).get("current")
observed_revision = current.get("calculation_revision") if isinstance(current, dict) else None
source_revision = str(payload.get("source_revision") or "")
if observed_revision != CURRENT_BREADTH_CALCULATION_REVISION or not source_revision.endswith(
    f"|breadth-r{CURRENT_BREADTH_CALCULATION_REVISION}"
):
    raise StaticArtifactFormulaError(
        f"{market} {source_label} artifact uses incompatible breadth revision: "
        f"revision={observed_revision!r}, source_revision={source_revision!r}; "
        f"expected {CURRENT_BREADTH_CALCULATION_REVISION}"
    )
```

Use this validator both when filtering fallback candidates and when validating selected current artifacts. Change the schema description to `current value is 3`; replace hard-coded activation return values with the shared constant.

- [ ] **Step 4: Run migration and static validation tests and confirm GREEN**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_breadth_rebuild.py tests/integration/test_breadth_revision_cutover.py tests/unit/services/test_static_artifact_combiner.py tests/unit/test_breadth_endpoints.py tests/unit/test_ui_snapshot_service.py -q`

Expected: PASS; revision-2 fallback fixtures are filtered before publication and current incompatible artifacts fail explicitly.

- [ ] **Step 5: Commit the revision-3 safeguards**

```bash
git add backend/app/services/breadth/rebuild.py backend/app/services/static_artifact_combiner.py backend/app/schemas/breadth.py backend/tests/unit/test_breadth_rebuild.py backend/tests/integration/test_breadth_revision_cutover.py backend/tests/unit/services/test_static_artifact_combiner.py backend/tests/unit/test_breadth_endpoints.py backend/tests/unit/test_ui_snapshot_service.py
git commit -m "feat: enforce breadth revision three cutover"
```

### Task 6: Update user-facing formula copy and operational documentation

**Files:**
- Modify: `frontend/src/components/Breadth/breadthMetricDefinitions.js`
- Modify: `frontend/src/components/Breadth/BreadthMetricTooltip.jsx`
- Modify: `frontend/src/components/Breadth/BreadthHistoryTable.test.jsx`
- Modify: `frontend/src/pages/BreadthPage.test.jsx`
- Modify: `docs/LIVE_APP_GUIDE.md`
- Modify: `docs/STATIC_SITE.md`
- Create: `docs/runbooks/market-breadth-revision-3-cutover.md`
- Create: `docs/release-notes/market-calibrated-breadth-r3.md`

**Interfaces:**
- Consumes: the fixed policy table and migration behavior from the approved spec.
- Produces: UI copy that says “selected market's local threshold” without embedding US values for every market.
- Produces: an operator runbook that rebuilds all nine markets, validates revision 3, activates atomically, rebuilds dependents, and clears caches.

- [ ] **Step 1: Add frontend copy tests that reject universal USD wording**

```javascript
it('describes StockBee eligibility in selected-market local units', () => {
  render(<BreadthMetricTooltip metric="stocks_up_4pct" />);
  expect(screen.getByText(/local-currency traded value/i)).toBeInTheDocument();
  expect(screen.getByText(/market-specific daily share threshold/i)).toBeInTheDocument();
  expect(screen.queryByText(/US\$250,000/i)).not.toBeInTheDocument();
});

it('describes the monthly reference price as market-specific', () => {
  render(<BreadthMetricTooltip metric="stocks_up_25pct_month" />);
  expect(screen.getByText(/market-specific local reference-price threshold/i)).toBeInTheDocument();
  expect(screen.queryByText(/US\$5/i)).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run the frontend test and confirm RED**

Run: `cd frontend && npm run test:run -- src/components/Breadth/BreadthHistoryTable.test.jsx src/pages/BreadthPage.test.jsx`

Expected: FAIL because the definitions still advertise US$250,000, 100,000 shares, and US$5 globally.

- [ ] **Step 3: Replace universal USD copy and write the revision-3 runbook**

```javascript
const STOCKBEE_LIQUIDITY =
  "20-session average raw traded value must meet the selected market's fixed local-currency threshold.";

const STOCKBEE_DAILY_VOLUME =
  "Target-session volume must meet the selected market's fixed daily share threshold and exceed the prior session.";

const STOCKBEE_MONTH_REFERENCE =
  "The raw close exactly 20 sessions earlier must meet the selected market's fixed local reference-price threshold.";
```

Use these phrases in the relevant metric descriptions and required-history text. In `LIVE_APP_GUIDE.md`, add the exact nine-row policy table and explain that the values are rounded initial settings maintained in code. In `STATIC_SITE.md`, state that breadth-capable artifacts require revision 3 and old fallbacks are unavailable rather than silently reused. Add a reusable release-note fragment stating that breadth now uses fixed local-market thresholds, upgrades require a revision-3 rebuild, and breadth can be temporarily unavailable until activation completes. In the new runbook, record this exact sequence:

1. Deploy revision-3 code with breadth-dependent writers paused.
2. Back up PostgreSQL and current static artifacts.
3. Rebuild US, CA, DE, HK, IN, JP, KR, TW, and CN into the existing shadow tables.
4. Validate revision, counts, denominators, ratios, signatures, and manifest policy contract.
5. Atomically activate the shadow dataset, replacing every revision-2 `market_breadth` row.
6. Rebuild exposure, attribution, UI snapshots, and static market artifacts.
7. Clear breadth/exposure caches, resume writers, and verify API/static `breadth-r3` markers.

- [ ] **Step 4: Run frontend tests, lint touched code, and inspect documentation terms**

Run: `cd frontend && npm run test:run -- src/components/Breadth/BreadthHistoryTable.test.jsx src/pages/BreadthPage.test.jsx && npm run lint`

Run: `rg -n "US\$250,000|US\$5|USD-normalized|historical FX" frontend/src/components/Breadth docs/LIVE_APP_GUIDE.md docs/STATIC_SITE.md docs/runbooks/market-breadth-revision-3-cutover.md`

Expected: tests and lint PASS; search returns only explicitly historical/migration explanations, not current-formula copy.

- [ ] **Step 5: Commit UI copy and operational docs**

```bash
git add frontend/src/components/Breadth/breadthMetricDefinitions.js frontend/src/components/Breadth/BreadthMetricTooltip.jsx frontend/src/components/Breadth/BreadthHistoryTable.test.jsx frontend/src/pages/BreadthPage.test.jsx docs/LIVE_APP_GUIDE.md docs/STATIC_SITE.md docs/runbooks/market-breadth-revision-3-cutover.md docs/release-notes/market-calibrated-breadth-r3.md
git commit -m "docs: explain local breadth thresholds and cutover"
```

### Task 7: Update remaining revision fixtures and run focused architecture checks

**Files:**
- Modify: `backend/tests/helpers/mcp_fixture.py`
- Modify: `backend/tests/unit/test_daily_breadth_runner.py`
- Modify: `backend/tests/unit/test_stock_workspace_endpoints.py`
- Modify: `backend/tests/unit/test_digest_service.py`
- Modify: `backend/tests/unit/test_watchlist_stewardship_service.py`
- Modify: `backend/tests/unit/test_breadth_persistence.py`

**Interfaces:**
- Consumes: revision 3 as the only current breadth contract.
- Produces: no test fixture representing current breadth as revision 2; deliberate stale-row tests retain revision 2 with names explaining rejection.

- [ ] **Step 1: Run a targeted stale-revision inventory and classify each hit**

Run: `rg -n "calculation_revision\s*[=:]\s*2|breadth-r2" backend/tests frontend/src --glob '*test*' --glob '*fixture*'`

Expected: current-data fixtures and deliberate stale-data tests are listed separately during editing; only deliberate stale-data tests remain revision 2 at the end.

- [ ] **Step 2: Update current-data fixtures to revision 3**

```python
current_breadth = MarketBreadth(
    market="US",
    date=date(2026, 8, 27),
    calculation_revision=3,
)
```

Keep revision 2 only in tests named like `test_revision_two_rows_are_not_served` or `test_revision_two_static_fallback_is_rejected`.

- [ ] **Step 3: Run the complete breadth-focused backend suite**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_breadth_*.py tests/unit/test_daily_breadth_runner.py tests/unit/test_stock_workspace_endpoints.py tests/unit/test_digest_service.py tests/unit/services/test_static_artifact_combiner.py tests/integration/test_breadth_revision_cutover.py -q`

Expected: PASS.

- [ ] **Step 4: Run static workflow and architecture searches**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_static_site_workflow.py tests/unit/test_export_static_site_no_current_artifacts.py -q`

Run: `rg -n "fx_by_currency|min_adtv_usd|min_month_reference_price_usd|raw_close_usd_20|adtv20_usd|fx_max_age_days" backend/app/services/breadth backend/app/services/breadth_calculator_service.py backend/app/services/breadth_backfill.py backend/app/services/breadth_attribution_service.py backend/app/services/static_breadth_section_builder.py`

Expected: tests PASS and architecture search returns no hits.

- [ ] **Step 5: Commit fixture and regression cleanup**

```bash
git add backend/tests/helpers/mcp_fixture.py backend/tests/unit/test_daily_breadth_runner.py backend/tests/unit/test_stock_workspace_endpoints.py backend/tests/unit/test_digest_service.py backend/tests/unit/test_watchlist_stewardship_service.py backend/tests/unit/test_breadth_persistence.py
git commit -m "test: align breadth fixtures with revision three"
```

### Task 8: Perform end-to-end verification and prepare branch handoff

**Files:**
- Verify only; modify files only when a failing check exposes an in-scope defect.

**Interfaces:**
- Consumes: all earlier task outputs.
- Produces: a clean, reviewable branch with evidence that backend, frontend, static, and migration behavior meet the spec.

- [ ] **Step 1: Run the complete backend test suite**

Run: `cd backend && ./venv/bin/pytest -q`

Expected: PASS.

- [ ] **Step 2: Run frontend tests, lint, and production build**

Run: `cd frontend && npm run test:run && npm run lint && npm run build`

Expected: all commands PASS and Vite produces the production bundle.

- [ ] **Step 3: Run repository-wide revision and FX ownership checks**

Run: `rg -n "calculation_revision\s*[=:]\s*2|breadth-r2" backend/app frontend/src`

Expected: no current application contract uses revision 2.

Run: `rg -n "fx_by_currency|min_adtv_usd|min_month_reference_price_usd|raw_close_usd_20|adtv20_usd|fx_max_age_days" backend/app/services/breadth*`

Expected: no breadth runtime code depends on FX or USD thresholds.

- [ ] **Step 4: Review the final diff and working tree**

Run: `git diff --check && git status --short --branch && git log --oneline origin/main..HEAD`

Expected: no whitespace errors; only intended tracked changes and the user's pre-existing untracked files remain; commits are scoped by task.

- [ ] **Step 5: Record the deployment handoff**

Report the exact test results, the nine market policies, revision-3 rebuild requirement, temporary-unavailability behavior before activation, and the fact that AU/SG/MY now skip breadth/exposure while continuing snapshot/static publication. Do not activate a production rebuild or publish static artifacts without a separate deployment request.
