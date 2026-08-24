# Correction Survivors Maintainability Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve all seven correction-survivors maintainability findings without changing its public policy, API/static contract, or supported UI behavior.

**Architecture:** Split opportunity state into typed domain policy, projection, and stewardship boundaries; move capability metadata into explicit scan/run metadata; and share one aggregate summary boundary between Daily Snapshot and telemetry. Extract scan assembly, static bundle export, frontend capability policy, and opportunity table presentation from their current oversized owners.

**Tech Stack:** Python 3.12, dataclasses, Pydantic v2, SQLAlchemy, Alembic, FastAPI, pytest, React 18, TanStack Query, Vitest, React Testing Library, ESLint, Vite.

**Spec:** `docs/superpowers/specs/2026-08-23-correction-survivors-maintainability-remediation-design.md`

## Global Constraints

- Preserve survivor eligibility, score weights, action precedence, response fields, static manifest behavior, and live/static parity.
- Keep unknown evidence tri-state; never coerce unknown to a failed gate or numeric zero.
- Treat only a completely absent projection as legacy; reject malformed present projections.
- Do not implement deferred Setup Follow-Through or a general capability framework.
- Store no new internal materialization metadata in user scan criteria.
- Resolve capability from explicit scan/run metadata, never result rows or ORM reflection.
- Keep the orchestrator, static export service, and two identified oversized tests below 1,000 lines.
- Add no dependency; use red-green-refactor and one independently reviewable commit per task.

## Planned File Boundaries

- `backend/app/domain/scanning/opportunity_state/`: model, policy, projection, stewardship, and stable public imports.
- `backend/app/scanners/scan_result_assembler.py`: result assembly and opportunity enrichment.
- `backend/app/services/static_scan_bundle_exporter.py`: static scan bundle/filter/serialization behavior.
- `backend/app/domain/scanning/opportunity_summary.py`: typed summary value and reader protocol.
- `backend/app/infra/db/repositories/opportunity_summary_repo.py`: scan-result and feature-row aggregate queries.
- `frontend/src/features/scan/opportunityCapabilityPolicy.js`: pure query/preset capability policy.
- `frontend/src/components/Scan/OpportunityResultCells.jsx`: opportunity table presentation.
- `frontend/src/components/Scan/useOpportunityEvidenceSelection.js`: drawer selection lifecycle.

---

### Task 1: Canonical Opportunity Domain Package

**Files:**
- Create: `backend/app/domain/scanning/opportunity_state/__init__.py`
- Create: `backend/app/domain/scanning/opportunity_state/model.py`
- Create: `backend/app/domain/scanning/opportunity_state/policy.py`
- Create: `backend/app/domain/scanning/opportunity_state/projection.py`
- Create: `backend/app/domain/scanning/opportunity_state/stewardship.py`
- Delete: `backend/app/domain/scanning/opportunity_state.py`
- Modify: `backend/app/schemas/opportunity_state.py`
- Test: `backend/tests/unit/domain/test_opportunity_state.py`
- Test: `backend/tests/unit/test_opportunity_state_schema.py`

**Interfaces:**
- Consumes: existing version-1 opportunity projection.
- Produces: grouped `OpportunityEvidence`, immutable `OpportunityAssessment`, canonical `ActionState`, `evaluate_opportunity_state`, strict parse/serialize functions, and stewardship overlay.

- [ ] **Step 1: Write failing grouped-evidence and projection tests**

```python
def test_unavailable_structure_is_data_limited():
    evidence = complete_evidence(structure=StructureEvidence(available=False))
    assert evaluate_opportunity_state(evidence).action_state is ActionState.DATA_LIMITED

def test_projection_round_trip_uses_canonical_pillars():
    result = evaluate_opportunity_state(complete_evidence())
    payload = serialize_opportunity_projection(result)
    assert parse_opportunity_projection(payload) == result
    assert tuple(payload["opportunity_state"]["score_pillars"]) == SCORE_PILLAR_KEYS
```

- [ ] **Step 2: Run RED**

Run: `cd backend && ./venv/bin/pytest tests/unit/domain/test_opportunity_state.py tests/unit/test_opportunity_state_schema.py -q -x`

Expected: missing grouped evidence/package interfaces.

- [ ] **Step 3: Implement focused model, policy, projection, and stewardship modules**

