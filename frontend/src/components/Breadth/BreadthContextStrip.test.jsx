import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { renderWithProviders } from '../../test/renderWithProviders';
import BreadthContextStrip from './BreadthContextStrip';
import { breadthMetricDefinitions } from './breadthMetricDefinitions';


const row = {
  advancing_count: 60,
  declining_count: 35,
  unchanged_count: 5,
  advance_decline_eligible_count: 100,
  new_high_52week_count: 8,
  new_low_52week_count: 2,
  high_low_52week_eligible_count: 80,
  t2108_count: 55,
  t2108_pct: 57.89,
  t2108_eligible_count: 95,
  atr_10x_extension_count: 3,
  atr_extension_eligible_count: 92,
  broad_universe_count: 110,
};


describe('BreadthContextStrip', () => {
  it('shows context values with their matching eligible denominators', () => {
    renderWithProviders(<BreadthContextStrip row={row} />);

    expect(screen.getByText('60 (60.0%)')).toBeInTheDocument();
    expect(screen.getByText('35 (35.0%)')).toBeInTheDocument();
    expect(screen.getByText('8 / 80')).toBeInTheDocument();
    expect(screen.getByText('2 / 80')).toBeInTheDocument();
    expect(screen.getByText('57.89% (55 / 95)')).toBeInTheDocument();
    expect(screen.getByText('3 / 92')).toBeInTheDocument();
    expect(screen.getByText('110')).toBeInTheDocument();
  });

  it('uses an em dash when a metric has no eligible stocks', () => {
    renderWithProviders(
      <BreadthContextStrip
        row={{ ...row, t2108_eligible_count: 0, t2108_pct: null }}
      />,
    );

    expect(screen.getByTestId('breadth-context-t2108_pct')).toHaveTextContent('—');
  });

  it('labels StockBee and screenshot-derived formulas explicitly', () => {
    expect(breadthMetricDefinitions.t2108_pct.formulaOrigin).toBe('StockBee');
    expect(breadthMetricDefinitions.atr_10x_extension_count.formulaOrigin).toBe(
      'Screenshot-derived',
    );
    expect(breadthMetricDefinitions.stocks_up_4pct.groupOrigin).toBe(
      'Screenshot grouping',
    );
    expect(breadthMetricDefinitions.stocks_up_4pct.formulaOrigin).toBe('StockBee');
  });
});
