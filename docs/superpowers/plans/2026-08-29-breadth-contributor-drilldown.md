# Breadth Contributor Drilldown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an exact, historically frozen stock-and-IBD-group drilldown for the 11 supported Breadth Recent History count cells across all breadth-enabled live and static markets.

**Architecture:** The canonical revision-3 breadth engine will emit aggregate results and date-level contributor snapshots from the same per-symbol evaluation. SQLAlchemy stores each complete snapshot atomically beside its aggregate row, while live endpoints and additive static shards expose one `breadth-contributors-v1` contract. A shared React registry, loader, table interaction, and responsive dialog render stocks and expandable IBD groups without recalculating formulas in the browser or on click.

**Tech Stack:** Python 3, pandas, SQLAlchemy, Alembic, FastAPI/Pydantic, pytest, React 18, Material UI, TanStack Query, Vitest, static JSON artifacts

**Spec:** `docs/superpowers/specs/2026-08-29-breadth-contributor-drilldown-design.md`

## Global Constraints

- Keep `CURRENT_BREADTH_CALCULATION_REVISION = 3`; `breadth-contributors-v1` is a transport schema, not a formula version.
- Use the existing canonical predicates and market-calibrated policies; do not add a click-time, API-time, or static-only formula path.
- Support exactly the ten Primary/Secondary membership counts plus `atr_10x_extension_count`; ratios, T2108, Broad Universe, advancing/declining, and 52-week high/low remain noninteractive.
- Retain contributor snapshots for the latest 20 completed breadth sessions per breadth-enabled market without pruning aggregate breadth history.
- Store a complete parent snapshot even when its contributor list is empty.
- Store each symbol once per date with a signal-to-qualifying-value map; serialize return and distance values in percentage points and ATR extension as a multiple.
- Freeze company name and IBD group in the contributor snapshot; use `No Group` when the date-effective classification is absent.
- Reconcile every contributor signal count to its aggregate field before commit or publication.
- Keep old live breadth clients and static bundles without contributor files working unchanged.
- Preserve all unrelated user-owned working-tree files.

---

### Task 1: Emit contributor snapshots from the canonical engine

**Files:**
- Create: `backend/app/services/breadth/contributors.py`
- Modify: `backend/app/services/breadth/types.py`
- Modify: `backend/app/services/breadth/formulas.py`
- Modify: `backend/app/services/breadth/engine.py`
- Modify: `backend/app/services/breadth/__init__.py`
- Test: `backend/tests/unit/test_breadth_contributors.py`
- Test: `backend/tests/unit/test_breadth_engine.py`
- Test: `backend/tests/unit/test_breadth_formulas.py`

**Interfaces:**
- Produces: `CONTRIBUTOR_SCHEMA_ID = "breadth-contributors-v1"`, `CONTRIBUTOR_RETENTION_SESSIONS = 20`, and `BREADTH_CONTRIBUTOR_SIGNALS: Mapping[str, BreadthContributorSignalDefinition]`.
- Produces: `evaluate_symbol_at(...) -> SymbolBreadthEvaluation`; keep `signal_flags_at(...) -> SymbolBreadthSignals` as a compatibility wrapper.
- Produces: `BreadthEngine.calculate_with_contributors(request) -> BreadthEngineBatchResult`; keep `calculate(request) -> Mapping[date, BreadthDailyResult]` as an aggregate-only compatibility wrapper.
- Consumes: optional `BreadthEngineRequest.contributor_metadata_by_date: Mapping[date, Mapping[str, BreadthContributorMetadata]]`.

- [ ] **Step 1: Write failing registry, formula-parity, multi-signal, and empty-snapshot tests**

```python
def test_contributor_registry_maps_exactly_eleven_aggregate_fields():
    assert {spec.aggregate_field for spec in BREADTH_CONTRIBUTOR_SIGNALS.values()} == {
        "stocks_up_4pct", "stocks_down_4pct",
        "stocks_up_25pct_quarter", "stocks_down_25pct_quarter",
        "stocks_up_25pct_month", "stocks_down_25pct_month",
        "stocks_up_50pct_month", "stocks_down_50pct_month",
        "stocks_up_13pct_34days", "stocks_down_13pct_34days",
        "atr_10x_extension_count",
    }


def test_engine_stores_one_symbol_with_every_qualifying_signal():
    batch = BreadthEngine().calculate_with_contributors(_request_for_large_up_move())
    aggregate = batch.daily_results[TARGET_DATE]
    snapshot = batch.contributor_snapshots[TARGET_DATE]
    assert len(snapshot.contributors) == 1
    row = snapshot.contributors[0]
    assert row.symbol == "AAA"
    assert row.company_name == "Alpha Ltd"
    assert row.ibd_industry_group == "Semiconductors"
    assert row.daily_change_pct == pytest.approx(60.0)
    assert row.signals["up_4pct"] == pytest.approx(60.0)
    assert row.signals["up_25pct_month"] >= 25.0
    assert row.signals["up_50pct_month"] >= 50.0
    assert aggregate.values.stocks_up_4pct == 1


def test_engine_emits_complete_empty_contributor_snapshot():
    batch = BreadthEngine().calculate_with_contributors(_request_without_movers())
    snapshot = batch.contributor_snapshots[TARGET_DATE]
    assert snapshot.schema_id == "breadth-contributors-v1"
    assert snapshot.contributors == ()
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_breadth_contributors.py tests/unit/test_breadth_engine.py tests/unit/test_breadth_formulas.py -q`

Expected: FAIL because the contributor registry, evaluation values, metadata input, and batch result do not exist.