```python
@dataclass(frozen=True)
class OpportunityEvidence:
    provenance: ProvenanceEvidence
    leadership: LeadershipEvidence
    trend: TrendEvidence
    structure: StructureEvidence
    tradability: TradabilityEvidence
    risk: RiskEvidence
```

Remove `stewardship_status`, `prior_run_required`, and `deterioration_confirmed` from current-snapshot inputs. Export compatible public names from `__init__.py` while callers migrate.

- [ ] **Step 4: Centralize projection contract and schema coherence**

```python
OPPORTUNITY_PROJECTION_KEYS = ("correction_survivor", "resilience_score", "action_state", "opportunity_state")
OPPORTUNITY_EVIDENCE_KEYS = frozenset(("schema_version", "policy_version", "as_of_date", "market", "mic", "benchmark_symbol", "benchmark_as_of_date", "score_pillars", "passed_checks", "failed_checks", "warnings", "metrics", "data_availability", "action_reasons"))
SCORE_PILLAR_KEYS = ("benchmark_leadership", "multi_horizon_rs", "trend_integrity", "structure_tightness", "liquidity_freshness")
```

Pydantic validators import the enum/constants and invoke canonical coherence validation rather than maintaining independent lists.

- [ ] **Step 5: Run GREEN and commit**

Run: `cd backend && ./venv/bin/pytest tests/unit/domain/test_opportunity_state.py tests/unit/test_opportunity_state_schema.py -q`

```bash
git add backend/app/domain/scanning/opportunity_state backend/app/domain/scanning/opportunity_state.py backend/app/schemas/opportunity_state.py backend/tests/unit/domain/test_opportunity_state.py backend/tests/unit/test_opportunity_state_schema.py
git commit -m "refactor: split opportunity state domain"
```

### Task 2: Typed Projection Assembly

**Files:**
- Modify: `backend/app/services/opportunity_state_service.py`
- Modify: `backend/app/scanners/scan_orchestrator.py`
- Modify: `backend/app/use_cases/feature_store/build_daily_snapshot.py`
- Test: `backend/tests/unit/services/test_opportunity_state_service.py`
- Test: `backend/tests/unit/use_cases/feature_store/test_build_daily_snapshot.py`

**Interfaces:**
- Consumes: Task 1 evidence and codec.
- Produces: the existing keyword-only `build_opportunity_projection` public interface, implemented by one normalization/evaluation/serialization pass.

- [ ] **Step 1: Write a failing single-serialization test**

```python
def test_projection_is_complete_before_single_serialization(monkeypatch):
    serialize = Mock(wraps=serialize_opportunity_projection)
    monkeypatch.setattr(service, "serialize_opportunity_projection", serialize)
    projection = build_opportunity_projection(**complete_service_inputs())
    serialize.assert_called_once()
    assert projection["metrics"]["current_price"] == 100.0
    assert projection["action_reasons"]
```

- [ ] **Step 2: Run RED**

Run: `cd backend && ./venv/bin/pytest tests/unit/services/test_opportunity_state_service.py -q -x`

Expected: current double construction/post-serialization mutation violates the assertion.

- [ ] **Step 3: Build typed evidence and serialize the final assessment once**

```python
evidence = OpportunityEvidence(
    provenance=build_provenance_evidence(inputs),
    leadership=build_leadership_evidence(inputs),
    trend=build_trend_evidence(inputs),
    structure=build_structure_evidence(inputs),
    tradability=build_tradability_evidence(inputs),
    risk=build_risk_evidence(inputs),
)
assessment = evaluate_opportunity_state(evidence).with_metrics(metrics)
return serialize_opportunity_projection(assessment)
```

Delete `_projection_metrics` and nested mapping mutation.

- [ ] **Step 4: Run GREEN and commit**

Run: `cd backend && ./venv/bin/pytest tests/unit/services/test_opportunity_state_service.py tests/unit/use_cases/feature_store/test_build_daily_snapshot.py tests/unit/test_scan_orchestrator.py -q`

```bash
git add backend/app/services/opportunity_state_service.py backend/app/scanners/scan_orchestrator.py backend/app/use_cases/feature_store/build_daily_snapshot.py backend/tests/unit/services/test_opportunity_state_service.py backend/tests/unit/use_cases/feature_store/test_build_daily_snapshot.py
git commit -m "refactor: assemble opportunity evidence once"
```

