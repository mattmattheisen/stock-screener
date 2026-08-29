import { ThemeProvider, createTheme } from '@mui/material/styles';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import BreadthContributorDialog from './BreadthContributorDialog';
import { buildBreadthContributorView } from './breadthContributorView';

const row = { date: '2026-08-28', stocks_up_4pct: 2 };
const document = {
  schema: 'breadth-contributors-v1', market: 'US', date: row.date,
  calculation_revision: 3,
  contributors: [
    {
      symbol: 'AEHR', company_name: 'Aehr Test Systems',
      ibd_industry_group: 'Semiconductors', daily_change_pct: 25.69,
      signals: { up_4pct: 25.69 },
    },
    {
      symbol: 'AXTI', company_name: 'AXT Inc',
      ibd_industry_group: 'Semiconductors', daily_change_pct: 16.98,
      signals: { up_4pct: 16.98 },
    },
  ],
};
const view = buildBreadthContributorView(document, 'stocks_up_4pct', 2);
const renderDialog = (props = {}) => render(
  <ThemeProvider theme={createTheme()}>
    <BreadthContributorDialog
      open
      metric="stocks_up_4pct"
      row={row}
      view={view}
      onClose={vi.fn()}
      onRetry={vi.fn()}
      {...props}
    />
  </ThemeProvider>,
);

describe('BreadthContributorDialog', () => {
  it('shows compact stocks then expands an IBD group', async () => {
    const user = userEvent.setup();
    renderDialog();

    expect(screen.getByRole('dialog', { name: /Stocks Up 4%\+.*2 stocks/i })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: /Qualifying value/i })).toBeInTheDocument();
    expect(screen.getByText('AEHR')).toBeInTheDocument();
    await user.click(screen.getByRole('tab', { name: 'IBD Groups' }));
    await user.click(screen.getByRole('button', { name: /Semiconductors.*2 stocks/i }));
    expect(screen.getByText('Aehr Test Systems')).toBeInTheDocument();
  });

  it.each([
    ['loading', { isLoading: true, view: null }, /Loading contributors/i],
    ['error', { error: new Error('network'), view: null }, /Could not load contributors/i],
    ['unavailable', { unavailable: true, view: null }, /not available/i],
    ['inconsistent', { inconsistent: 'Count mismatch', view: null }, /Count mismatch/i],
  ])('contains the %s state inside the dialog', (_name, props, message) => {
    renderDialog(props);
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText(message)).toBeInTheDocument();
  });
});
