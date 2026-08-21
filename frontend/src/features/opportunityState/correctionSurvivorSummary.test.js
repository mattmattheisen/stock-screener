import { describe, expect, it } from 'vitest';

import { buildCorrectionSurvivorSummary } from './correctionSurvivorSummary';

const ALL_ZERO_COUNTS = {
  exit_risk: 0,
  deteriorating: 0,
  event_risk: 0,
  extended: 0,
  data_limited: 0,
  setup_ready: 0,
  watch: 0,
};

describe('buildCorrectionSurvivorSummary', () => {
  // Catches a second, browser-owned survivor filter or resilience sort drifting
  // away from the exported preset that selected and ordered these rows.
  it('summarizes already-selected persisted rows without filtering or reordering them', () => {
    const rows = [
      {
        symbol: 'MANIFEST-FIRST',
        correction_survivor: false,
        resilience_score: 10,
        action_state: 'watch',
      },
      {
        symbol: 'MANIFEST-SECOND',
        correction_survivor: true,
        resilience_score: 99,
        action_state: 'setup_ready',
      },
    ];

    const summary = buildCorrectionSurvivorSummary(rows, { complete: true });

    expect(summary).toMatchObject({
      available: true,
      complete: true,
      count: 2,
      counts_by_action_state: {
        ...ALL_ZERO_COUNTS,
        setup_ready: 1,
        watch: 1,
      },
    });
    expect(summary.rows.map((row) => row.symbol)).toEqual([
      'MANIFEST-FIRST',
      'MANIFEST-SECOND',
    ]);
  });

  // Catches an incomplete static bundle being presented as a trustworthy zero.
  it('marks a partial static chunk load incomplete', () => {
    expect(buildCorrectionSurvivorSummary([
      { symbol: 'PARTIAL', action_state: 'watch' },
    ], { complete: false })).toEqual({
      available: false,
      complete: false,
      count: 0,
      counts_by_action_state: ALL_ZERO_COUNTS,
      rows: [],
    });
  });

  // Catches unbounded daily payloads while preserving counts across the full membership.
  it('limits displayed rows to twenty while counting every selected row', () => {
    const rows = Array.from({ length: 21 }, (_, index) => ({
      symbol: `ROW-${index + 1}`,
      action_state: 'watch',
    }));

    const summary = buildCorrectionSurvivorSummary(rows, { complete: true });

    expect(summary.count).toBe(21);
    expect(summary.counts_by_action_state.watch).toBe(21);
    expect(summary.rows).toHaveLength(20);
    expect(summary.rows.at(-1).symbol).toBe('ROW-20');
  });
});
