import { useCallback, useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  BREADTH_CONTRIBUTOR_REVISION,
  BREADTH_CONTRIBUTOR_SCHEMA,
  validateBreadthContributorIndex,
} from './breadthContributorContract';
import { buildBreadthContributorView } from './breadthContributorView';

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
    queryFn: async () => validateBreadthContributorIndex(await loadIndex(), market),
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
  const close = useCallback(() => {
    selected?.anchor?.focus?.();
    setSelected(null);
  }, [selected]);
  const selectedDate = selected?.row?.date || null;
  const dialogQuery = useQuery({
    queryKey: [
      'breadthContributors',
      String(market || '').toUpperCase(),
      selectedDate,
      BREADTH_CONTRIBUTOR_SCHEMA,
      BREADTH_CONTRIBUTOR_REVISION,
    ],
    queryFn: () => loadDate(selectedDate),
    enabled: Boolean(selectedDate && loadDate && availableDates.has(selectedDate)),
    staleTime: Infinity,
  });
  const viewState = useMemo(() => {
    if (!dialogQuery.data || !selected) {
      return { view: null, inconsistent: null };
    }
    const { metric, row } = selected;
    try {
      return {
        view: buildBreadthContributorView(
          dialogQuery.data,
          metric,
          row[metric],
          { market, date: row.date },
        ),
        inconsistent: null,
      };
    } catch (error) {
      return { view: null, inconsistent: error.message };
    }
  }, [dialogQuery.data, market, selected]);

  return {
    availableDates,
    indexQuery,
    selected,
    open,
    close,
    dialogQuery,
    viewState,
  };
};