- [ ] **Step 3: Add the exact registry and immutable contributor types**

```python
# backend/app/services/breadth/contributors.py
CONTRIBUTOR_SCHEMA_ID = "breadth-contributors-v1"
CONTRIBUTOR_RETENTION_SESSIONS = 20
NO_GROUP_LABEL = "No Group"

@dataclass(frozen=True, slots=True)
class BreadthContributorSignalDefinition:
    signal_key: str
    aggregate_field: str
    direction: Literal["up", "down", "extension"]
    value_kind: Literal["percent", "multiple"]

BREADTH_CONTRIBUTOR_SIGNALS = {
    "up_4pct": BreadthContributorSignalDefinition("up_4pct", "stocks_up_4pct", "up", "percent"),
    "down_4pct": BreadthContributorSignalDefinition("down_4pct", "stocks_down_4pct", "down", "percent"),
    "up_25pct_quarter": BreadthContributorSignalDefinition("up_25pct_quarter", "stocks_up_25pct_quarter", "up", "percent"),
    "down_25pct_quarter": BreadthContributorSignalDefinition("down_25pct_quarter", "stocks_down_25pct_quarter", "down", "percent"),
    "up_25pct_month": BreadthContributorSignalDefinition("up_25pct_month", "stocks_up_25pct_month", "up", "percent"),
    "down_25pct_month": BreadthContributorSignalDefinition("down_25pct_month", "stocks_down_25pct_month", "down", "percent"),
    "up_50pct_month": BreadthContributorSignalDefinition("up_50pct_month", "stocks_up_50pct_month", "up", "percent"),
    "down_50pct_month": BreadthContributorSignalDefinition("down_50pct_month", "stocks_down_50pct_month", "down", "percent"),
    "up_13pct_34days": BreadthContributorSignalDefinition("up_13pct_34days", "stocks_up_13pct_34days", "up", "percent"),
    "down_13pct_34days": BreadthContributorSignalDefinition("down_13pct_34days", "stocks_down_13pct_34days", "down", "percent"),
    "atr_10x_extension": BreadthContributorSignalDefinition("atr_10x_extension", "atr_10x_extension_count", "extension", "multiple"),
}
```

```python
# backend/app/services/breadth/types.py
@dataclass(frozen=True, slots=True)
class BreadthContributorMetadata:
    company_name: str | None = None
    ibd_industry_group: str = "No Group"

@dataclass(frozen=True, slots=True)
class BreadthContributor:
    symbol: str
    company_name: str | None
    ibd_industry_group: str
    daily_change_pct: float
    signals: Mapping[str, float]

@dataclass(frozen=True, slots=True)
class BreadthContributorSnapshotResult:
    market: str
    calculation_date: date
    calculation_revision: int
    schema_id: str
    contributors: tuple[BreadthContributor, ...]

@dataclass(frozen=True, slots=True)
class BreadthEngineBatchResult:
    daily_results: Mapping[date, BreadthDailyResult]
    contributor_snapshots: Mapping[date, BreadthContributorSnapshotResult]
```

- [ ] **Step 4: Evaluate flags and qualifying values once, then return aggregate and snapshots together**

```python
# formulas.py: values are percentage points except extension_ratio.
@dataclass(frozen=True, slots=True)
class SymbolBreadthEvaluation:
    signals: SymbolBreadthSignals
    daily_change_pct: float | None
    qualifying_values: Mapping[str, float]

def signal_flags_at(*args, **kwargs) -> SymbolBreadthSignals:
    return evaluate_symbol_at(*args, **kwargs).signals
```

Move the current `signal_flags_at` body into `evaluate_symbol_at`, retain its exact boundary helpers, and build `qualifying_values` only for true flags using `daily_return * 100`, `month_return * 100`, `gain/loss_from_* * 100`, and the unrounded ATR extension ratio. In `BreadthEngine.calculate_with_contributors`, aggregate `evaluation.signals`, attach normalized metadata or `No Group`, omit symbols with no qualifying values, sort contributors by symbol, and call `reconcile_contributor_counts(snapshot, daily_result)`. Implement `calculate` as `return self.calculate_with_contributors(request).daily_results`.

- [ ] **Step 5: Run focused tests and commit the canonical output**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_breadth_contributors.py tests/unit/test_breadth_engine.py tests/unit/test_breadth_formulas.py tests/unit/test_breadth_workflow_parity.py -q`

Expected: PASS.

```bash
git add backend/app/services/breadth backend/tests/unit/test_breadth_contributors.py backend/tests/unit/test_breadth_engine.py backend/tests/unit/test_breadth_formulas.py backend/tests/unit/test_breadth_workflow_parity.py
git commit -m "feat: emit canonical breadth contributor snapshots"
```

### Task 2: Add atomic contributor persistence and retention

**Files:**
- Create: `backend/app/models/breadth_contributor.py`
- Create: `backend/alembic/versions/20260829_0033_add_breadth_contributor_snapshots.py`
- Create: `backend/tests/integration/test_breadth_contributor_migration.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/services/breadth/persistence.py`
- Modify: `backend/tests/unit/test_breadth_persistence.py`

**Interfaces:**
- Produces: models `MarketBreadthContributorSnapshot` and `MarketBreadthContributor`.
- Produces: `BreadthPersistence.upsert_daily(result, *, contributor_snapshot=None, duration_seconds)` and `upsert_many(results, *, contributor_snapshots_by_date=None, duration_seconds_by_date=None)`.
- Produces: `replace_contributor_snapshots(snapshots, *, expected_aggregates)`, which never updates aggregate rows.

- [ ] **Step 1: Write failing migration and transaction tests**

```python
def test_contributor_migration_creates_parent_child_contract(tmp_path):
    engine = _legacy_breadth_database(tmp_path)
    _run_revision(engine, "upgrade")
    inspector = sa.inspect(engine)
    assert {"market_breadth_contributor_snapshots", "market_breadth_contributors"}.issubset(inspector.get_table_names())
    assert any(item["name"] == "uq_breadth_contributor_snapshot_market_date" for item in inspector.get_unique_constraints("market_breadth_contributor_snapshots"))


