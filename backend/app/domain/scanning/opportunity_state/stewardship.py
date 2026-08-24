"""Cross-run stewardship overlay for a current opportunity assessment."""

from __future__ import annotations

from dataclasses import replace

from .model import ACTION_STATES, ActionState, OpportunityAssessment

_STATE_PRIORITY = {state: index for index, state in enumerate(ACTION_STATES)}


def overlay_stewardship_state(
    result: OpportunityAssessment,
    stewardship_status: str | None,
    prior_run_available: bool,
) -> OpportunityAssessment:
    """Apply a supported stewardship state only when it outranks persisted state."""
    if stewardship_status is None:
        return result
    try:
        stewardship_state = ActionState(stewardship_status)
    except ValueError:
        return result
    if stewardship_state is not ActionState.EXIT_RISK and prior_run_available is not True:
        return result
    if _STATE_PRIORITY[stewardship_state] >= _STATE_PRIORITY[result.action_state]:
        return result

    reason = f"stewardship_{stewardship_state.value}"
    action_reasons = result.action_reasons
    if reason not in action_reasons:
        action_reasons += (reason,)
    data_availability = {
        **result.data_availability,
        "prior_run": "available" if prior_run_available else "unavailable",
    }
    return replace(
        result,
        action_state=stewardship_state,
        action_reasons=action_reasons,
        data_availability=data_availability,
    )
