import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { buildDefaultScanFilters } from '../defaultFilters';
import { createEmptyExpression } from '../filterExpressionModel';
import { legacyFiltersToExpression } from '../legacyFilterExpression';
import { useScanFilterPresets } from './useScanFilterPresets';

function setup(overrides = {}) {
  const applyQuery = vi.fn();
  const createPresetAsync = vi.fn().mockResolvedValue({ id: 'preset-2' });
  const updatePresetAsync = vi.fn().mockResolvedValue({});
  const deletePreset = vi.fn();

  const props = {
    presets: [
      {
        id: 'preset-1',
        name: 'Momentum',
        filters: { ...buildDefaultScanFilters(), symbolSearch: 'NVDA' },
        sort_by: 'composite_score',
        sort_order: 'desc',
      },
      {
        id: 'preset-2',
        name: 'Growth',
        description: 'growth profile',
        filters: { ...buildDefaultScanFilters(), symbolSearch: 'AAPL' },
        sort_by: 'rs_rating',
        sort_order: 'asc',
      },
    ],
    createPresetAsync,
    updatePresetAsync,
    deletePreset,
    expression: legacyFiltersToExpression(buildDefaultScanFilters()),
    sortBy: 'composite_score',
    sortOrder: 'desc',
    applyQuery,
    ...overrides,
  };

  const hook = renderHook((currentProps) => useScanFilterPresets(currentProps), {
    initialProps: props,
  });

  return {
    hook,
    props,
    applyQuery,
    createPresetAsync,
    updatePresetAsync,
    deletePreset,
  };
}