def test_count_mismatch_rolls_back_aggregate_and_snapshot(db):
    before = _stored_aggregate(db, advancing_count=8)
    with pytest.raises(ValueError, match="stocks_up_4pct"):
        BreadthPersistence(db).upsert_daily(
            _result(advancing=9),
            contributor_snapshot=_snapshot(signals={}),
            duration_seconds=0.5,
        )
    assert db.get(MarketBreadth, before.id).advancing_count == 8
    assert db.query(MarketBreadthContributorSnapshot).count() == 0


def test_retention_keeps_latest_twenty_dates_without_deleting_aggregates(db):
    _persist_21_complete_days(db)
    assert db.query(MarketBreadthContributorSnapshot).count() == 20
    assert db.query(MarketBreadth).count() == 21
```

- [ ] **Step 2: Run persistence tests and confirm RED**

Run: `cd backend && ./venv/bin/pytest tests/integration/test_breadth_contributor_migration.py tests/unit/test_breadth_persistence.py -q`

Expected: FAIL because revision `0033`, models, atomic snapshot replacement, and retention do not exist.

- [ ] **Step 3: Create the additive schema and SQLAlchemy models**

```python
class MarketBreadthContributorSnapshot(Base):
    __tablename__ = "market_breadth_contributor_snapshots"
    id = Column(Integer, primary_key=True)
    market = Column(String(8), nullable=False)
    date = Column(Date, nullable=False)
    calculation_revision = Column(Integer, nullable=False)
    schema_id = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(["date", "market"], ["market_breadth.date", "market_breadth.market"], ondelete="CASCADE"),
        UniqueConstraint("market", "date", name="uq_breadth_contributor_snapshot_market_date"),
        Index("ix_breadth_contributor_snapshot_market_date", "market", "date"),
    )

class MarketBreadthContributor(Base):
    __tablename__ = "market_breadth_contributors"
    id = Column(Integer, primary_key=True)
    snapshot_id = Column(Integer, ForeignKey("market_breadth_contributor_snapshots.id", ondelete="CASCADE"), nullable=False, index=True)
    symbol = Column(String(32), nullable=False)
    company_name = Column(String(255), nullable=True)
    ibd_industry_group = Column(String(255), nullable=False, default="No Group")
    daily_change_pct = Column(Float, nullable=False)
    signals_json = Column(JSON, nullable=False)
    __table_args__ = (UniqueConstraint("snapshot_id", "symbol", name="uq_breadth_contributor_snapshot_symbol"),)
```

Set migration `down_revision = "20260825_0032"`; create the parent before the child and drop in reverse order. Export both models from `app.models` so Alembic metadata and test databases include them.

- [ ] **Step 4: Implement reconciliation, atomic replacement, contributors-only backfill writes, and post-success pruning**

Use `reconcile_contributor_counts` before mutating the session. Flush the aggregate before inserting its parent, delete an existing parent for the same market/date, insert deterministic child rows, and commit aggregate plus snapshot together. After a successful commit, delete parents outside the newest 20 dates for that market in a second transaction. `replace_contributor_snapshots` must first load and compare all existing aggregates, then replace the complete market set in one commit without calling `_assign` on `MarketBreadth`.

- [ ] **Step 5: Run tests and commit persistence**

Run: `cd backend && ./venv/bin/pytest tests/integration/test_breadth_contributor_migration.py tests/unit/test_breadth_persistence.py tests/unit/test_alembic_baseline.py -q`

Expected: PASS.

```bash
git add backend/alembic/versions/20260829_0033_add_breadth_contributor_snapshots.py backend/app/models backend/app/services/breadth/persistence.py backend/tests/integration/test_breadth_contributor_migration.py backend/tests/unit/test_breadth_persistence.py
git commit -m "feat: persist breadth contributor snapshots atomically"
```

### Task 3: Wire metadata, daily calculation, historical rebuild, and one-time backfill

**Files:**
- Create: `backend/app/services/breadth/contributor_metadata.py`
- Create: `backend/app/services/breadth/contributor_backfill.py`
- Create: `backend/app/scripts/backfill_breadth_contributors.py`
- Create: `backend/tests/unit/test_breadth_contributor_backfill.py`
- Modify: `backend/app/services/breadth_coverage.py`
- Modify: `backend/app/services/breadth_calculator_service.py`
- Modify: `backend/app/services/breadth_backfill.py`
- Modify: `backend/app/services/daily_breadth_runner.py`
- Modify: `backend/tests/unit/test_breadth_calculator_service.py`
- Modify: `backend/tests/unit/test_breadth_backfill.py`
- Modify: `backend/tests/unit/test_daily_breadth_runner.py`

**Interfaces:**
- Produces: `BreadthContributorMetadataLoader.current(db, market, symbols)` and `.historical(db, market, symbols_by_date)`.
- Produces: `BreadthCalculationResult.contributor_snapshot`.
- Produces: `BreadthContributorBackfillService.run(market, limit=20) -> BreadthContributorBackfillReport`.
- CLI: `cd backend && ./venv/bin/python -m app.scripts.backfill_breadth_contributors --markets US,CA --limit 20`.

- [ ] **Step 1: Write failing frozen-metadata and contributors-only backfill tests**

```python
def test_historical_metadata_uses_exact_date_feature_run_and_no_newer_group(db):
    _feature_run(db, "US", date(2026, 8, 20), "AAA", group="Old Group", name="Alpha")
    _feature_run(db, "US", date(2026, 8, 21), "AAA", group="New Group", name="Alpha Inc")
    result = BreadthContributorMetadataLoader.historical(db, "US", {date(2026, 8, 20): ("AAA", "MISSING")})
    assert result[date(2026, 8, 20)]["AAA"].ibd_industry_group == "Old Group"
    assert result[date(2026, 8, 20)]["MISSING"].ibd_industry_group == "No Group"


