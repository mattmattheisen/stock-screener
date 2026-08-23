import { describe, expect, it } from 'vitest';
import { createEmptyExpression } from './filterExpressionModel';
import {
  presetRequiresOpportunityState,
  queryRequiresOpportunityState,
  sanitizeQueryForOpportunityCapability,
} from './opportunityCapabilityPolicy';

describe('opportunity capability policy', () => {
  it('does not infer capability requirements from a preset display name', () => {
    expect(presetRequiresOpportunityState({
      name: 'Correction Survivors',
      filters: { schema_version: 2, expression: createEmptyExpression() },
      sort_by: 'composite_score',
    })).toBe(false);
  });

  it('normalizes legacy preset filters before checking semantics', () => {
    expect(presetRequiresOpportunityState({
      name: 'My setup',
      filters: { correctionSurvivor: true },
      sort_by: 'composite_score',
    })).toBe(true);
  });

  it('detects normalized expression and sort requirements', () => {
    expect(queryRequiresOpportunityState({
      expression: createEmptyExpression([
        { kind: 'categorical', field: 'action_state', values: ['watch'] },
      ]),
      sortBy: 'composite_score',
    })).toBe(true);
    expect(queryRequiresOpportunityState({
      expression: createEmptyExpression(),
      sortBy: 'resilience_score',
    })).toBe(true);
  });

  it('sanitizes unsupported filter and sort atomically', () => {
    const expression = createEmptyExpression([
      { kind: 'range', field: 'price', min: 10, max: null },
      { kind: 'boolean', field: 'correction_survivor', value: true },
    ]);
    expression.groups = [
      {
        id: 'mixed',
        name: 'Mixed',
        match: 'all',
        enabled: true,
        conditions: [
          { kind: 'range', field: 'resilience_score', min: 80, max: null },
          { kind: 'categorical', field: 'rating', values: ['Buy'] },
        ],
      },
      {
        id: 'opportunity-only',
        name: 'Opportunity only',
        match: 'all',
        enabled: true,
        conditions: [
          { kind: 'categorical', field: 'action_state', values: ['watch'] },
        ],
      },
      {
        id: 'disabled-empty',
        name: 'Disabled empty',
        match: 'any',
        enabled: false,
        conditions: [],
      },
    ];

    expect(sanitizeQueryForOpportunityCapability({
      expression,
      sortBy: 'resilience_score',
      sortOrder: 'asc',
    }, false)).toEqual({
      expression: {
        expression_version: 1,
        required: {
          id: 'required',
          name: 'Always require',
          match: 'all',
          enabled: true,
          conditions: [
            { kind: 'range', field: 'price', min: 10, max: null },
          ],
        },
        group_join: 'any',
        groups: [
          {
            id: 'mixed',
            name: 'Mixed',
            match: 'all',
            enabled: true,
            conditions: [
              { kind: 'categorical', field: 'rating', values: ['Buy'] },
            ],
          },
          {
            id: 'disabled-empty',
            name: 'Disabled empty',
            match: 'any',
            enabled: false,
            conditions: [],
          },
        ],
      },
      sortBy: 'composite_score',
      sortOrder: 'desc',
    });
  });
});
