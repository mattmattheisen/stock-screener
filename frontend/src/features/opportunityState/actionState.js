export const ACTION_STATE_META = Object.freeze({
  exit_risk: { label: 'Exit Risk', color: 'error' },
  deteriorating: { label: 'Deteriorating', color: 'warning' },
  event_risk: { label: 'Event Risk', color: 'warning' },
  extended: { label: 'Extended', color: 'info' },
  data_limited: { label: 'Data Limited', color: 'default' },
  setup_ready: { label: 'Setup Ready', color: 'success' },
  watch: { label: 'Watch', color: 'default' },
});

const NOT_COMPUTED_META = Object.freeze({ label: 'Not computed', color: 'default' });

export function actionStateMeta(state) {
  return ACTION_STATE_META[state] ?? NOT_COMPUTED_META;
}