def test_contributor_backfill_commits_all_twenty_or_none_and_never_updates_aggregates(db):
    original = _seed_twenty_revision_three_aggregates(db)
    report = _service(db).run("US", limit=20)
    assert report.committed_dates == 20
    assert _aggregate_values(db) == original
    committed_snapshots = _snapshot_values(db)
    _force_one_count_mismatch(db)
    with pytest.raises(BreadthContributorBackfillMismatch):
        _service(db).run("US", limit=20)
    assert _aggregate_values(db) == original
    assert _snapshot_values(db) == committed_snapshots
```

- [ ] **Step 2: Run adapter/backfill tests and confirm RED**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_breadth_contributor_backfill.py tests/unit/test_breadth_calculator_service.py tests/unit/test_breadth_backfill.py tests/unit/test_daily_breadth_runner.py -q`

Expected: FAIL because metadata loading and contributor-aware calculation/persistence are not wired.

- [ ] **Step 3: Implement deterministic current and historical metadata loading**

For current sessions, load `StockUniverse.name` and invert `IBDIndustryService.get_group_memberships(db, market=market)` once per market. For historical dates, select the newest `published` `FeatureRun` whose exact `as_of_date` and `feature_run_market(run)` match; when no published run exists for that exact date, use its newest `completed` run. Then read `StockFeatureDaily.details_json.company_name` and `.ibd_industry_group`. Do not use a later run for an earlier date; produce `BreadthContributorMetadata(None, "No Group")` for missing rows.

- [ ] **Step 4: Carry contributor snapshots through production paths and add the all-or-none backfill command**

```python
@dataclass(frozen=True)
class BreadthCalculationResult:
    indicators: Mapping[str, Any]
    coverage: BreadthCoverageReport
    daily_result: BreadthDailyResult | None = None
    contributor_snapshot: BreadthContributorSnapshotResult | None = None
```

Make daily calculation call `calculate_with_contributors`, return both results, and make `run_daily_breadth` pass both to `store_daily_result`. Refactor `BreadthBackfillExecutor` to calculate one `BreadthEngineBatchResult`; normal execution calls `upsert_many` with both mappings, while contributor-only execution calls `replace_contributor_snapshots` against the unchanged revision-3 aggregate rows. The CLI derives the newest 20 dates from `breadth_query`, runs strict cache-only calculation per market, prints mismatch rows as `market,date,signal,aggregate_count,contributor_count`, and exits nonzero if any market fails.

- [ ] **Step 5: Run tests and commit adapter/backfill wiring**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_breadth_contributor_backfill.py tests/unit/test_breadth_calculator_service.py tests/unit/test_breadth_backfill.py tests/unit/test_daily_breadth_runner.py tests/unit/test_breadth_rebuild.py -q`

Expected: PASS.

```bash
git add backend/app/services/breadth backend/app/services/breadth_coverage.py backend/app/services/breadth_calculator_service.py backend/app/services/breadth_backfill.py backend/app/services/daily_breadth_runner.py backend/app/scripts/backfill_breadth_contributors.py backend/tests/unit/test_breadth_contributor_backfill.py backend/tests/unit/test_breadth_calculator_service.py backend/tests/unit/test_breadth_backfill.py backend/tests/unit/test_daily_breadth_runner.py
git commit -m "feat: wire breadth contributor calculation and backfill"
```

### Task 4: Add the live contributor index and date endpoints

**Files:**
- Create: `backend/app/services/breadth/contributor_query.py`
- Modify: `backend/app/schemas/breadth.py`
- Modify: `backend/app/api/v1/breadth.py`
- Modify: `backend/tests/unit/test_breadth_endpoints.py`
- Test: `backend/tests/unit/test_breadth_contributor_query.py`

**Interfaces:**
- Produces: `list_contributor_dates(db, market, limit=20) -> BreadthContributorIndexPayload`.
- Produces: `get_contributor_document(db, market, calculation_date) -> BreadthContributorDocumentPayload`.
- HTTP: `GET /v1/breadth/contributors/index?market=US` and `GET /v1/breadth/contributors?market=US&date=2026-08-28`.

- [ ] **Step 1: Write failing query and endpoint contract tests**

```python
def test_contributor_index_is_newest_first_and_limited(client, db):
    _seed_complete_snapshots(db, count=21)
    response = client.get("/api/v1/breadth/contributors/index", params={"market": "US"})
    assert response.status_code == 200
    body = response.json()
    assert body["schema"] == "breadth-contributors-v1"
    assert body["calculation_revision"] == 3
    assert len(body["dates"]) == 20
    assert body["dates"] == sorted(body["dates"], reverse=True)


def test_contributor_date_returns_404_unavailable_and_409_inconsistent(client, db):
    assert client.get("/api/v1/breadth/contributors", params={"market": "US", "date": "2026-08-28"}).status_code == 404
    _seed_corrupt_snapshot(db)
    assert client.get("/api/v1/breadth/contributors", params={"market": "US", "date": "2026-08-28"}).status_code == 409