describe('useScanFilterPresets', () => {
  it('hides and blocks the Correction Survivors preset without API capability', () => {
    const { hook, applyQuery } = setup({
      opportunityStateAvailable: false,
      presets: [
        {
          id: 'correction-survivors-live',
          name: 'Correction Survivors',
          filters: { ...buildDefaultScanFilters(), correctionSurvivor: true },
          sort_by: 'resilience_score',
          sort_order: 'desc',
        },
        {
          id: 'momentum',
          name: 'Momentum',
          filters: buildDefaultScanFilters(),
          sort_by: 'composite_score',
          sort_order: 'desc',
        },
      ],
    });

    expect(hook.result.current.availablePresets.map(({ name }) => name)).toEqual([
      'Momentum',
    ]);

    act(() => hook.result.current.handleLoadPreset('correction-survivors-live'));
    expect(applyQuery).not.toHaveBeenCalled();
  });

  it('exposes the Correction Survivors preset for a capable scan', () => {
    const { hook } = setup({
      opportunityStateAvailable: true,
      presets: [{
        id: 'correction-survivors-live',
        name: 'Correction Survivors',
        filters: { ...buildDefaultScanFilters(), correctionSurvivor: true },
        sort_by: 'resilience_score',
        sort_order: 'desc',
      }],
    });

    expect(hook.result.current.availablePresets).toHaveLength(1);
  });

  it('sanitizes manually authored opportunity query state once when capability is lost', () => {
    const expression = createEmptyExpression([
      { kind: 'range', field: 'price', min: 10, max: null },
      { kind: 'boolean', field: 'correction_survivor', value: true },
    ]);
    expression.group_join = 'all';
    expression.groups = [
      {
        id: 'mixed',
        name: 'Mixed setup',
        match: 'all',
        enabled: true,
        conditions: [
          { kind: 'range', field: 'resilience_score', min: 80, max: null },
          { kind: 'categorical', field: 'rating', values: ['Buy'], mode: 'include' },
        ],
      },
      {
        id: 'opportunity-only',
        name: 'Opportunity only',
        match: 'any',
        enabled: true,
        conditions: [
          {
            kind: 'categorical',
            field: 'action_state',
            values: ['setup_ready'],
            mode: 'include',
          },
        ],
      },
      {
        id: 'disabled-empty',
        name: 'Disabled empty setup',
        match: 'any',
        enabled: false,
        conditions: [],
      },
      {
        id: 'unrelated',
        name: 'Unrelated setup',
        match: 'all',
        enabled: false,
        conditions: [
          { kind: 'boolean', field: 'vcp_detected', value: true },
        ],
      },
    ];
    const { hook, props, applyQuery } = setup({
      expression,
      sortBy: 'resilience_score',
      sortOrder: 'asc',
      opportunityStateAvailable: true,
    });

    act(() => {
      hook.rerender({
        ...props,
        expression,
        sortBy: 'resilience_score',
        sortOrder: 'asc',
        opportunityStateAvailable: false,
      });
    });

    const sanitizedExpression = {
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
      group_join: 'all',
      groups: [
        {
          id: 'mixed',
          name: 'Mixed setup',
          match: 'all',
          enabled: true,
          conditions: [
            { kind: 'categorical', field: 'rating', values: ['Buy'], mode: 'include' },
          ],
        },
        {
          id: 'disabled-empty',
          name: 'Disabled empty setup',
          match: 'any',
          enabled: false,
          conditions: [],
        },
        {
          id: 'unrelated',
          name: 'Unrelated setup',
          match: 'all',
          enabled: false,
          conditions: [
            { kind: 'boolean', field: 'vcp_detected', value: true },
          ],
        },
      ],
    };
    expect(applyQuery).toHaveBeenCalledTimes(1);
    expect(applyQuery).toHaveBeenCalledWith({
      expression: sanitizedExpression,
      sortBy: 'composite_score',
      sortOrder: 'desc',
    });

    act(() => {
      hook.rerender({
        ...props,
        expression: sanitizedExpression,
        sortBy: 'composite_score',
        sortOrder: 'desc',
        opportunityStateAvailable: false,
      });
    });
    expect(applyQuery).toHaveBeenCalledTimes(1);
  });

  it('does not sanitize opportunity query state while capability remains true', () => {
    const expression = createEmptyExpression([
      { kind: 'boolean', field: 'correction_survivor', value: true },
    ]);
    const { applyQuery } = setup({
      expression,
      sortBy: 'resilience_score',
      sortOrder: 'desc',
      opportunityStateAvailable: true,
    });

    expect(applyQuery).not.toHaveBeenCalled();
  });

  it('loads a preset as one canonical filter + sort transition', () => {
    const { hook, applyQuery } = setup();

    act(() => {
      hook.result.current.handleLoadPreset('preset-1');
    });

    expect(applyQuery).toHaveBeenCalledWith(expect.objectContaining({
      expression: expect.objectContaining({
        expression_version: 1,
        required: expect.objectContaining({
          conditions: expect.arrayContaining([
            expect.objectContaining({ kind: 'text', pattern: 'NVDA' }),
          ]),
        }),
      }),
      sortBy: 'composite_score',
      sortOrder: 'desc',
    }));
  });

  it('loads the Correction Survivors live preset with survivor semantics', () => {
    const { hook, applyQuery } = setup({
      opportunityStateAvailable: true,
      presets: [{
        id: 'correction-survivors-live',
        name: 'Correction Survivors',
        filters: { ...buildDefaultScanFilters(), correctionSurvivor: true },
        sort_by: 'resilience_score',
        sort_order: 'desc',
      }],
    });

    act(() => {
      hook.result.current.handleLoadPreset('correction-survivors-live');
    });

    expect(applyQuery).toHaveBeenCalledWith({
      expression: expect.objectContaining({
        required: expect.objectContaining({
          conditions: [
            expect.objectContaining({
              kind: 'boolean',
              field: 'correction_survivor',
              value: true,
            }),
          ],
        }),
      }),
      sortBy: 'resilience_score',
      sortOrder: 'desc',
    });
  });

  it('omits static-only legacy aliases when loading a live preset', () => {
    const { hook, applyQuery } = setup({
      presets: [{
        id: 'legacy-static-alias',
        name: 'Legacy performance',
        filters: {
          ...buildDefaultScanFilters(),
          pctDay: { min: 5, max: null },
          pctWeek: { min: 10, max: null },
          pctMonth: { min: 20, max: null },
          symbolSearch: 'NVDA',
        },
        sort_by: 'composite_score',
        sort_order: 'desc',
      }],
    });

    act(() => {
      hook.result.current.handleLoadPreset('legacy-static-alias');
    });

    const { conditions } = applyQuery.mock.calls[0][0].expression.required;
    expect(conditions).toContainEqual(
      expect.objectContaining({ kind: 'text', pattern: 'NVDA' }),
    );
    expect(conditions.map(({ field }) => field)).not.toEqual(
      expect.arrayContaining(['pct_day', 'pct_week', 'pct_month']),
    );
  });

  it('tracks unsaved changes after preset load', () => {
    const { hook, props } = setup();

    act(() => {
      hook.result.current.handleLoadPreset('preset-1');
    });
    hook.rerender({
      ...props,
      expression: legacyFiltersToExpression({
        ...buildDefaultScanFilters(),
        symbolSearch: 'NVDA',
      }),
    });
    expect(hook.result.current.hasUnsavedChanges()).toBe(false);

    hook.rerender({
      ...props,
      expression: legacyFiltersToExpression({
        ...buildDefaultScanFilters(),
        symbolSearch: 'AAPL',
      }),
    });

    expect(hook.result.current.hasUnsavedChanges()).toBe(true);
  });

  it('creates a new preset from save dialog', async () => {
    const { hook, createPresetAsync } = setup();

    act(() => {
      hook.result.current.handleOpenSaveDialog();
    });

    await act(async () => {
      await hook.result.current.handleSaveDialogSave('My preset', 'desc');
    });

    expect(createPresetAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        name: 'My preset',
        description: 'desc',
      })
    );
  });

  it('stores one canonical V2 expression using the current quick-filter draft', async () => {
    const currentFilters = { ...buildDefaultScanFilters(), symbolSearch: 'AAPL' };
    const { hook, createPresetAsync } = setup({
      expression: legacyFiltersToExpression(currentFilters),
    });

    act(() => {
      hook.result.current.handleOpenSaveDialog();
    });
    await act(async () => {
      await hook.result.current.handleSaveDialogSave('Current draft', '');
    });

    const payload = createPresetAsync.mock.calls[0][0].filters;
    expect(payload).toEqual({
      schema_version: 2,
      expression: expect.objectContaining({
        required: expect.objectContaining({
          conditions: expect.arrayContaining([
            expect.objectContaining({ kind: 'text', pattern: 'AAPL' }),
          ]),
        }),
      }),
    });
    expect(payload).not.toHaveProperty('legacy_filters');
  });

  it('loads V2 presets from the expression even when stale legacy filters exist', () => {
    const canonicalFilters = { ...buildDefaultScanFilters(), symbolSearch: 'GOOGL' };
    const staleFilters = { ...buildDefaultScanFilters(), symbolSearch: 'STALE' };
    const { hook, applyQuery } = setup({
      expression: legacyFiltersToExpression(buildDefaultScanFilters()),
      presets: [
        {
          id: 'preset-v2',
          name: 'Canonical',
          filters: {
            schema_version: 2,
            expression: legacyFiltersToExpression(canonicalFilters),
            legacy_filters: staleFilters,
          },
          sort_by: 'rs_rating',
          sort_order: 'desc',
        },
      ],
    });

    act(() => {
      hook.result.current.handleLoadPreset('preset-v2');
    });

    expect(applyQuery).toHaveBeenCalledWith(expect.objectContaining({
      expression: expect.objectContaining({
        required: expect.objectContaining({
          conditions: expect.arrayContaining([
            expect.objectContaining({ kind: 'text', pattern: 'GOOGL' }),
          ]),
        }),
      }),
    }));
  });

  it('renames the preset selected in the rename dialog, not the active preset', async () => {
    const { hook, updatePresetAsync } = setup();

    act(() => {
      hook.result.current.handleLoadPreset('preset-1');
      hook.result.current.handleRenamePreset('preset-2');
    });

    await act(async () => {
      await hook.result.current.handleSaveDialogSave('Renamed Growth', 'updated');
    });

    expect(updatePresetAsync).toHaveBeenCalledWith({
      presetId: 'preset-2',
      updates: { name: 'Renamed Growth', description: 'updated' },
    });
  });
});
