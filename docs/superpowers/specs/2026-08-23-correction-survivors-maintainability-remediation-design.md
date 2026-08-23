# Correction Survivors Maintainability Remediation Design

**Status:** Implemented

**Date:** 2026-08-23

## Context

The correction-survivors feature is behaviorally complete, but the final
maintainability review found that it concentrated too much policy, persistence,
query, and presentation work in existing large modules. The implementation also
placed backend-owned materialization metadata in user scan criteria, repeated
the same action-state contract in several modules, queried Daily Snapshot action
counts one state at a time, and made capability transitions an implicit concern
of the frontend preset hook.

This remediation preserves the shipped opportunity-state policy, live/static
parity, API contract, and legacy-snapshot behavior while introducing explicit
boundaries around the new feature.

## Goals

- Give each opportunity-state module one cohesive responsibility.
- Establish one canonical typed projection contract and remove duplicate key
  lists and validators.
- Keep user-authored scan criteria free of internal materialization metadata.
- Resolve live capability from explicit scan/run metadata without inspecting
  rows or reflecting over ORM objects.
- Replace per-action-state count queries with one grouped aggregation shared by
  Daily Snapshot and telemetry.
- Extract opportunity assembly and static bundle export from files that crossed
  the repository's 1,000-line review threshold.
- Make frontend capability handling pure, explicit, and independent of preset
  display names.
- Reduce conditional rendering and comparison logic in the Scan results table.
- Preserve every supported static and live behavior and keep legacy data
  unavailable rather than misleadingly empty.

## Non-Goals

- Do not change survivor eligibility, scoring weights, action precedence, or
  public response field names.
- Do not implement the deferred cross-run Setup Follow-Through study.
- Do not introduce a general plugin or feature-capability framework.
- Do not backfill opportunity projections into historical scan rows.
- Do not change the static manifest capability contract.
- Do not redesign the table, Daily Snapshot, watchlist, or evidence drawer UI.

## Considered Approaches

### 1. Extract files only

Move code into smaller modules while retaining criteria-based metadata,
per-state queries, and frontend effect-driven sanitization. This reduces file
sizes but leaves the correctness and ownership problems intact.

### 2. Build a general capability framework

Create a registry for every present and future materialized scan feature. This
could eventually be useful, but no second capability currently requires it. It
would expand the change well beyond the reviewed feature.

### 3. Targeted boundary remediation

Create narrow opportunity-state domain, query, assembly, persistence, and UI
boundaries. Store direct-scan materialization metadata in a dedicated JSON
column and keep FeatureRun configuration authoritative for snapshot-backed
scans. This resolves every finding while minimizing unrelated change. This is
the selected approach.

## Backend Domain Design

The current `domain/scanning/opportunity_state.py` module becomes an
`opportunity_state` package with four responsibilities:

- `model.py` owns `ActionState`, availability types, grouped input evidence,
  score pillars, and the immutable assessment result.
- `policy.py` owns current-snapshot eligibility, score calculation, check
  generation, and action-state precedence. It is pure and has no serializers,
  persistence knowledge, or stewardship history.
- `projection.py` owns the versioned compact projection, strict parsing,
  coherence validation, and serialization. Projection keys are declared once
  here and reused by API schemas and adapters.
- `stewardship.py` owns the cross-run watchlist overlay. It accepts a completed
  current-snapshot assessment plus stewardship status and returns the effective
  action state without changing the underlying score or eligibility result.

`OpportunityInputs` is replaced with cohesive evidence objects for provenance,
leadership, trend, structure, tradability, and risk. Availability is represented
with typed evidence state rather than a value plus a parallel boolean. The
unused `stewardship_status` input and production-inactive
`prior_run_required`/`deterioration_confirmed` snapshot modes are removed.

The application service normalizes scanner and Setup Engine values into these
evidence objects once, invokes the policy once, and serializes the final result
once. It may add typed metric values before serialization; it must not mutate a
serialized nested dictionary after evaluation.