```

- [ ] **Step 2: Run endpoint tests and confirm RED**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_breadth_contributor_query.py tests/unit/test_breadth_endpoints.py -q`

Expected: FAIL with missing query service, schemas, and routes.

- [ ] **Step 3: Add strict Pydantic payloads and read-side validation**

```python
class BreadthContributorItem(BaseModel):
    symbol: str
    company_name: str | None = None
    ibd_industry_group: str
    daily_change_pct: float
    signals: dict[str, float]

class BreadthContributorIndexResponse(BaseModel):
    schema: Literal["breadth-contributors-v1"]
    market: str
    calculation_revision: Literal[3]
    dates: list[Date]

class BreadthContributorDocumentResponse(BaseModel):
    schema: Literal["breadth-contributors-v1"]
    market: str
    date: Date
    calculation_revision: Literal[3]
    contributors: list[BreadthContributorItem]
```

The query service loads the parent and children, rejects duplicate symbols, unknown/nonfinite signal values, schema/revision mismatch, and count mismatch with the corresponding `MarketBreadth` row. The index omits inconsistent snapshots and logs their market/date/reason.

- [ ] **Step 4: Add guarded routes with stable 404 and 409 behavior**

Reuse `_normalize_market_param`. Return `404` when no active snapshot exists for the requested date and `409` when `BreadthContributorSnapshotInconsistent` is raised. Do not change `/current`, `/historical`, `/trend`, or their response models.

- [ ] **Step 5: Run tests and commit the live contract**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_breadth_contributor_query.py tests/unit/test_breadth_endpoints.py -q`

Expected: PASS.

```bash
git add backend/app/services/breadth/contributor_query.py backend/app/schemas/breadth.py backend/app/api/v1/breadth.py backend/tests/unit/test_breadth_contributor_query.py backend/tests/unit/test_breadth_endpoints.py
git commit -m "feat: expose breadth contributor API"
```

### Task 5: Publish and validate additive static contributor shards

**Files:**
- Create: `backend/app/services/static_breadth_contributor_exporter.py`
- Create: `backend/tests/unit/test_static_breadth_contributor_exporter.py`
- Modify: `backend/app/services/static_site_export_service.py`
- Modify: `backend/app/services/static_artifact_combiner.py`
- Modify: `backend/app/services/static_breadth_section_builder.py`
- Modify: `backend/app/services/breadth_attribution_service.py`
- Modify: `backend/tests/unit/test_static_site_export_service.py`
- Modify: `backend/tests/unit/test_static_market_artifact_validation.py`
- Modify: `backend/tests/unit/test_breadth_attribution_service.py`

**Interfaces:**
- Produces: `StaticBreadthContributorExporter.export(db, output_dir, path_prefix, breadth_payload) -> dict | None`.
- Static asset descriptor: `entry.assets.breadth_contributors.index_path`.
- Static files: `markets/<market>/breadth/contributors/index.json` and one `<date>.json` per advertised date.
- Changes `BreadthAttributionService` to summarize persisted contributor documents; it no longer accepts or evaluates price frames.

- [ ] **Step 1: Write failing static export, legacy-bundle, and market-isolation tests**

```python
def test_static_export_writes_index_and_twenty_date_shards(tmp_path, db):
    _seed_complete_snapshots(db, market="CA", count=20)
    asset = StaticBreadthContributorExporter().export(db, tmp_path, Path("markets/ca"), _breadth_payload("CA"))
    assert asset == {"index_path": "markets/ca/breadth/contributors/index.json"}
    index = _read(tmp_path / asset["index_path"])
    assert index["market"] == "CA"
    assert len(index["dates"]) == 20
    assert _read(tmp_path / "markets/ca/breadth/contributors" / f"{index['dates'][0]}.json")["market"] == "CA"


def test_combiner_accepts_legacy_market_without_contributor_asset(tmp_path):
    artifact = _legacy_valid_market_artifact(tmp_path, market="US")
    assert _combine(artifact).manifest["markets"]["US"]["features"]["breadth"] is True


def test_invalid_contributors_warn_but_do_not_remove_market(tmp_path):
    result = _export_with_missing_contributor_date(tmp_path, market="DE")
    assert "DE" in result.manifest["supported_markets"]
    assert "breadth_contributors" not in result.manifest["markets"]["DE"]["assets"]


def test_exporter_market_support_matches_breadth_catalog():
    expected = set(get_market_catalog().market_codes_with_capability("breadth"))
    assert set(StaticBreadthContributorExporter.supported_markets()) == expected
```

- [ ] **Step 2: Run static tests and confirm RED**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_static_breadth_contributor_exporter.py tests/unit/test_static_site_export_service.py tests/unit/test_static_market_artifact_validation.py tests/unit/test_breadth_attribution_service.py -q`

Expected: FAIL because no static shard exporter or contributor asset validation exists.

- [ ] **Step 3: Export one shared contract without enlarging `breadth.json`**

Select the newest 20 dates present in `payload.history_90d`, load validated documents through `contributor_query`, stage the index and shards under `breadth/contributors`, and replace any prior contributor directory only after every count reconciles. This removes stale shards outside the retained set without exposing a partial directory. On unavailable/inconsistent data, delete the stage, return `None`, and append a warning; still write the valid aggregate `breadth.json` and market entry. Add the asset descriptor only when export succeeds.

- [ ] **Step 4: Validate optional shards during artifact combination and retire price-based attribution**