### Task 3: Explicit Scan Materialization Metadata

**Files:**
- Modify: `backend/app/models/scan_result.py`
- Create: `backend/alembic/versions/20260823_0029_add_scan_metadata.py`
- Modify: `backend/app/domain/scanning/materialization.py`
- Modify: `backend/app/use_cases/scanning/create_scan.py`
- Modify: `backend/app/use_cases/scanning/get_scan_results.py`
- Modify: `backend/app/services/daily_snapshot_service.py`
- Test: `backend/tests/unit/test_scan_materialization_metadata_migration.py`
- Test: `backend/tests/unit/use_cases/test_create_scan.py`
- Test: `backend/tests/unit/use_cases/test_create_scan_compile_path.py`
- Test: `backend/tests/unit/use_cases/test_get_scan_results.py`

**Interfaces:**
- Produces: nullable `Scan.metadata_json` and `resolve_opportunity_state_capability(*, feature_run_id, feature_run_config, scan_metadata) -> bool`.

- [ ] **Step 1: Write failing ownership, precedence, and migration tests**

```python
def test_direct_scan_keeps_internal_marker_out_of_criteria():
    scan = run_direct_scan(criteria={"min_price": 10})
    assert scan.criteria == {"min_price": 10}
    assert scan.metadata_json == {"materialization_versions": {"opportunity_state": 1}}

def test_feature_run_is_authoritative():
    assert not resolve_opportunity_state_capability(feature_run_id=7, feature_run_config={}, scan_metadata=CAPABLE)
```

Migration assertions cover upgrade move, unrelated-key preservation, downgrade restoration, and re-upgrade idempotence.

- [ ] **Step 2: Run RED**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_scan_materialization_metadata_migration.py tests/unit/use_cases/test_create_scan.py tests/unit/use_cases/test_create_scan_compile_path.py tests/unit/use_cases/test_get_scan_results.py -q -x`

- [ ] **Step 3: Add column/migration and replace ORM reflection**

```python
metadata_json = Column(JSON, nullable=True)

def resolve_opportunity_state_capability(*, feature_run_id, feature_run_config, scan_metadata):
    source = feature_run_config if feature_run_id is not None else scan_metadata
    return config_has_opportunity_state_materialization(source)
```

Migration `0029` moves only the recognized nested marker and merges without overwriting unrelated criteria/metadata values.

- [ ] **Step 4: Update direct-scan writers and explicit readers**

Create/compile paths write metadata separately. Get-results and Daily pass explicit fields. Delete `scan_has_opportunity_state_materialization(scan: object)`.

- [ ] **Step 5: Run GREEN and commit**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_scan_materialization_metadata_migration.py tests/unit/use_cases/test_create_scan.py tests/unit/use_cases/test_create_scan_compile_path.py tests/unit/use_cases/test_get_scan_results.py tests/unit/test_scan_results_endpoints.py tests/unit/test_daily_snapshot_service.py -q`

```bash
git add backend/app/models/scan_result.py backend/alembic/versions/20260823_0029_add_scan_metadata.py backend/app/domain/scanning/materialization.py backend/app/use_cases/scanning/create_scan.py backend/app/use_cases/scanning/get_scan_results.py backend/app/services/daily_snapshot_service.py backend/tests/unit/test_scan_materialization_metadata_migration.py backend/tests/unit/use_cases/test_create_scan.py backend/tests/unit/use_cases/test_create_scan_compile_path.py backend/tests/unit/use_cases/test_get_scan_results.py
git commit -m "refactor: store scan materialization metadata explicitly"
```

### Task 4: Shared Opportunity Summary Aggregation

**Files:**
- Create: `backend/app/domain/scanning/opportunity_summary.py`
- Create: `backend/app/infra/db/repositories/opportunity_summary_repo.py`
- Modify: `backend/app/services/daily_snapshot_service.py`
- Modify: `backend/app/services/telemetry/per_market_telemetry.py`
- Modify: `backend/app/services/telemetry/schema.py`
- Modify: `backend/app/infra/db/uow.py`
- Modify: `backend/app/domain/common/uow.py`
- Create: `backend/tests/unit/test_daily_snapshot_opportunity_summary.py`
- Modify: `backend/tests/unit/test_daily_snapshot_service.py`
- Test: `backend/tests/unit/test_per_market_telemetry.py`

