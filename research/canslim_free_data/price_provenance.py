"""Fail-closed provenance gate for CAN SLIM price history.

A receipt records *evidence claimed by an upstream audit*. Its presence
is not independent proof. No broker orders, remote calls, or secrets.
"""
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum


class Purpose(str, Enum):
    LIVE_EOD = "live_eod"
    HISTORICAL_BACKTEST = "historical_backtest"


@dataclass(frozen=True)
class PriceProvenance:
    symbol: str
    source: str
    expected_session: date
    latest_session: date
    requested_as_of: date
    retrieved_at: datetime
    history_start: date
    adjustment_mode: str  # accepted: verified_explicit_adj_close
    adjustment_verified_by: str
    corporate_actions_verified_by: str
    split_volume_verified_by: str
    point_in_time_source: bool


@dataclass(frozen=True)
class ProvenanceAssessment:
    accepted: bool
    failures: tuple[str, ...]


def check_provenance(receipt: PriceProvenance, purpose: Purpose) -> ProvenanceAssessment:
    """Check preconditions without treating unverifiable strings as proof.

    A source system must substantiate each verification identity with
    immutable evidence in a later production version.
    """
    failures = []
    if not receipt.symbol.strip() or not receipt.source.strip():
        failures.append("MISSING_IDENTITY")
    if receipt.requested_as_of < receipt.expected_session:
        failures.append("AS_OF_BEFORE_EXPECTED_SESSION")
    if receipt.latest_session != receipt.expected_session:
        failures.append("STALE_OR_FUTURE_SESSION")
    if receipt.history_start > receipt.latest_session:
        failures.append("INVALID_HISTORY_RANGE")
    if receipt.adjustment_mode != "verified_explicit_adj_close":
        failures.append("ADJUSTMENT_MODE_UNVERIFIED")
    if not receipt.adjustment_verified_by.strip():
        failures.append("NO_ADJUSTMENT_AUDITOR")
    if not receipt.corporate_actions_verified_by.strip():
        failures.append("NO_CORPORATE_ACTION_AUDITOR")
    if not receipt.split_volume_verified_by.strip():
        failures.append("NO_VOLUME_RECONCILIATION")
    if receipt.retrieved_at.tzinfo is None or receipt.retrieved_at.utcoffset() is None:
        failures.append("NAIVE_RETRIEVAL_TIMESTAMP")
    elif purpose == Purpose.HISTORICAL_BACKTEST:
        # Reconstructed history fetched today may contain later corrections,
        # future corporate actions and dividend restatements. It cannot
        # be asserted to have been known on a historical research date.
        if (receipt.retrieved_at.astimezone(timezone.utc).date()
                > receipt.requested_as_of or not receipt.point_in_time_source):
            failures.append("NOT_POINT_IN_TIME")
    return ProvenanceAssessment(not failures, tuple(failures))