When `assets.breadth_contributors.index_path` exists, `StaticArtifactCombiner` verifies safe relative paths, schema/revision/market, newest-first unique dates capped at 20, every shard's market/date, unique symbols, known finite signals, and reconciliation to `breadth.json`. Absence remains valid. Rework `BreadthAttributionService` to consume contributor documents and derive its existing ±4% group history; remove `prepare_feature_frame` and `signal_flags_at` imports so no independent static predicate remains.

- [ ] **Step 5: Run tests and commit static publication**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_static_breadth_contributor_exporter.py tests/unit/test_static_site_export_service.py tests/unit/test_static_market_artifact_validation.py tests/unit/test_static_artifact_combiner.py tests/unit/test_breadth_attribution_service.py -q`

Expected: PASS.

```bash
git add backend/app/services/static_breadth_contributor_exporter.py backend/app/services/static_site_export_service.py backend/app/services/static_artifact_combiner.py backend/app/services/static_breadth_section_builder.py backend/app/services/breadth_attribution_service.py backend/tests/unit/test_static_breadth_contributor_exporter.py backend/tests/unit/test_static_site_export_service.py backend/tests/unit/test_static_market_artifact_validation.py backend/tests/unit/test_breadth_attribution_service.py
git commit -m "feat: publish static breadth contributor shards"
```

### Task 6: Add shared frontend contributor definitions and data shaping

**Files:**
- Create: `frontend/src/components/Breadth/breadthContributorView.js`
- Create: `frontend/src/components/Breadth/breadthContributorView.test.js`
- Create: `frontend/src/components/Breadth/useBreadthContributors.js`
- Create: `frontend/src/components/Breadth/useBreadthContributors.test.jsx`
- Modify: `frontend/src/components/Breadth/breadthMetricDefinitions.js`
- Modify: `frontend/src/api/breadth.js`
- Modify: `frontend/src/static/dataClient.js`

**Interfaces:**
- Produces: contributor metadata on the existing 11 metric definitions: `{ signalKey, direction, valueKind, qualifierLabel }`.
- Produces: `buildBreadthContributorView(document, metric, expectedCount)`.
- Produces: `useBreadthContributors({ market, indexQueryKey, loadIndex, loadDate })` with `availableDates`, `open`, `close`, and dialog query state.

- [ ] **Step 1: Write failing filter, order, group-share, cache, and index tests**

```javascript
it('filters one signal, sorts down values lowest first, and keeps No Group last', () => {
  const view = buildBreadthContributorView(document, 'stocks_down_25pct_month', 3);
  expect(view.stocks.map((row) => row.symbol)).toEqual(['AAA', 'CCC', 'BBB']);
  expect(view.groups.at(-1).name).toBe('No Group');
  expect(view.groups.reduce((sum, group) => sum + group.count, 0)).toBe(3);
  expect(view.groups[0].sharePct).toBeCloseTo((view.groups[0].count / 3) * 100);
});

it('rejects a document whose selected signal count differs from the cell', () => {
  expect(() => buildBreadthContributorView(document, 'stocks_up_4pct', 99))
    .toThrow('Contributor count does not match breadth history');
});
```

- [ ] **Step 2: Run frontend data tests and confirm RED**

Run: `cd frontend && npx vitest run src/components/Breadth/breadthContributorView.test.js src/components/Breadth/useBreadthContributors.test.jsx`

Expected: FAIL because the contributor definition, view builder, hook, and clients do not exist.

- [ ] **Step 3: Extend the metric registry and implement strict view shaping**

```javascript
// Example entries; add the same object to all 11 approved metrics.
stocks_up_4pct: stockBee({
  label: 'Stocks Up 4%+',
  contributor: { signalKey: 'up_4pct', direction: 'up', valueKind: 'percent', qualifierLabel: '1-day change' },
  // existing definition fields remain unchanged
}),
atr_10x_extension_count: {
  // existing fields remain unchanged
  contributor: { signalKey: 'atr_10x_extension', direction: 'extension', valueKind: 'multiple', qualifierLabel: 'ATR extension' },
},
```

`buildBreadthContributorView` validates schema `breadth-contributors-v1`, revision `3`, known metric, finite daily/signal values, and exact expected count. It returns direction-sorted stocks and groups shaped as `{name, count, sharePct, stocks}` with count/name ordering and `No Group` last.

- [ ] **Step 4: Implement lazy date loading shared by live and static pages**

Add `getBreadthContributorIndex(market)` and `getBreadthContributors(market, date)` to the live API client. Add `fetchStaticBreadthContributorIndex(indexPath)` and `fetchStaticBreadthContributors(indexPath, date)`, deriving the date file from the validated index directory. The hook loads the index immediately, opens only advertised dates, enables a TanStack date query only while selected, keys its cache by market/date/schema/revision, and retains a valid cached document after a retryable request failure.

- [ ] **Step 5: Run tests and commit frontend data logic**

Run: `cd frontend && npx vitest run src/components/Breadth/breadthContributorView.test.js src/components/Breadth/useBreadthContributors.test.jsx`

Expected: PASS.

```bash
git add frontend/src/components/Breadth/breadthMetricDefinitions.js frontend/src/components/Breadth/breadthContributorView.js frontend/src/components/Breadth/breadthContributorView.test.js frontend/src/components/Breadth/useBreadthContributors.js frontend/src/components/Breadth/useBreadthContributors.test.jsx frontend/src/api/breadth.js frontend/src/static/dataClient.js
git commit -m "feat: add breadth contributor frontend data layer"
```

### Task 7: Build the responsive Stocks and IBD Groups dialog

**Files:**
- Create: `frontend/src/components/Breadth/BreadthContributorDialog.jsx`
- Create: `frontend/src/components/Breadth/BreadthContributorDialog.test.jsx`

**Interfaces:**
- Consumes: `{ open, metric, row, view, isLoading, error, unavailable, onRetry, onClose }`.
- Produces: one Material UI dialog with `Stocks` and `IBD Groups` tabs and expandable group rows.

- [ ] **Step 1: Write failing dialog behavior and accessibility tests**

```javascript
it('shows compact stocks then expands an IBD group', async () => {
  render(<BreadthContributorDialog {...readyProps} />);
  expect(screen.getByRole('dialog', { name: /Up 4%\+ Today.*728 stocks/i })).toBeInTheDocument();
  expect(screen.getByRole('columnheader', { name: 'Qualifying value' })).toBeInTheDocument();
  await user.click(screen.getByRole('tab', { name: 'IBD Groups' }));
  await user.click(screen.getByRole('button', { name: /Semiconductors.*34 stocks/i }));
  expect(screen.getByText('AEHR')).toBeInTheDocument();
});

