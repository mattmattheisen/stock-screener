import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '../../test/renderWithProviders';
import CorrectionSurvivorsPanel from './CorrectionSurvivorsPanel';

const counts = {
  exit_risk: 0,
  deteriorating: 0,
  event_risk: 0,
  extended: 0,
  data_limited: 0,
  setup_ready: 1,
  watch: 1,
};

const rows = [
  {
    symbol: 'FIRST',
    company_name: 'First Resilient Corp',
    resilience_score: 91.2,
    action_state: 'setup_ready',
    opportunity_state: {
      benchmark_symbol: 'SPY',
      passed_checks: ['leadership_gate'],
      failed_checks: [],
      warnings: [],
      action_reasons: ['persisted evidence only'],
    },
  },
  {
    symbol: 'SECOND',
    company_name: 'Second Resilient Corp',
    resilience_score: 84,
    action_state: 'watch',
    opportunity_state: {},
  },
];

const completeSummary = {
  available: true,
  complete: true,
  count: 2,
  counts_by_action_state: counts,
  rows,
};

describe('CorrectionSurvivorsPanel', () => {
  // Catches state-count omissions, order drift, the wrong score field, or posture details being dropped.
  it('renders total, all state counts, persisted row order, resilience score, and posture', () => {
    renderWithProviders(
      <CorrectionSurvivorsPanel
        summary={completeSummary}
        posture={{ stance: 'Confirmed Uptrend', date: '2026-08-21', benchmark_symbol: 'SPY' }}
      />,
    );

    const panel = screen.getByTestId('correction-survivors-panel');
    expect(within(panel).getByText('Total survivors: 2')).toBeInTheDocument();
    expect(within(panel).getByText('Exit Risk: 0')).toBeInTheDocument();
    expect(within(panel).getByText('Deteriorating: 0')).toBeInTheDocument();
    expect(within(panel).getByText('Event Risk: 0')).toBeInTheDocument();
    expect(within(panel).getByText('Extended: 0')).toBeInTheDocument();
    expect(within(panel).getByText('Data Limited: 0')).toBeInTheDocument();
    expect(within(panel).getByText('Setup Ready: 1')).toBeInTheDocument();
    expect(within(panel).getByText('Watch: 1')).toBeInTheDocument();
    expect(within(panel).getByText('Confirmed Uptrend')).toBeInTheDocument();
    expect(within(panel).getByText('2026-08-21 · SPY')).toBeInTheDocument();
    expect(within(panel).getByText('91.2')).toBeInTheDocument();

    const tableRows = within(panel).getAllByRole('row').slice(1);
    expect(tableRows[0]).toHaveTextContent('FIRST');
    expect(tableRows[1]).toHaveTextContent('SECOND');
  });

  // Catches chart coupling or evidence reconstruction in the daily panel.
  it('opens the shared drawer from the action badge using persisted evidence', async () => {
    renderWithProviders(
      <CorrectionSurvivorsPanel summary={completeSummary} posture={null} />,
    );

    expect(screen.getByText('Market posture unavailable')).toBeInTheDocument();
    expect(screen.getByText('FIRST')).toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByText('Setup Ready'));

    expect(await screen.findByRole('heading', { name: 'Opportunity evidence' })).toBeInTheDocument();
    expect(screen.getByText('Leadership gate')).toBeInTheDocument();
    expect(screen.getByText('persisted evidence only')).toBeInTheDocument();
  });

  // Catches unavailable data being mislabeled as a valid no-survivor result.
  it('distinguishes incomplete data from a complete zero result', () => {
    const { rerender } = renderWithProviders(
      <CorrectionSurvivorsPanel
        summary={{ available: false, complete: false, count: 0, counts_by_action_state: {}, rows: [] }}
        posture={null}
      />,
    );

    expect(screen.getByText('Survivor data incomplete')).toBeInTheDocument();
    expect(screen.queryByText('No correction survivors in this snapshot.')).not.toBeInTheDocument();

    rerender(
      <CorrectionSurvivorsPanel
        summary={{
          available: true,
          complete: true,
          count: 0,
          counts_by_action_state: Object.fromEntries(Object.keys(counts).map((state) => [state, 0])),
          rows: [],
        }}
        posture={null}
      />,
    );

    expect(screen.getByText('No correction survivors in this snapshot.')).toBeInTheDocument();
    expect(screen.queryByText('Survivor data incomplete')).not.toBeInTheDocument();
  });

  // Catches action-badge clicks bubbling into a chart open.
  it('keeps evidence actions separate from row chart actions', async () => {
    const onOpenChart = vi.fn();
    renderWithProviders(
      <CorrectionSurvivorsPanel
        summary={completeSummary}
        posture={null}
        onOpenChart={onOpenChart}
        navigationSymbols={['FIRST', 'SECOND']}
      />,
    );

    const user = userEvent.setup();
    await user.click(screen.getByText('Setup Ready'));

    expect(onOpenChart).not.toHaveBeenCalled();
  });
});
