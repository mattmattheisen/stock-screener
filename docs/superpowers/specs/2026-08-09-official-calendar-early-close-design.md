# Official Calendar Early-Close Preservation

## Problem

Reviewed official calendar input records full-day exchange closures, but it does
not record exceptional session close times. Official manifests therefore omit
`close_exceptions`. When a calendar provider cannot answer for a verified date,
`MarketCalendarService.last_completed_trading_day()` falls back to the regular
market close. On an early-close session this can delay recognition of the
completed session and cause a static export to publish stale data.

## Design

Each reviewed market may declare `close_exceptions` as a year-keyed mapping of
ISO session dates to exchange-local ISO times. The field is optional so existing
reviewed input and callers remain compatible; an omitted year or field means no
reviewed exceptional closes for that scope.

`ReviewedCalendarInput` parses the values into immutable
`Mapping[date, time]` records and exposes a `close_exceptions_for(market, year)`
accessor. Validation rejects dates outside the declared year, dates also listed
as closures, and invalid ISO times.

The checked-in production input will contain every verified exceptional close
identified for each official market year. Calendar generation passes those
records through `CalendarManifestGenerator.import_official_closures()`, which
also verifies that every exceptional-close date is a generated session before
writing the existing manifest `close_exceptions` field. Provisional generation
is unchanged.

## Data Flow

1. Operators transcribe official closures and exceptional close times into the
   reviewed JSON using exchange-local time.
2. The reviewed-input loader validates and normalizes those facts.
3. The deterministic builder creates official sessions and passes exceptional
   closes to the manifest generator.
4. Checked-in official manifests retain the exceptional close times.
5. `MarketCalendarService` uses the manifest exception before consulting the
   provider, preserving correct behavior when the provider is unavailable.

## Compatibility and Errors

The reviewed JSON remains at schema version 1 because the new field is optional
and additive. Existing `import_official_year()` and
`import_official_closures()` callers keep their current behavior through an
optional empty mapping. Invalid reviewed facts fail calendar generation with a
specific validation error; warnings and calendar coverage policy do not change.

## Testing

- Loader tests cover parsing, omission compatibility, invalid dates and times,
  closure conflicts, and cross-year entries.
- Generator tests first reproduce the missing `close_exceptions` output, then
  cover propagation and rejection of non-session dates.
- Builder drift tests verify regenerated production manifests.
- Market-calendar regression coverage verifies that a provider-unavailable run
  recognizes a reviewed early-close session after its close buffer.
- Focused calendar suites, manifest drift checks, lint, and the complete backend
  suite provide final verification.