it.each(['loading', 'error', 'unavailable', 'inconsistent'])('contains the %s state inside the dialog', (state) => {
  render(<BreadthContributorDialog {...propsFor(state)} />);
  expect(screen.getByRole('dialog')).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the dialog test and confirm RED**

Run: `cd frontend && npx vitest run src/components/Breadth/BreadthContributorDialog.test.jsx`

Expected: FAIL because the dialog does not exist.

- [ ] **Step 3: Implement the compact Stocks tab and contained states**

Use `Dialog fullScreen={useMediaQuery(theme.breakpoints.down('sm'))} maxWidth="md" fullWidth`. The header renders metric label, formatted date, and count. The stock table columns are Ticker, Company, IBD Group, Qualifying value, and 1-day change; company/group use ellipsis plus tooltips. Percent values include signs and two decimals; ATR values render as `12.34x`. Loading uses a centered spinner, error includes Retry, unavailable uses an info alert, and inconsistent uses a warning without rendering rows.

- [ ] **Step 4: Implement expandable IBD Groups and focus-safe close**

Render group count and share, keep only one expansion state per group name, and show the same sorted stock list inside a `Collapse`. Use semantic buttons with `aria-expanded`. Let Material UI restore focus to the opening element; do not disable `restoreFocus`.

- [ ] **Step 5: Run tests and commit the dialog**

Run: `cd frontend && npx vitest run src/components/Breadth/BreadthContributorDialog.test.jsx`

Expected: PASS.

```bash
git add frontend/src/components/Breadth/BreadthContributorDialog.jsx frontend/src/components/Breadth/BreadthContributorDialog.test.jsx
git commit -m "feat: add breadth contributor dialog"
```

### Task 8: Make Recent History cells interactive and wire live/static pages

**Files:**
- Modify: `frontend/src/components/Breadth/BreadthHistoryTable.jsx`
- Modify: `frontend/src/components/Breadth/BreadthHistoryTable.test.jsx`
- Modify: `frontend/src/pages/BreadthPage.jsx`
- Modify: `frontend/src/pages/BreadthPage.test.jsx`
- Modify: `frontend/src/static/pages/StaticBreadthPage.jsx`
- Modify: `frontend/src/static/pages/StaticBreadthPage.test.jsx`

**Interfaces:**
- `BreadthHistoryTable({ rows, maxRows, contributorDates = new Set(), onContributorCellClick })`.
- Live page supplies live index/date loaders; static page supplies the manifest asset's `index_path` and static loaders.
- Both pages render the same `BreadthContributorDialog`.

- [ ] **Step 1: Write failing table and page integration tests**

```javascript
it('makes only advertised nonzero contributor cells buttons without changing column widths', async () => {
  const onOpen = vi.fn();
  renderWithProviders(<BreadthHistoryTable rows={[row]} contributorDates={new Set([row.date])} onContributorCellClick={onOpen} />);
  await user.click(screen.getByRole('button', { name: 'View 12 contributing stocks for Stocks Up 4%+' }));
  expect(onOpen).toHaveBeenCalledWith('stocks_up_4pct', row, expect.any(HTMLElement));
  expect(screen.queryByRole('button', { name: /5 Day Ratio/ })).not.toBeInTheDocument();
});

it('live and static pages open the same dialog and fetch one date lazily', async () => {
  renderBreadthPageWithContributorIndex();
  await user.click(await screen.findByRole('button', { name: /View 12 contributing stocks/ }));
  expect(mockGetBreadthContributors).toHaveBeenCalledTimes(1);
  await user.click(screen.getByRole('tab', { name: 'IBD Groups' }));
  expect(screen.getByText('Semiconductors')).toBeInTheDocument();
});
```

- [ ] **Step 2: Run table/page tests and confirm RED**

Run: `cd frontend && npx vitest run src/components/Breadth/BreadthHistoryTable.test.jsx src/pages/BreadthPage.test.jsx src/static/pages/StaticBreadthPage.test.jsx`

Expected: FAIL because the table has no interactive-cell contract and the pages do not load contributor assets.

- [ ] **Step 3: Render full-cell buttons only for approved available nonzero counts**

Inside each existing `TableCell`, compute `definition.contributor && contributorDates.has(row.date) && Number(row[metric]) > 0`. Render a zero-padding `ButtonBase` that fills the cell, preserves inherited color/font/background, adds a visible `:focus-visible` outline, and calls `onContributorCellClick(metric, row, event.currentTarget)`. Keep the existing `<colgroup>`, `minWidth`, group borders, header lines, heatmap tones, and plain-cell rendering unchanged.

- [ ] **Step 4: Wire the live and static loaders and shared dialog**

Live `BreadthPage` calls the hook with `getBreadthContributorIndex` and `getBreadthContributors`. An index error yields an empty availability set and leaves the aggregate page unchanged. `StaticBreadthPage` reads `marketEntry.assets.breadth_contributors?.index_path`; absence likewise yields an empty set and no failed request. Both pass the hook's dates/callback to the table and render one dialog after the table. Keep the existing static `By Group` tab; its payload now comes from canonical snapshots via Task 5.

- [ ] **Step 5: Run frontend regression tests, lint, build, and commit integration**

Run: `cd frontend && npx vitest run src/components/Breadth/BreadthHistoryTable.test.jsx src/components/Breadth/BreadthContributorDialog.test.jsx src/components/Breadth/breadthContributorView.test.js src/components/Breadth/useBreadthContributors.test.jsx src/pages/BreadthPage.test.jsx src/static/pages/StaticBreadthPage.test.jsx`

Run: `cd frontend && npm run lint && npm run build`

Expected: all tests PASS, ESLint exits 0, and Vite production build exits 0 without widening the table fixture.

```bash
git add frontend/src/components/Breadth/BreadthHistoryTable.jsx frontend/src/components/Breadth/BreadthHistoryTable.test.jsx frontend/src/pages/BreadthPage.jsx frontend/src/pages/BreadthPage.test.jsx frontend/src/static/pages/StaticBreadthPage.jsx frontend/src/static/pages/StaticBreadthPage.test.jsx
git commit -m "feat: wire breadth contributor drilldowns"
```

### Task 9: Document rollout and run the complete verification matrix

**Files:**
- Create: `docs/runbooks/breadth-contributor-backfill.md`
- Modify: `docs/STATIC_SITE.md`
- Test: `backend/tests/unit/test_breadth_workflow_parity.py`

**Interfaces:**
- Documents schema upgrade, 20-session all-or-none backfill, validation report, static regeneration, rollback behavior, and post-deploy checks.
- Produces final live/static parity coverage for US plus one non-US market.

- [ ] **Step 1: Add a failing parity test covering an up, down, and ATR signal**

```python
@pytest.mark.parametrize("market", ["US", "CA"])
def test_live_and_static_contributor_documents_match_for_all_signal_kinds(market):
    batch = _canonical_batch_with_up_down_and_atr(market)
    persisted = _persist_and_read_live_document(batch)
    exported = _export_and_read_static_document(batch)
    assert exported == persisted
    assert {"up_4pct", "down_25pct_month", "atr_10x_extension"}.issubset(
        {key for row in persisted["contributors"] for key in row["signals"]}
    )
```

- [ ] **Step 2: Run the parity test and confirm RED if any adapter still diverges**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_breadth_workflow_parity.py -q`

Expected: PASS only when live persistence and static serialization use the same canonical contributor result; otherwise FAIL on document equality.

- [ ] **Step 3: Write the operator runbook with exact safe commands and failure semantics**

Document these commands and state that the backfill leaves aggregate rows untouched and commits no contributor rows for a market when one date mismatches:

```bash
cd backend
./venv/bin/alembic upgrade head
./venv/bin/python -m app.scripts.backfill_breadth_contributors --markets US,CA,DE,HK,IN,JP,KR,TW,CN --limit 20
./venv/bin/pytest tests/unit/test_breadth_contributor_query.py tests/unit/test_static_breadth_contributor_exporter.py -q
```

Add the new optional `assets.breadth_contributors.index_path` layout to `docs/STATIC_SITE.md` and explicitly state that bundles without it remain supported.

- [ ] **Step 4: Run the backend and frontend verification suites**

Run: `cd backend && ./venv/bin/pytest tests/unit/test_breadth_contributors.py tests/unit/test_breadth_engine.py tests/unit/test_breadth_persistence.py tests/unit/test_breadth_contributor_backfill.py tests/unit/test_breadth_contributor_query.py tests/unit/test_breadth_endpoints.py tests/unit/test_static_breadth_contributor_exporter.py tests/unit/test_static_site_export_service.py tests/unit/test_static_market_artifact_validation.py tests/unit/test_breadth_workflow_parity.py tests/integration/test_breadth_contributor_migration.py -q`

Run: `cd frontend && npm run test:run && npm run lint && npm run build`

Expected: all backend and frontend tests PASS, ESLint exits 0, and the production build exits 0.

- [ ] **Step 5: Commit rollout documentation and final parity coverage**

```bash
git add docs/runbooks/breadth-contributor-backfill.md docs/STATIC_SITE.md backend/tests/unit/test_breadth_workflow_parity.py
git commit -m "docs: add breadth contributor rollout runbook"
```

## Final Acceptance Checklist

- [ ] Apply the migration and run the contributor-only backfill against a disposable copy of an existing database; confirm aggregate row hashes are unchanged.
- [ ] Confirm each breadth-enabled market advertises no more than 20 newest-first dates and every advertised signal count reconciles.
- [ ] Confirm US and one non-US live page open up, down, and ATR cells; stock count and expanded group totals equal the clicked count.
- [ ] Generate a static bundle and confirm the same sampled market/date documents equal the live API documents.
- [ ] Load a legacy static bundle without contributor assets and confirm Recent History still renders with noninteractive cells.
- [ ] At the supported desktop viewport, confirm the table retains its existing width and does not introduce new horizontal scrolling.
- [ ] On a mobile viewport, confirm the dialog becomes full-screen, group rows expand, retry works, and closing returns focus to the source cell.
