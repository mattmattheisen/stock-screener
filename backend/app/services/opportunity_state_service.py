"""Point-in-time assembly for the persisted opportunity-state projection."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date, datetime
from typing import TYPE_CHECKING

from app.analysis.patterns.config import SetupEngineParameters
from app.domain.scanning.default_filters import resolve_default_scan_filters
from app.domain.scanning.opportunity_state import (
    InvalidationEvidence,
    OpportunityInputs,
    evaluate_opportunity_state,
    normalize_event_date,
)
from app.services.security_master_service import SecurityMasterResolver

if TYPE_CHECKING:
    from app.scanners.base_screener import StockData


def build_opportunity_projection(
    result: Mapping[str, object],
    stock_data: StockData,
    parameters: SetupEngineParameters,
) -> dict[str, object]:
    """Assemble current scan evidence and evaluate the policy exactly once."""
    setup = _mapping_or_none(result.get("setup_engine"))
    fundamentals = _mapping_or_empty(stock_data.fundamentals)
    event = normalize_event_date(
        fundamentals.get("next_earnings_date"),
        key_present="next_earnings_date" in fundamentals,
    )
    market = _normalized_market(stock_data.market)
    as_of_date = _last_frame_date(stock_data.price_data)
    liquidity_floor = resolve_default_scan_filters(market).get("minVolume")
    avg_dollar_volume = _finite_float(result.get("avg_dollar_volume"))
    invalidation_flags = _invalidation_flags(setup)

    inputs = OpportunityInputs(
        market=market,
        mic=SecurityMasterResolver.resolve_exchange_mic(market, stock_data.exchange),
        as_of_date=as_of_date,
        benchmark_symbol=_text_or_none(stock_data.benchmark_symbol),
        benchmark_as_of_date=_last_frame_date(stock_data.benchmark_data),
        benchmark_relative_return_65d=_number_from(setup, "rs_vs_spy_65d"),
        rs_rating_1m=_finite_float(result.get("rs_rating_1m")),
        rs_rating_3m=_finite_float(result.get("rs_rating_3m")),
        rs_line_new_high=_bool_from(setup, "rs_line_new_high"),
        rs_line_blue_dot=_bool_from(setup, "rs_line_blue_dot"),
        stage=_integer_or_none(result.get("stage")),
        ma_alignment=_bool_or_none(result.get("ma_alignment")),
        invalidation_evidence_available=invalidation_flags is not None,
        invalidation_flags=invalidation_flags,
        setup_payload_available=setup is not None,
        pattern_primary=_text_from(setup, "pattern_primary"),
        squeeze=_bool_from(setup, "bb_squeeze"),
        tight_closes_count=_integer_from(setup, "tight_closes_count"),
        quiet_days_count=_integer_from(setup, "quiet_days_10d"),
        volume_vs_50d=_number_from(setup, "volume_vs_50d"),
        volume_dry_up_max=parameters.volume_vs_50d_max_for_ready,
        liquidity_available=(
            liquidity_floor is not None and avg_dollar_volume is not None
        ),
        liquidity_passes=(
            avg_dollar_volume >= liquidity_floor
            if liquidity_floor is not None and avg_dollar_volume is not None
            else None
        ),
        feature_status=_text_from(result, "data_status"),
        is_scannable=_bool_or_none(result.get("is_scannable")),
        event_calendar_available=event.available,
        earnings_soon=(
            _event_is_inside_window(
                event.value,
                as_of_date,
                parameters.earnings_soon_window_days,
            )
            if event.available
            else None
        ),
        setup_ready=_bool_from(setup, "setup_ready"),
        in_early_zone=_bool_from(setup, "in_early_zone"),
        extended=_bool_from(setup, "extended_from_pivot"),
        prior_run_required=False,
        prior_run_available=False,
        deterioration_confirmed=False,
        stewardship_status=None,
    )
    projection = evaluate_opportunity_state(inputs).projection()
    _projection_metrics(projection)["liquidity_floor_local"] = liquidity_floor
    return projection


def build_data_limited_projection(
    result: Mapping[str, object],
    stock_data: StockData,
    reason: str,
) -> dict[str, object]:
    """Build an explicit structured fallback while preserving row identity."""
    market = _normalized_market(stock_data.market)
    as_of_date = _last_frame_date(stock_data.price_data)
    fundamentals = _mapping_or_empty(stock_data.fundamentals)
    event = normalize_event_date(
        fundamentals.get("next_earnings_date"),
        key_present="next_earnings_date" in fundamentals,
    )
    liquidity_floor = resolve_default_scan_filters(market).get("minVolume")
    avg_dollar_volume = _finite_float(result.get("avg_dollar_volume"))

    inputs = OpportunityInputs(
        market=market,
        mic=SecurityMasterResolver.resolve_exchange_mic(market, stock_data.exchange),
        as_of_date=as_of_date,
        benchmark_symbol=_text_or_none(stock_data.benchmark_symbol),
        benchmark_as_of_date=_last_frame_date(stock_data.benchmark_data),
        benchmark_relative_return_65d=None,
        rs_rating_1m=None,
        rs_rating_3m=None,
        rs_line_new_high=None,
        rs_line_blue_dot=None,
        stage=None,
        ma_alignment=None,
        invalidation_evidence_available=False,
        invalidation_flags=None,
        setup_payload_available=False,
        pattern_primary=None,
        squeeze=None,
        tight_closes_count=None,
        quiet_days_count=None,
        volume_vs_50d=None,
        volume_dry_up_max=None,
        liquidity_available=(
            liquidity_floor is not None and avg_dollar_volume is not None
        ),
        liquidity_passes=(
            avg_dollar_volume >= liquidity_floor
            if liquidity_floor is not None and avg_dollar_volume is not None
            else None
        ),
        feature_status=_text_from(result, "data_status"),
        is_scannable=_bool_or_none(result.get("is_scannable")),
        event_calendar_available=event.available,
        earnings_soon=None,
        setup_ready=None,
        in_early_zone=None,
        extended=None,
        prior_run_required=False,
        prior_run_available=False,
        deterioration_confirmed=False,
        stewardship_status=None,
    )
    projection = evaluate_opportunity_state(inputs).projection()
    evidence = projection.get("opportunity_state")
    if not isinstance(evidence, dict):  # pragma: no cover - evaluator contract guard
        raise TypeError("Opportunity policy returned no evidence payload")
    evidence["action_reasons"] = [reason]
    _projection_metrics(projection)["liquidity_floor_local"] = liquidity_floor
    return projection


def _mapping_or_none(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    if not all(isinstance(key, str) for key in value):
        return None
    return dict(value)


def _mapping_or_empty(value: object) -> dict[str, object]:
    return _mapping_or_none(value) or {}


def _normalized_market(value: object) -> str | None:
    normalized = str(value or "").strip().upper()
    return normalized or None


def _text_or_none(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _text_from(source: Mapping[str, object] | None, key: str) -> str | None:
    return _text_or_none(source.get(key)) if source is not None else None


def _finite_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _number_from(source: Mapping[str, object] | None, key: str) -> float | None:
    return _finite_float(source.get(key)) if source is not None else None


def _bool_or_none(value: object) -> bool | None:
    return value if type(value) is bool else None


def _bool_from(source: Mapping[str, object] | None, key: str) -> bool | None:
    return _bool_or_none(source.get(key)) if source is not None else None


def _integer_or_none(value: object) -> int | None:
    numeric = _finite_float(value)
    if numeric is None or not numeric.is_integer():
        return None
    return int(numeric)


def _integer_from(source: Mapping[str, object] | None, key: str) -> int | None:
    return _integer_or_none(source.get(key)) if source is not None else None


def _last_frame_date(frame: object) -> date | None:
    if frame is None or getattr(frame, "empty", True):
        return None
    try:
        value = frame.index[-1]
    except (AttributeError, IndexError, KeyError, TypeError):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    to_pydatetime = getattr(value, "to_pydatetime", None)
    if callable(to_pydatetime):
        converted = to_pydatetime()
        if isinstance(converted, datetime):
            return converted.date()
        if isinstance(converted, date):
            return converted
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _event_is_inside_window(
    event_date: date | None,
    as_of_date: date | None,
    window_days: float,
) -> bool | None:
    if event_date is None:
        return False
    if as_of_date is None:
        return None
    days_until_event = (event_date - as_of_date).days
    return 0 <= days_until_event <= window_days


def _invalidation_flags(
    setup: Mapping[str, object] | None,
) -> tuple[InvalidationEvidence, ...] | None:
    if setup is None:
        return None
    explain = setup.get("explain")
    if not isinstance(explain, Mapping):
        return None
    raw_flags = explain.get("invalidation_flags")
    if not isinstance(raw_flags, list):
        return None

    flags: list[InvalidationEvidence] = []
    for raw_flag in raw_flags:
        if not isinstance(raw_flag, Mapping):
            return None
        code = _text_or_none(raw_flag.get("code"))
        is_hard = raw_flag.get("is_hard")
        if code is None or type(is_hard) is not bool:
            return None
        flags.append(InvalidationEvidence(code=code, is_hard=is_hard))
    return tuple(flags)


def _projection_metrics(projection: Mapping[str, object]) -> dict[str, object]:
    evidence = projection.get("opportunity_state")
    if not isinstance(evidence, dict):  # pragma: no cover - evaluator contract guard
        raise TypeError("Opportunity policy returned malformed evidence")
    metrics = evidence.get("metrics")
    if not isinstance(metrics, dict):  # pragma: no cover - evaluator contract guard
        raise TypeError("Opportunity policy returned malformed metrics")
    return metrics


__all__ = ["build_data_limited_projection", "build_opportunity_projection"]
