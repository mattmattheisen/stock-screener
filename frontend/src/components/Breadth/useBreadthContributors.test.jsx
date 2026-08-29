import { focusManager } from '@tanstack/react-query';
import { act, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderHookWithProviders } from '../../test/renderWithProviders';
import { useBreadthContributors } from './useBreadthContributors';

const index = {
  schema: 'breadth-contributors-v1',
  market: 'US',
  calculation_revision: 3,
  dates: ['2026-08-28'],
};

afterEach(() => focusManager.setFocused(undefined));

describe('useBreadthContributors', () => {
  it('loads the index immediately and one advertised date lazily', async () => {
    const loadIndex = vi.fn().mockResolvedValue(index);
    const loadDate = vi.fn().mockResolvedValue({ ...index, date: '2026-08-28', contributors: [] });
    const { result } = renderHookWithProviders(() => useBreadthContributors({
      market: 'US', indexQueryKey: ['contributors', 'US'], loadIndex, loadDate,
    }));

    await waitFor(() => expect(result.current.availableDates.has('2026-08-28')).toBe(true));
    expect(loadDate).not.toHaveBeenCalled();

    act(() => result.current.open('stocks_up_4pct', { date: '2026-08-28', stocks_up_4pct: 0 }));
    await waitFor(() => expect(result.current.dialogQuery.data?.date).toBe('2026-08-28'));
    expect(loadDate).toHaveBeenCalledWith('2026-08-28');
  });

  it('does not open a date omitted by the validated index', async () => {
    const loadDate = vi.fn();
    const { result } = renderHookWithProviders(() => useBreadthContributors({
      market: 'US',
      indexQueryKey: ['contributors', 'US'],
      loadIndex: () => Promise.resolve(index),
      loadDate,
    }));
    await waitFor(() => expect(result.current.availableDates.size).toBe(1));

    act(() => result.current.open('stocks_up_4pct', { date: '2026-08-27', stocks_up_4pct: 1 }));

    expect(result.current.selected).toBeNull();
    expect(loadDate).not.toHaveBeenCalled();
  });

  it('refreshes a stale live index when the window regains focus', async () => {
    const updatedIndex = { ...index, dates: ['2026-08-29', ...index.dates] };
    const loadIndex = vi.fn()
      .mockResolvedValueOnce(index)
      .mockResolvedValueOnce(updatedIndex);
    const { result } = renderHookWithProviders(() => useBreadthContributors({
      market: 'US',
      indexQueryKey: ['contributors', 'US'],
      loadIndex,
      loadDate: vi.fn(),
      indexStaleTime: 0,
    }));
    await waitFor(() => expect(result.current.availableDates.has('2026-08-28')).toBe(true));

    act(() => focusManager.setFocused(false));
    act(() => focusManager.setFocused(true));

    await waitFor(() => expect(result.current.availableDates.has('2026-08-29')).toBe(true));
    expect(loadIndex).toHaveBeenCalledTimes(2);
  });
});