**Interfaces:**
- Produces: immutable `OpportunityStateSummary` and reader methods `for_scan(scan_id)` and `for_feature_run(run_id)`.

- [ ] **Step 1: Split Daily opportunity tests without changing assertions**

Move only correction-survivor fixtures/cases to `test_daily_snapshot_opportunity_summary.py`; run both files and preserve their combined test count.

- [ ] **Step 2: Write failing one-reader-call tests**

```python
def test_daily_uses_one_summary_read(summary_reader):
    payload = build_daily_snapshot_payload(
        db=db,
        market="US",
        uow=uow,
        scan_results_use_case=scan_results_use_case,
        opportunity_summary_reader=summary_reader,
    )
    summary_reader.for_scan.assert_called_once_with("scan-1")
    assert payload["correction_survivors"]["counts_by_action_state"]["setup_ready"] == 2
```

Telemetry test asserts `for_feature_run(42)` is called once and telemetry creates no database session itself.

- [ ] **Step 3: Run RED**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_daily_snapshot_opportunity_summary.py tests/unit/test_per_market_telemetry.py tests/unit/test_opportunity_telemetry_api.py -q -x`

- [ ] **Step 4: Implement typed reader and one aggregate per source**

```python
@dataclass(frozen=True)
class OpportunityStateSummary:
    rows_total: int
    survivor_count: int
    counts_by_action_state: Mapping[ActionState, int]
```

Daily keeps one ordered top-row query plus one summary aggregate. Telemetry consumes `for_feature_run` and no longer owns feature SQL, dynamic model imports, or session cleanup.

- [ ] **Step 5: Run GREEN and commit**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_daily_snapshot_service.py tests/unit/test_daily_snapshot_opportunity_summary.py tests/unit/test_per_market_telemetry.py tests/unit/test_opportunity_telemetry_api.py tests/unit/test_field_coverage_telemetry.py -q`

```bash
git add backend/app/domain/scanning/opportunity_summary.py backend/app/infra/db/repositories/opportunity_summary_repo.py backend/app/services/daily_snapshot_service.py backend/app/services/telemetry/per_market_telemetry.py backend/app/services/telemetry/schema.py backend/app/infra/db/uow.py backend/app/domain/common/uow.py backend/tests/unit/test_daily_snapshot_service.py backend/tests/unit/test_daily_snapshot_opportunity_summary.py backend/tests/unit/test_per_market_telemetry.py
git commit -m "refactor: share opportunity summary aggregation"
```

### Task 5: Extract Scan Result Assembly

**Files:**
- Create: `backend/app/scanners/scan_result_assembler.py`
- Modify: `backend/app/scanners/scan_orchestrator.py`
- Create: `backend/tests/unit/test_scan_result_assembler.py`
- Modify: `backend/tests/unit/test_scan_orchestrator.py`

**Interfaces:**
- Produces: `ScanResultAssembler.assemble(request: ScanResultAssemblyRequest) -> dict[str, object]`; orchestrator delegates result construction.

- [ ] **Step 1: Write a failing assembler characterization test**

```python
def test_assembler_preserves_result_contract(orchestrator_inputs):
    result = ScanResultAssembler().assemble(**orchestrator_inputs)
    assert result["symbol"] == "NVDA"
    assert result["opportunity_state"]["schema_version"] == 1
    assert result["composite_score"] == pytest.approx(88.0)
```

- [ ] **Step 2: Run RED**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_scan_result_assembler.py -q -x`

- [ ] **Step 3: Move `_combine_results` assembly into the collaborator**

Move result scoring, audit fields, Setup Engine attachment, and opportunity composition unchanged. Inject the opportunity projector for isolated tests.

- [ ] **Step 4: Delegate from the orchestrator**

```python
return self._result_assembler.assemble(symbol=symbol, stock_data=stock_data, screener_outputs=results, context=context)
```

- [ ] **Step 5: Run GREEN, complexity check, and commit**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_scan_result_assembler.py tests/unit/test_scan_orchestrator.py tests/unit/test_scan_orchestrator_quality_policy.py -q`

Run: `wc -l backend/app/scanners/scan_orchestrator.py && cd backend && ./venv/bin/ruff check app/scanners/scan_orchestrator.py app/scanners/scan_result_assembler.py --select C901,E9,F`

