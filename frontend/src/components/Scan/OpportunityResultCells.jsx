import { memo, useCallback } from 'react';
import { TableCell } from '@mui/material';

import ActionStateBadge from '../shared/ActionStateBadge';

function OpportunityResultCells({ row, visible, onOpenEvidence }) {
  const handleOpen = useCallback((event) => {
    event.stopPropagation();
    onOpenEvidence(row);
  }, [onOpenEvidence, row]);

  if (!visible) {
    return null;
  }

  return (
    <>
      <TableCell
        align="center"
        sx={{ fontFamily: 'monospace', width: 48, minWidth: 48 }}
      >
        {row.resilience_score != null
          ? Number(row.resilience_score).toFixed(1)
          : '-'}
      </TableCell>
      <TableCell align="center" sx={{ width: 105, minWidth: 105 }}>
        <ActionStateBadge
          state={row.action_state}
          onClick={row.opportunity_state ? handleOpen : undefined}
        />
      </TableCell>
    </>
  );
}

export default memo(OpportunityResultCells);
