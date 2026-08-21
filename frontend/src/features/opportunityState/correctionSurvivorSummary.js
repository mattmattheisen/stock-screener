import { ACTION_STATE_META } from './actionState';

const ACTION_STATES = Object.freeze(Object.keys(ACTION_STATE_META));
const MAX_DAILY_ROWS = 20;

const emptyCounts = () => Object.fromEntries(ACTION_STATES.map((state) => [state, 0]));

export function buildCorrectionSurvivorSummary(rows, { complete } = {}) {
  if (!complete) {
    return {
      available: false,
      complete: false,
      count: 0,
      counts_by_action_state: emptyCounts(),
      rows: [],
    };
  }

  const selectedRows = Array.isArray(rows) ? rows : [];
  const countsByActionState = emptyCounts();
  selectedRows.forEach((row) => {
    if (Object.hasOwn(countsByActionState, row?.action_state)) {
      countsByActionState[row.action_state] += 1;
    }
  });

  return {
    available: true,
    complete: true,
    count: selectedRows.length,
    counts_by_action_state: countsByActionState,
    rows: selectedRows.slice(0, MAX_DAILY_ROWS),
  };
}

export { ACTION_STATES as CORRECTION_SURVIVOR_ACTION_STATES };