```bash
git add backend/app/scanners/scan_result_assembler.py backend/app/scanners/scan_orchestrator.py backend/tests/unit/test_scan_result_assembler.py backend/tests/unit/test_scan_orchestrator.py
git commit -m "refactor: extract scan result assembler"
```

### Task 6: Extract Static Scan Bundle Export

**Files:**
- Create: `backend/app/services/static_scan_bundle_exporter.py`
- Modify: `backend/app/services/static_site_export_service.py`
- Create: `backend/tests/unit/test_static_scan_bundle_exporter.py`
- Modify: `backend/tests/unit/test_static_site_export_service.py`

**Interfaces:**
- Produces: `StaticScanBundleExporter.export_scan_bundle(request: StaticScanBundleRequest) -> StaticScanBundleResult` and manifest fragment.

- [ ] **Step 1: Write a failing bundle characterization test**

```python
def test_bundle_preserves_compact_projection(tmp_path, capable_run):
    exporter = StaticScanBundleExporter(feature_store=feature_store_repo)
    result = exporter.export_scan_bundle(
        StaticScanBundleRequest(run=capable_run, destination=tmp_path)
    )
    row = read_first_row(result)
    assert row["action_state"] == "setup_ready"
    assert "setup_engine" not in row
    assert row["opportunity_state"]["score_pillars"]["trend_integrity"] == 20.0
```

- [ ] **Step 2: Run RED**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_static_scan_bundle_exporter.py -q -x`

- [ ] **Step 3: Move scan bundle/filter/serialization methods and delegate**

Preserve bundle names, JSON shape, null ordering, capability marker, filter manifest, and strict projection validation. The site service owns only export coordination and destination lifecycle.

- [ ] **Step 4: Run GREEN, threshold checks, and commit**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_static_scan_bundle_exporter.py tests/unit/test_static_site_export_service.py tests/integration/test_opportunity_state_surface_parity.py -q`

Run: `wc -l backend/app/services/static_site_export_service.py backend/tests/unit/test_daily_snapshot_service.py`

```bash
git add backend/app/services/static_scan_bundle_exporter.py backend/app/services/static_site_export_service.py backend/tests/unit/test_static_scan_bundle_exporter.py backend/tests/unit/test_static_site_export_service.py backend/tests/unit/test_daily_snapshot_service.py backend/tests/unit/test_daily_snapshot_opportunity_summary.py
git commit -m "refactor: extract static scan bundle exporter"
```

### Task 7: Pure Frontend Capability Policy

**Files:**
- Create: `frontend/src/features/scan/opportunityCapabilityPolicy.js`
- Create: `frontend/src/features/scan/opportunityCapabilityPolicy.test.js`
- Modify: `frontend/src/features/scan/hooks/useScanFilterPresets.js`
- Modify: `frontend/src/features/scan/hooks/useScanFilterPresets.test.jsx`
- Modify: `frontend/src/features/scan/pages/ScanPageContainer.jsx`
- Modify: `frontend/src/features/scan/pages/ScanPageContainer.test.jsx`
- Modify: `frontend/src/static/pages/StaticScanPage.jsx`
- Create: `frontend/src/static/pages/StaticScanPage.opportunity.test.jsx`
- Modify: `frontend/src/static/pages/StaticScanPage.test.jsx`

**Interfaces:**
- Produces: `queryRequiresOpportunityState`, `sanitizeQueryForOpportunityCapability`, and `presetRequiresOpportunityState`, all based on normalized query semantics.

- [ ] **Step 1: Split static opportunity tests and preserve combined count**

Move capability, preset, opportunity filter/sort, and drawer cases into `StaticScanPage.opportunity.test.jsx`; run both static files before changing behavior.

- [ ] **Step 2: Write failing name-heuristic and transition tests**

```javascript
it('does not hide a user preset based on display name', () => {
  expect(presetRequiresOpportunityState({ name: 'Correction Survivors', filters: expressionFilters(emptyExpression()) })).toBe(false);
});

it('sanitizes unsupported filter and sort atomically', () => {
  expect(sanitizeQueryForOpportunityCapability(opportunityQuery(), false)).toEqual(safeQuery());
});
```

ScanPage test asserts exactly one sanitized replacement request after capability loss and no unsupported request to the legacy scan.

- [ ] **Step 3: Run RED**