Pydantic response schemas remain the public validation boundary, but their
enums, field definitions, and coherence checks delegate to or adapt the
canonical domain projection. They do not maintain independent lists of allowed
keys or states.

## Scan Assembly and Static Export

`ScanOrchestrator` continues to coordinate one scan, but no longer assembles
every result itself. A `ScanResultAssembler` receives scanner outputs and
supporting data, calculates the composite result, invokes an injected
opportunity-state projector, and returns the persistable result. The
orchestrator is responsible only for orchestration, failure handling, and
collecting assembled results.

The static export service keeps export coordination and destination ownership.
A `StaticScanBundleExporter` owns scan-row serialization, scan-filter
application, bundle construction, and scan manifest fragments. The exporter
uses the same strict opportunity projection codec as the live path.

These extractions must bring both production files below 1,000 lines and leave
the extracted collaborators independently testable. The two review-identified
test files are split by feature concern so they also remain below 1,000 lines.

## Materialization Metadata

The `scans` table gains a nullable `metadata_json` JSON column. It is internal
scan metadata and is not accepted as user criteria or exposed as criteria in
the API. Direct and compiled scans write:

```json
{
  "materialization_versions": {
    "opportunity_state": 1
  }
}
```

Snapshot-backed scans continue to derive capability from their authoritative
`FeatureRun.config_json`. An explicit resolver receives typed values:

```text
resolve_opportunity_state_capability(
    feature_run_id,
    feature_run_config,
    scan_metadata,
) -> bool
```

When `feature_run_id` is present, the run configuration is authoritative. For a
direct scan, `scan_metadata` is authoritative. The resolver never receives an
arbitrary ORM object and never guesses attribute names or inspects result rows.

Migration `0029` adds the column and moves the recognized
`materialization_versions.opportunity_state` marker from existing scan criteria
into metadata without changing other criteria keys. The downgrade restores the
recognized marker for compatibility before dropping the column. New writes
never add the internal key to criteria.

Legacy scans with neither authoritative marker remain incapable even if a row
happens to contain opportunity fields. Capable scans remain capable when their
current result set is empty.

## Opportunity Summary Query

A dedicated `OpportunityStateSummaryReader` returns one value object containing
the correction-survivor total and grouped action-state counts. Its repository
implementation performs one aggregate query using conditional aggregation or a
grouped subquery.

Daily Snapshot performs at most:

1. one query for its ordered survivor rows, and
2. one aggregate query for survivor and action-state counts.

Telemetry consumes the same summary reader or its returned value. Generic
telemetry code no longer owns feature-specific SQL, dynamic model imports, or a
separate database-session lifecycle for this aggregation. Unknown action-state
values are rejected or recorded as an explicit integrity warning; they are not
silently folded into a known state.

## Frontend Capability Policy

A pure opportunity capability policy module owns:

- canonical query normalization,
- `queryRequiresOpportunityState(query)`, and
- `sanitizeQueryForOpportunityCapability(query, available)`.

The policy traverses only the documented canonical filter expression. It does
not recursively search arbitrary objects and never uses the preset display name
as identity. A user preset named “Correction Survivors” is treated according to
its expression, exactly like any other user preset.

`useScanFilterPresets` returns to preset fetching, selection, and CRUD state.
The Scan controller applies the pure sanitizer when a scan or capability
changes and issues the sanitized query when necessary. Capability loss removes
unsupported opportunity predicates and sorts atomically; it also clears an
active predefined opportunity preset identity. Capability restoration does not
reapply previously removed filters.

Static pages keep their manifest-owned capability behavior and use the same
pure query policy without changing the manifest contract.

## Results Presentation

Opportunity-specific columns, badges, and drawer selection are extracted from
`ResultsTable` behind a focused column/presentation boundary. The table no
longer deep-compares `opportunity_state` with `JSON.stringify` inside a manually
maintained row comparator. Stable upstream row references and ordinary React
memoization are preferred; if a comparator remains necessary, it is generated
from the active column accessors rather than hand-enumerating row properties.

