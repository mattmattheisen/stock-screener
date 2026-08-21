import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/renderWithProviders';
import ActionStateBadge from './ActionStateBadge';

describe('ActionStateBadge', () => {
  // Catches a missing or incorrectly normalized persisted state label.
  it.each([
    ['exit_risk', 'Exit Risk'],
    ['deteriorating', 'Deteriorating'],
    ['event_risk', 'Event Risk'],
    ['extended', 'Extended'],
    ['data_limited', 'Data Limited'],
    ['setup_ready', 'Setup Ready'],
    ['watch', 'Watch'],
    [null, 'Not computed'],
    ['unknown_state', 'Not computed'],
  ])('renders %s as %s', (state, label) => {
    renderWithProviders(<ActionStateBadge state={state} />);

    expect(screen.getByText(label)).toBeInTheDocument();
  });

  // Catches a non-interactive badge that prevents an evidence drawer from opening by keyboard or pointer.
  it('becomes an accessible button only when an evidence action is supplied', async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();
    const { rerender } = renderWithProviders(<ActionStateBadge state="setup_ready" />);

    expect(screen.queryByRole('button', { name: 'Setup Ready' })).not.toBeInTheDocument();

    rerender(<ActionStateBadge state="setup_ready" onClick={onClick} />);
    await user.click(screen.getByRole('button', { name: 'Setup Ready' }));

    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
