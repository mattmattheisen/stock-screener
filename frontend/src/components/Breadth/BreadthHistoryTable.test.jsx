import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import BreadthHistoryTable from './BreadthHistoryTable';


const row = {
  date: '2026-08-21',
  stocks_up_4pct: 10,
  stocks_down_4pct: 5,
  ratio_5day: 2,
  ratio_10day: 1.5,
  stocks_up_25pct_quarter: 8,
  stocks_down_25pct_quarter: 4,
  stocks_up_25pct_month: 7,
  stocks_down_25pct_month: 3,
  stocks_up_50pct_month: 2,
  stocks_down_50pct_month: 1,
  stocks_up_13pct_34days: 9,
  stocks_down_13pct_34days: 6,
  atr_10x_extension_count: 3,
  t2108_pct: 57.89,
  broad_universe_count: 110,
};


describe('BreadthHistoryTable', () => {
  it('renders grouped primary, secondary, and context headers', () => {
    render(<BreadthHistoryTable rows={[row]} />);

    expect(screen.getByText('Primary Breadth Indicators')).toBeInTheDocument();
    expect(screen.getByText('Secondary Breadth Indicators')).toBeInTheDocument();
    expect(screen.getByText('Context')).toBeInTheDocument();
    expect(screen.getByText('10x ATR')).toBeInTheDocument();
    expect(screen.getByText('T2108')).toBeInTheDocument();
    expect(screen.getByText('Broad Universe')).toBeInTheDocument();
    expect(screen.getByText('2.00')).toBeInTheDocument();
    expect(screen.getByText('57.89%')).toBeInTheDocument();
  });

  it('marks paired cells and exposes formula tooltips accessibly', () => {
    render(<BreadthHistoryTable rows={[row]} />);

    expect(screen.getAllByTestId('breadth-up-cell').length).toBeGreaterThan(0);
    expect(screen.getAllByTestId('breadth-down-cell').length).toBeGreaterThan(0);
    expect(
      screen.getByRole('button', { name: /stocks up 4%\+ formula details/i }),
    ).toBeInTheDocument();
    expect(screen.getByTestId('breadth-history-scroll')).toHaveStyle({
      overflowX: 'auto',
    });
  });
});
