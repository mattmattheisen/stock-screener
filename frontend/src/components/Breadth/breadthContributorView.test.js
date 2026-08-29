import { describe, expect, it } from 'vitest';
import { buildBreadthContributorView } from './breadthContributorView';

const document = {
  schema: 'breadth-contributors-v1',
  market: 'US',
  date: '2026-08-28',
  calculation_revision: 3,
  contributors: [
    {
      symbol: 'BBB', company_name: 'Beta', ibd_industry_group: 'No Group',
      daily_change_pct: -5, signals: { down_25pct_month: -30 },
    },
    {
      symbol: 'AAA', company_name: 'Alpha', ibd_industry_group: 'Banks',
      daily_change_pct: -4, signals: { down_25pct_month: -40 },
    },
    {
      symbol: 'CCC', company_name: 'Charlie', ibd_industry_group: 'Banks',
      daily_change_pct: null, signals: { down_25pct_month: -35 },
    },
    {
      symbol: 'UP', company_name: 'Up', ibd_industry_group: 'Software',
      daily_change_pct: 6, signals: { up_4pct: 6 },
    },
  ],
};

describe('buildBreadthContributorView', () => {
  it('filters one signal, sorts down values lowest first, and keeps No Group last', () => {
    const view = buildBreadthContributorView(document, 'stocks_down_25pct_month', 3);

    expect(view.stocks.map((row) => row.symbol)).toEqual(['AAA', 'CCC', 'BBB']);
    expect(view.groups.at(-1).name).toBe('No Group');
    expect(view.groups.reduce((sum, group) => sum + group.count, 0)).toBe(3);
    expect(view.groups[0].sharePct).toBeCloseTo((2 / 3) * 100);
  });

  it('rejects a document whose selected signal count differs from the cell', () => {
    expect(() => buildBreadthContributorView(document, 'stocks_up_4pct', 99))
      .toThrow('Contributor count does not match breadth history');
  });

  it('rejects unsupported metrics and malformed values', () => {
    expect(() => buildBreadthContributorView(document, 'ratio_5day', 1))
      .toThrow('does not support contributors');
    expect(() => buildBreadthContributorView({ ...document, calculation_revision: 2 }, 'stocks_up_4pct', 1))
      .toThrow('revision');
  });
});
