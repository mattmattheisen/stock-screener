"""Typed aggregate contract shared by opportunity-state consumers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

from .opportunity_state import ActionState


@dataclass(frozen=True)
class OpportunityStateSummary:
    rows_total: int
    survivor_count: int
    action_state_counts: Mapping[ActionState, int]
    survivor_action_state_counts: Mapping[ActionState, int]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "action_state_counts",
            MappingProxyType(
                {
                    state: int(self.action_state_counts.get(state, 0))
                    for state in ActionState
                }
            ),
        )
        object.__setattr__(
            self,
            "survivor_action_state_counts",
            MappingProxyType(
                {
                    state: int(self.survivor_action_state_counts.get(state, 0))
                    for state in ActionState
                }
            ),
        )


class OpportunityStateSummaryReader(Protocol):
    def for_scan(self, scan_id: str) -> OpportunityStateSummary: ...

    def for_feature_run(self, run_id: int) -> OpportunityStateSummary: ...
