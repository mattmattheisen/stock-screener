import { Chip } from '@mui/material';
import { actionStateMeta } from '../../features/opportunityState/actionState';

function ActionStateBadge({ state, onClick }) {
  const { label, color } = actionStateMeta(state);
  const isInteractive = typeof onClick === 'function';

  return (
    <Chip
      label={label}
      color={color}
      size="small"
      variant="outlined"
      clickable={isInteractive}
      onClick={isInteractive ? onClick : undefined}
      sx={{ fontSize: '0.7rem', fontWeight: 600, height: 22 }}
    />
  );
}

export { ActionStateBadge };
export default ActionStateBadge;
