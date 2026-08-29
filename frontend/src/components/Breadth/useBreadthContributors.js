import { useCallback, useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';

const validateIndex = (index, market) => {
  const dates = index?.dates;
  if (
    index?.schema !== 'breadth-contributors-v1'
    || index?.calculation_revision !== 3
    || String(index?.market || '').toUpperCase() !== String(market || '').toUpperCase()
    || !Array.isArray(dates)
    || dates.length > 20
    || new Set(dates).size !== dates.length
    || dates.some((date) => !/^\d{4}-\d{2}-\d{2}$/.test(date))
    || dates.some((date, position) => position > 0 && dates[position - 1] < date)
  ) {
    throw new Error('Invalid breadth contributor index');
  }
  return index;
};

export const useBreadthContributors = ({
  market,
  indexQueryKey,
  loadIndex,
  loadDate,
}) => {
  const [selected, setSelected] = useState(null);
  const indexIdentity = JSON.stringify(indexQueryKey);
  useEffect(() => setSelected(null), [market, indexIdentity]);
  const indexQuery = useQuery({
    queryKey: indexQueryKey,
    queryFn: async () => validateIndex(await loadIndex(), market),
    enabled: Boolean(loadIndex && indexQueryKey),
    staleTime: Infinity,
  });
  const availableDates = useMemo(
    () => new Set(indexQuery.data?.dates || []),
    [indexQuery.data],
  );
  const open = useCallback((metric, row, anchor = null) => {
    if (!availableDates.has(row?.date)) return;
    setSelected({ metric, row, anchor });
  }, [availableDates]);
  const close = useCallback(() => setSelected(null), []);
  const selectedDate = selected?.row?.date || null;
  const dialogQuery = useQuery({
    queryKey: [
      'breadthContributors',
      String(market || '').toUpperCase(),
      selectedDate,
      'breadth-contributors-v1',
      3,
    ],
    queryFn: () => loadDate(selectedDate),
    enabled: Boolean(selectedDate && loadDate && availableDates.has(selectedDate)),
    staleTime: Infinity,
  });

  return {
    availableDates,
    indexQuery,
    selected,
    open,
    close,
    dialogQuery,
  };
};