Run: `cd frontend && npx vitest run src/features/scan/opportunityCapabilityPolicy.test.js src/features/scan/hooks/useScanFilterPresets.test.jsx src/features/scan/pages/ScanPageContainer.test.jsx --maxWorkers=4`

- [ ] **Step 4: Implement pure policy and make preset hook CRUD-only**

```javascript
export function queryRequiresOpportunityState(query) {
  const expression = canonicalizeExpression(query?.expression);
  return canonicalGroups(expression).some(group => group.conditions.some(condition => isOpportunityStateField(condition.field))) || isOpportunityStateField(query?.sortBy);
}
```

Normalize legacy presets before checking. Delete display-name matching, arbitrary recursive traversal, capability props, and query-mutation effects from the hook.

- [ ] **Step 5: Apply sanitization in live/static controllers**

Controllers compare stable query keys and issue a sanitized replacement atomically. Capability restoration never replays removed filters. Clear active preset identity only when its normalized query requires the absent capability.

- [ ] **Step 6: Run GREEN and commit**

Run: `cd frontend && npx vitest run src/features/scan/opportunityCapabilityPolicy.test.js src/features/scan/hooks/useScanFilterPresets.test.jsx src/features/scan/pages/ScanPageContainer.test.jsx src/static/pages/StaticScanPage.test.jsx src/static/pages/StaticScanPage.opportunity.test.jsx --maxWorkers=4`

```bash
git add frontend/src/features/scan/opportunityCapabilityPolicy.js frontend/src/features/scan/opportunityCapabilityPolicy.test.js frontend/src/features/scan/hooks/useScanFilterPresets.js frontend/src/features/scan/hooks/useScanFilterPresets.test.jsx frontend/src/features/scan/pages/ScanPageContainer.jsx frontend/src/features/scan/pages/ScanPageContainer.test.jsx frontend/src/static/pages/StaticScanPage.jsx frontend/src/static/pages/StaticScanPage.test.jsx frontend/src/static/pages/StaticScanPage.opportunity.test.jsx
git commit -m "refactor: centralize opportunity capability policy"
```

### Task 8: Extract Results Opportunity Presentation

**Files:**
- Create: `frontend/src/components/Scan/OpportunityResultCells.jsx`
- Create: `frontend/src/components/Scan/useOpportunityEvidenceSelection.js`
- Modify: `frontend/src/components/Scan/ResultsTable.jsx`
- Modify: `frontend/src/components/Scan/ResultsTable.test.jsx`
- Modify: `frontend/src/components/shared/OpportunityEvidenceDrawer.jsx`
- Modify: `frontend/src/components/shared/OpportunityEvidenceDrawer.test.jsx`

**Interfaces:**
- Produces: focused opportunity cell rendering and symbol-keyed evidence selection lifecycle.

- [ ] **Step 1: Write failing alias, refresh, and rerender tests**

```javascript
it('does not read resilience_pillars', () => {
  render(<OpportunityEvidenceDrawer open row={{ opportunity_state: { resilience_pillars: { trend_integrity: 20 } } }} />);
  expect(screen.getByText('Not available')).toBeInTheDocument();
});
```

Selection test opens a symbol, rerenders refreshed rows, asserts new evidence, then removes the symbol and asserts closure.

- [ ] **Step 2: Run RED**

Run: `cd frontend && npx vitest run src/components/Scan/ResultsTable.test.jsx src/components/shared/OpportunityEvidenceDrawer.test.jsx --maxWorkers=4`

- [ ] **Step 3: Extract cells and selection; remove deep comparator**

Move opportunity cell handlers/rendering and drawer selection from `ResultsTable`. Delete the `JSON.stringify(opportunity_state)` comparator; use ordinary memoization with stable callbacks or accessor-derived equality.

- [ ] **Step 4: Remove the compatibility alias**

```javascript
const scorePillars = isRecord(evidence.score_pillars) ? evidence.score_pillars : {};
```

- [ ] **Step 5: Run GREEN, threshold checks, and commit**

Run: `cd frontend && npx vitest run src/components/Scan/ResultsTable.test.jsx src/components/shared/OpportunityEvidenceDrawer.test.jsx src/components/DailySnapshot/CorrectionSurvivorsPanel.test.jsx src/components/Watchlist/WatchlistTable.test.jsx --maxWorkers=4`

