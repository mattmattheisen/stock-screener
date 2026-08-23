# Correction Survivors maintainability remediation report

Date: 2026-08-23

Branch: `codex/correction-survivors-action-state`

Implementation head before this report: `9b656dc56a1b5298b6fbd5bf487fc6b8649acf07`

## Outcome

The thermo-nuclear maintainability review is resolved. All seven findings were
implemented without changing the opportunity-state policy, response fields,
static manifest contract, legacy all-null semantics, or supported UI behavior.
The final re-review found no remaining Critical, Important, or new threshold-
crossing issue in the feature diff.

## Findings resolved

1. **Monolithic opportunity domain:** split into typed model, pure policy,
   canonical projection codec, and stewardship overlay modules. Inactive policy
   modes and parallel availability booleans were removed.
2. **Repeated/mutable projection assembly:** scanner and snapshot inputs are
   normalized into typed evidence once, evaluated once, and serialized once.
   Canonical keys, states, pillars, and coherence rules have one backend owner.
3. **Internal metadata in user criteria:** direct-scan materialization versions
   now live in `Scan.metadata_json`; FeatureRun configuration remains
   authoritative for snapshot-backed scans. Capability resolution accepts
   explicit typed sources and performs no row inference or ORM reflection.
4. **Repeated summary SQL and telemetry coupling:** Daily Snapshot and telemetry
   share one typed opportunity-summary reader. Counts use one aggregate query;
   telemetry no longer owns feature SQL or a session lifecycle.
5. **Oversized scan orchestration:** result construction moved to the independently
   tested `ScanResultAssembler`. Data preparation, screener execution, terminal
   states, and success assembly are separate orchestration phases. Stale tests
   that called the removed private `_combine_results` method now use the public
   assembler boundary.
6. **Oversized static export service:** scan serialization, filtering, bundle
   construction, and manifest fragments moved to `StaticScanBundleExporter`.
   Live/static projection parity remains strict.
7. **Scattered frontend capability/presentation logic:** canonical query
   traversal, sanitization, capability resolution, preset filtering, and
   transition handling are isolated in pure policy plus a shared transition
   hook. ResultsTable delegates opportunity cells and evidence selection, has no
   JSON-stringified opportunity comparator, and the undocumented
   `resilience_pillars` alias is gone.

## Behavioral verification

Focused and adjacent suites were run throughout the red-green-refactor cycle.
Notable final-tree gates include:

- consolidated opportunity backend regression: **397 passed**;
- final orchestrator/assembler regression: **32 passed**;
- Setup Engine persistence/query adapter regression: **97 passed**;
- final live/static/table capability regression: **78 passed**;
- real FastAPI ASGI versus static export parity: green;
- complete frontend suite: **89 files, 624 tests passed** in 207.71 seconds;
- complete backend suite: **6,155 passed, 7 failed, 3 skipped, 21 warnings**
  in 657.77 seconds.

The seven backend failures are the unchanged environment gates:

- three protected theme-pipeline API integration cases receive HTTP 503 because
  server authentication is not configured in the local test environment;
- three failure-isolation load cases and one per-market load case reject the
  absent calibrated simulator profiles for AU/CA/CN/DE/IN/KR/MY/SG.

No feature, assembler, persistence, query, parity, schema, migration, or UI test
failed in the final run.

## Migration verification

Migration `20260823_0029` was exercised against disposable PostgreSQL 16 through
upgrade, downgrade to `20260821_0028`, and re-upgrade to head. The run verified:

- unrelated criteria and metadata keys are preserved;
- the recognized opportunity materialization marker moves to `metadata_json`;
- downgrade restores the marker before dropping the column;
- re-upgrade reaches head cleanly.

The disposable container was stopped and removed. No user or deployment
database was modified.

## Structural and static quality gates

Final reviewed file sizes:

- `backend/app/scanners/scan_orchestrator.py`: **810 lines**;
- `backend/app/services/static_site_export_service.py`: **879 lines**;
- `backend/tests/unit/test_daily_snapshot_service.py`: **849 lines**;
- `frontend/src/static/pages/StaticScanPage.test.jsx`: **910 lines**.

All four are below the 1,000-line review threshold. The extracted assembler,
static exporter, domain, summary, and frontend capability modules are focused
and independently tested.

Quality commands and results:

- changed Python files, Ruff `E4,E7,E9,F,I`: **all checks passed**;
- remediated backend boundaries, Ruff `C901,E9,F`: **all checks passed**;
- extracted frontend capability/presentation modules, ESLint complexity 20:
  **passed**;
- complete frontend ESLint: **0 errors, 4 existing warnings** outside this
  feature;
- production build: **passed, 2,497 modules transformed**;
- `git diff --check`: **clean**;
- private-key/token/credential pattern scan: **no match**;
- opportunity telemetry privacy inspection/tests: aggregate, symbol-free
  opportunity payload remains enforced.

Repository-wide C901 inspection still reports functions that already exceeded
the threshold on `origin/main`. The remediation did not create a new crossing:
the previously complex `scan_stock_multi` path is now clean; ResultsTable's
legacy virtual row is back to its baseline complexity; and Static Scan is below
its baseline complexity. Those unrelated baseline functions were not disguised
with exclusions or weakened lint rules.

## Final thermo-nuclear verdict

**Approved.** The implementation now has explicit ownership boundaries, one
canonical projection contract, one summary query abstraction, cohesive scan and
static collaborators, pure frontend capability policy, and no feature-specific
spaghetti growth in shared hooks or table rendering. No clear code-judo
opportunity remains that would materially simplify this feature without
expanding into unrelated baseline refactoring.
