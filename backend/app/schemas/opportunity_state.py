"""Versioned HTTP contract for persisted opportunity-state evidence."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class OpportunityStateResponse(BaseModel):
    schema_version: Literal[1]
    policy_version: Literal["correction-survivors-v1"]
    as_of_date: str | None = None
    market: str | None = None
    mic: str | None = None
    benchmark_symbol: str | None = None
    benchmark_as_of_date: str | None = None
    passed_checks: list[str] = Field(default_factory=list)
    failed_checks: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    data_availability: dict[str, str] = Field(default_factory=dict)
    action_reasons: list[str] = Field(default_factory=list)


__all__ = ["OpportunityStateResponse"]