Run: `wc -l frontend/src/components/Scan/ResultsTable.jsx frontend/src/static/pages/StaticScanPage.test.jsx`

```bash
git add frontend/src/components/Scan/OpportunityResultCells.jsx frontend/src/components/Scan/useOpportunityEvidenceSelection.js frontend/src/components/Scan/ResultsTable.jsx frontend/src/components/Scan/ResultsTable.test.jsx frontend/src/components/shared/OpportunityEvidenceDrawer.jsx frontend/src/components/shared/OpportunityEvidenceDrawer.test.jsx
git commit -m "refactor: extract opportunity result presentation"
```

### Task 9: Integrated Verification and PR Update

**Files:**
- Update: `docs/superpowers/specs/2026-08-23-correction-survivors-maintainability-remediation-design.md`
- Create: `.superpowers/sdd/2026-08-21-correction-survivors-action-state/maintainability-remediation-report.md`

**Interfaces:**
- Produces: verified, reviewed, pushed PR #345 update.

- [ ] **Step 1: Run consolidated focused backend and frontend suites**

Run: `cd backend && ./venv/bin/pytest tests/unit/domain/test_opportunity_state.py tests/unit/test_opportunity_state_schema.py tests/unit/services/test_opportunity_state_service.py tests/unit/test_daily_snapshot_service.py tests/unit/test_daily_snapshot_opportunity_summary.py tests/unit/test_per_market_telemetry.py tests/unit/test_scan_result_assembler.py tests/unit/test_scan_orchestrator.py tests/unit/test_static_scan_bundle_exporter.py tests/unit/test_static_site_export_service.py tests/unit/use_cases/test_create_scan.py tests/unit/use_cases/test_create_scan_compile_path.py tests/unit/use_cases/test_get_scan_results.py tests/integration/test_opportunity_state_surface_parity.py -q`

Run: `cd frontend && npx vitest run src/features/scan/opportunityCapabilityPolicy.test.js src/features/scan/hooks/useScanFilterPresets.test.jsx src/features/scan/pages/ScanPageContainer.test.jsx src/static/pages/StaticScanPage.test.jsx src/static/pages/StaticScanPage.opportunity.test.jsx src/components/Scan/ResultsTable.test.jsx src/components/shared/OpportunityEvidenceDrawer.test.jsx --maxWorkers=4`

Expected: both consolidated suites are fully green.

- [ ] **Step 2: Validate migration upgrade/downgrade/re-upgrade**

Use the repository disposable PostgreSQL harness through `20260823_0029`, back to `20260821_0028`, and to head again. Run metadata preservation tests against that database.

- [ ] **Step 3: Run complete verification**

Run: `(cd backend && ./venv/bin/pytest -q)`

Run: `(cd frontend && npm run test:run -- --maxWorkers=4)`

Run: `(cd frontend && npm run lint)`

Run: `(cd frontend && npm run build)`

Expected: no new failures; report unchanged protected-theme environment gates and calibrated-simulator skips separately.

- [ ] **Step 4: Run structural, static, privacy, and thermo review**

```bash
wc -l backend/app/scanners/scan_orchestrator.py backend/app/services/static_site_export_service.py backend/tests/unit/test_daily_snapshot_service.py frontend/src/static/pages/StaticScanPage.test.jsx
git diff --check
git diff --stat origin/main...HEAD
```

Run changed-file Ruff `E4,E7,E9,F,I,C901`, targeted ESLint complexity checks, secret/privacy scans, and the thermo-nuclear review. Resolve every new Critical, Important, or threshold-crossing finding.

- [ ] **Step 5: Record verification and commit**

Set the design status to Implemented only after verification. Record exact commands, counts, accepted environment gates, final file sizes, and review verdict.

```bash
git add docs/superpowers/specs/2026-08-23-correction-survivors-maintainability-remediation-design.md .superpowers/sdd/2026-08-21-correction-survivors-action-state/maintainability-remediation-report.md
git commit -m "docs: record opportunity maintainability verification"
```

- [ ] **Step 6: Push and update PR #345**

```bash
git push origin codex/correction-survivors-action-state
gh pr view 345 --json url,state,baseRefName,headRefName,mergeable,statusCheckRollup
```

Update the PR with the seven resolved findings, verification evidence, and unchanged environment-gated tests.