The evidence drawer accepts only the canonical `score_pillars` field. The
undocumented `resilience_pillars` alias is removed. Legacy normalization, when
needed, belongs in a versioned API/static adapter rather than a shared UI
component; no current supported payload requires that alias.

Existing rules remain unchanged: refreshed evidence updates an open drawer,
removed rows or lost capability close it, and keyboard behavior remains
available on Scan, Daily Snapshot, and watchlist surfaces.

## Data Flow

For newly computed rows:

1. Producers gather point-in-time scanner, Setup Engine, liquidity, event, and
   provenance evidence.
2. The application service normalizes that data into typed evidence.
3. The pure policy returns an immutable assessment.
4. The projection codec validates and serializes it once.
5. `ScanResultAssembler` persists the flat query fields and compact projection.
6. Scan or FeatureRun metadata records materialization capability.
7. Live APIs and static export validate and deliver the same projection.
8. React capability policy sanitizes queries, and shared presentation renders
   the delivered evidence without recalculating policy.

For summary consumers, the repository aggregates persisted flat fields once and
returns a typed summary to both Daily Snapshot and telemetry.

## Error and Legacy Handling

- Missing current evidence continues to produce the existing tri-state/data-
  limited outcomes; refactoring must not turn unknown into false.
- Malformed present projections fail strict parsing. A completely absent
  projection remains the only legacy all-null case.
- Metadata migration preserves unrelated user criteria and unrelated metadata.
- A linked FeatureRun with no supported marker remains incapable even if direct
  scan metadata is present, preventing ambiguous ownership.
- Capability loss sanitizes unsupported frontend query state before issuing the
  replacement request, so legacy runs render “unavailable,” not a misleading
  zero-result opportunity view.
- Static export fails its current validation boundary when a projection is
  malformed; it does not repair or infer one in the browser.

## Testing Strategy

Implementation follows red-green-refactor in review-severity order.

1. Add contract tests for grouped evidence, canonical projection round trips,
   strict malformed-payload rejection, and removal of inactive policy modes.
2. Add persistence tests proving direct-scan capability lives in
   `metadata_json`, criteria remain unchanged, FeatureRun precedence is
   explicit, and migration upgrade/downgrade preserves unrelated values.
3. Add query-count/repository tests proving one summary aggregate serves Daily
   Snapshot and telemetry, plus the existing survivor-row query.
4. Add characterization tests around the extracted scan assembler and static
   bundle exporter before moving logic.
5. Add frontend regressions for user presets sharing the predefined display
   name, capability loss with active filters/sorts, canonical-expression-only
   traversal, and static/live behavior parity.
6. Add ResultsTable and drawer tests proving updates, removals, keyboard access,
   and canonical `score_pillars` behavior without the compatibility alias.
7. Split oversized tests without changing assertions, then run all focused and
   adjacent suites.

Final verification includes the complete backend and frontend suites, migration
upgrade/downgrade/re-upgrade against PostgreSQL where available, frontend lint
and production build, changed-file Ruff checks, file-size/complexity review,
privacy/diff review, and a final thermo-nuclear maintainability re-review. The
known environment-gated backend failures are reported separately and must not
mask new failures.

## Acceptance Criteria

- All seven maintainability findings are resolved without changing the public
  opportunity-state policy or supported UI behavior.
- No new internal materialization metadata is stored in scan criteria.
- Capability is explicit, backend-owned, page-independent, and stable for empty
  capable scans and legacy incapable scans.
- Daily Snapshot action totals no longer execute one query per state.
- Opportunity projection keys and action states have one backend source of
  truth.
- The orchestrator, static export service, and identified test files are below
  1,000 lines after extraction/splitting.
- Frontend preset capability logic has no display-name heuristic or arbitrary
  recursive object traversal.
- ResultsTable has no JSON-stringified opportunity comparator and does not grow
  another feature-specific render branch.
- The undocumented `resilience_pillars` UI alias is absent.
- Focused, parity, full-suite, lint, build, migration, and maintainability
  verification provide no new unexplained failures.
