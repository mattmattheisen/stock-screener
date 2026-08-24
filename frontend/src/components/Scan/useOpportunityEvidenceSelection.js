import { useCallback, useEffect, useMemo, useState } from 'react';

export function useOpportunityEvidenceSelection({ rows, enabled }) {
  const [selectedSymbol, setSelectedSymbol] = useState(null);
  const selectedRow = useMemo(
    () => rows?.find((row) => row?.symbol === selectedSymbol) ?? null,
    [rows, selectedSymbol],
  );

  useEffect(() => {
    if (
      selectedSymbol != null
      && (!enabled || !selectedRow?.opportunity_state)
    ) {
      setSelectedSymbol(null);
    }
  }, [enabled, selectedRow, selectedSymbol]);

  const openEvidence = useCallback((row) => {
    setSelectedSymbol(row?.symbol ?? null);
  }, []);
  const closeEvidence = useCallback(() => {
    setSelectedSymbol(null);
  }, []);

  return {
    selectedRow,
    openEvidence,
    closeEvidence,
  };
}
