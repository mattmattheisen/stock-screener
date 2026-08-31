import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '../../test/renderWithProviders';
import AddToWatchlistMenu from './AddToWatchlistMenu';

const api = vi.hoisted(() => ({
  getWatchlists: vi.fn(),
  getWatchlistMemberships: vi.fn(),
  createWatchlist: vi.fn(),
  addItem: vi.fn(),
  bulkAddItems: vi.fn(),
}));

vi.mock('../../api/userWatchlists', () => api);

const renderMenu = () => {
  renderWithProviders(
    <AddToWatchlistMenu
      symbols="MSFT"
      trigger={<button type="button">Add to Watchlist</button>}
    />,
  );
  fireEvent.click(screen.getByRole('button', { name: 'Add to Watchlist' }));
};

describe('AddToWatchlistMenu', () => {
  beforeEach(() => {
    Object.values(api).forEach((mockFn) => mockFn.mockReset());
    api.getWatchlists.mockResolvedValue({
      watchlists: [
        { id: 1, name: 'Portfolio' },
        { id: 2, name: 'Growth' },
      ],
      total: 2,
    });
    api.getWatchlistMemberships.mockResolvedValue({
      memberships: { MSFT: [1] },
    });
    api.addItem.mockResolvedValue({ id: 10, watchlist_id: 2, symbol: 'MSFT' });
  });

  it('marks an existing membership and prevents a duplicate add request', async () => {
    renderMenu();

    const portfolioItem = await screen.findByRole('menuitem', { name: /Portfolio Already added/i });

    expect(api.getWatchlistMemberships).toHaveBeenCalledWith(['MSFT']);
    expect(portfolioItem).toHaveAttribute('aria-disabled', 'true');
    fireEvent.click(portfolioItem);
    expect(api.addItem).not.toHaveBeenCalled();
  });

  it('updates membership immediately after a successful add', async () => {
    renderMenu();

    const growthItem = await screen.findByRole('menuitem', { name: 'Growth' });
    fireEvent.click(growthItem);

    await waitFor(() => {
      expect(api.addItem).toHaveBeenCalledWith(2, { symbol: 'MSFT' });
      expect(screen.getByRole('menuitem', { name: /Growth Already added/i }))
        .toHaveAttribute('aria-disabled', 'true');
    });
  });

  it('shows the backend error when adding fails', async () => {
    api.addItem.mockRejectedValueOnce({
      response: { data: { detail: 'Stock already exists in watchlist' } },
    });
    api.getWatchlistMemberships.mockResolvedValueOnce({
      memberships: { MSFT: [] },
    });
    renderMenu();

    fireEvent.click(await screen.findByRole('menuitem', { name: 'Portfolio' }));

    expect(await screen.findByText('Stock already exists in watchlist')).toBeInTheDocument();
  });

  it('refreshes membership whenever the menu reopens despite the app cache window', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false, staleTime: 300_000 },
      },
    });
    api.getWatchlistMemberships.mockResolvedValueOnce({
      memberships: { MSFT: [] },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <AddToWatchlistMenu
          symbols="MSFT"
          trigger={<button type="button">Add to Watchlist</button>}
        />
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Add to Watchlist' }));
    expect(await screen.findByRole('menuitem', { name: 'Portfolio' })).toBeEnabled();
    expect(api.getWatchlistMemberships).toHaveBeenCalledTimes(1);

    fireEvent.click(document.querySelector('.MuiBackdrop-root'));
    await waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument());
    let resolveRefresh;
    const refreshPromise = new Promise((resolve) => {
      resolveRefresh = resolve;
    });
    api.getWatchlistMemberships.mockImplementationOnce(() => refreshPromise);

    fireEvent.click(screen.getByRole('button', { name: 'Add to Watchlist' }));

    await waitFor(() => expect(api.getWatchlistMemberships).toHaveBeenCalledTimes(2));
    expect(screen.getByRole('progressbar')).toBeInTheDocument();
    expect(screen.queryByRole('menuitem', { name: 'Portfolio' })).not.toBeInTheDocument();
    await act(async () => {
      resolveRefresh({ memberships: { MSFT: [1] } });
    });
    expect(await screen.findByRole('menuitem', { name: /Portfolio Already added/i }))
      .toHaveAttribute('aria-disabled', 'true');
  });
});
