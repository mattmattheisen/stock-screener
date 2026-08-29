import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useBreadthContributors } from './useBreadthContributors';

const index = {
  schema: 'breadth-contributors-v1',
  market: 'US',
  calculation_revision: 3,
  dates: ['2026-08-28'],
};

const wrapper = ({ children }) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    {children}
  </QueryClientProvider>
);

describe('useBreadthContributors', () => {
  it('loads the index immediately and one advertised date lazily', async () => {
    const loadIndex = vi.fn().mockResolvedValue(index);
    const loadDate = vi.fn().mockResolvedValue({ ...index, date: '2026-08-28', contributors: [] });
    const { result } = renderHook(() => useBreadthContributors({
      market: 'US', indexQueryKey: ['contributors', 'US'], loadIndex, loadDate,
    }), { wrapper });

    await waitFor(() => expect(result.current.availableDates.has('2026-08-28')).toBe(true));
    expect(loadDate).not.toHaveBeenCalled();

    act(() => result.current.open('stocks_up_4pct', { date: '2026-08-28', stocks_up_4pct: 0 }));
    await waitFor(() => expect(result.current.dialogQuery.data?.date).toBe('2026-08-28'));
    expect(loadDate).toHaveBeenCalledWith('2026-08-28');
  });

  it('does not open a date omitted by the validated index', async () => {
    const loadDate = vi.fn();
    const { result } = renderHook(() => useBreadthContributors({
      market: 'US',
      indexQueryKey: ['contributors', 'US'],
      loadIndex: () => Promise.resolve(index),
      loadDate,
    }), { wrapper });
    await waitFor(() => expect(result.current.availableDates.size).toBe(1));

    act(() => result.current.open('stocks_up_4pct', { date: '2026-08-27', stocks_up_4pct: 1 }));

    expect(result.current.selected).toBeNull();
    expect(loadDate).not.toHaveBeenCalled();
  });
});
