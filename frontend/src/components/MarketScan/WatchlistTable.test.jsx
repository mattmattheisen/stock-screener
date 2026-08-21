import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

import { renderWithProviders } from '../../test/renderWithProviders';
import { recordOpportunityEvidenceOpen } from '../../features/opportunityState/opportunityTelemetry';
import WatchlistTable from './WatchlistTable';

vi.mock('../../features/opportunityState/opportunityTelemetry', () => ({
  recordOpportunityEvidenceOpen: vi.fn().mockResolvedValue(undefined),
}));

const watchlistData = {
  id: 1,
  name: 'Leaders',
  items: [
    {
      id: 11,
      symbol: 'NVDA',
      company_name: 'NVIDIA',
      rs_data: [],
      rs_trend: 0,
      price_data: [],
      price_trend: 0,
      change_1d: 1.2,
    },
  ],
  price_change_bounds: {},
};

const stewardshipBySymbol = {
  NVDA: {
    symbol: 'NVDA',
    status: 'strengthening',
    score_delta: 4.5,
    rs_delta: 3,
    days_until_earnings: 21,
    theme_support: 'new',
    correction_survivor: true,
    resilience_score: 91.5,
    action_state: 'setup_ready',
    opportunity_state: {
      schema_version: 1,
      policy_version: 'correction-survivors-v1',
      as_of_date: '2026-08-21',
      market: 'US',
      mic: 'XNAS',
      benchmark_symbol: 'SPY',
      benchmark_as_of_date: '2026-08-21',
      passed_checks: ['leadership_gate'],
      failed_checks: [],
      warnings: [],
      score_pillars: {},
      metrics: {},
      data_availability: {},
      action_reasons: ['setup_ready'],
    },
  },
};

const renderTable = (onOpenChart = vi.fn()) => ({
  onOpenChart,
  ...renderWithProviders(
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <WatchlistTable
        watchlistData={watchlistData}
        stewardshipBySymbol={stewardshipBySymbol}
        onOpenChart={onOpenChart}
      />
    </MemoryRouter>,
  ),
});

describe('WatchlistTable', () => {
  beforeEach(() => {
    recordOpportunityEvidenceOpen.mockClear();
  });

  // Catches the existing stewardship label being replaced instead of shown beside Action State.
  it('shows stewardship and Action State as separate columns and opens shared evidence', async () => {
    const user = userEvent.setup();
    const { onOpenChart } = renderTable();

    expect(screen.getByRole('columnheader', { name: 'Stewardship' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Action' })).toBeInTheDocument();
    expect(screen.getByText('strengthening')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Setup Ready' }));

    expect(screen.getByText('Resilience score')).toBeInTheDocument();
    expect(screen.getByText('91.5')).toBeInTheDocument();
    expect(recordOpportunityEvidenceOpen).toHaveBeenCalledOnce();
    expect(recordOpportunityEvidenceOpen).toHaveBeenCalledWith('US', 'watchlist');
    expect(onOpenChart).not.toHaveBeenCalled();
  });

  // Catches keyboard-generated badge clicks bubbling into the chart row action.
  it('isolates Action State keyboard activation from chart opening', async () => {
    const user = userEvent.setup();
    const { onOpenChart } = renderTable();
    const actionBadge = screen.getByRole('button', { name: 'Setup Ready' });

    actionBadge.focus();
    await user.keyboard('{Enter}');

    expect(screen.getByText('Opportunity evidence')).toBeInTheDocument();
    expect(onOpenChart).not.toHaveBeenCalled();
  });

  // Catches Action State integration disabling the pre-existing row chart action.
  it('preserves row chart opening outside the Action State control', async () => {
    const user = userEvent.setup();
    const { onOpenChart } = renderTable();

    await user.click(screen.getByText('NVIDIA'));

    expect(onOpenChart).toHaveBeenCalledWith('NVDA');
  });
});
