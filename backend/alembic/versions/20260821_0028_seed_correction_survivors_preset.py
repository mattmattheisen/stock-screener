"""Seed Correction Survivors and index its feature-store predicates.

The preset seed follows the ownership-audit convention established by
``20260523_0019``: an existing same-name row belongs to the user, only newly
inserted ids are audited, and downgrade removes an audited row only while its
seed-owned content is unchanged.

The expression indexes are PostgreSQL-only. SQLite still exercises the seed
path in migration tests without parsing PostgreSQL JSON operators.
"""

from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "20260821_0028"
down_revision = "20260808_0027"
branch_labels = None
depends_on = None


CORRECTION_SURVIVORS_PRESET = {
    "name": "Correction Survivors",
    "description": "Leaders that held trend and relative-strength evidence through a correction.",
    "filter_overrides": {"correctionSurvivor": True},
    "sort_by": "resilience_score",
    "sort_order": "desc",
}

_AUDIT_TABLE_NAME = "_seed_correction_survivors_preset_audit"


def _empty_filter_shape() -> dict[str, Any]:
    """Mirror ``buildDefaultScanFilters()`` as of this migration."""

    range_filter = {"min": None, "max": None}
    return {
        "symbolSearch": "",
        "stage": None,
        "ratings": [],
        "ibdIndustries": {"values": [], "mode": "include"},
        "gicsSectors": {"values": [], "mode": "include"},
        "minVolume": None,
        "minMarketCap": None,
        "marketCapUsd": dict(range_filter),
        "advUsd": dict(range_filter),
        "markets": [],
        "compositeScore": dict(range_filter),
        "correctionSurvivor": None,
        "minerviniScore": dict(range_filter),
        "canslimScore": dict(range_filter),
        "ipoScore": dict(range_filter),
        "customScore": dict(range_filter),
        "volBreakthroughScore": dict(range_filter),
        "seSetupScore": dict(range_filter),
        "seDistanceToPivot": dict(range_filter),
        "seBbSqueeze": dict(range_filter),
        "seVolumeVs50d": dict(range_filter),
        "seUpDownVolume": dict(range_filter),
        "sePatternPrimary": [],
        "seSetupReady": None,
        "seRsLineNewHigh": None,
        "seRsLineBlueDot": None,
        "rsLineBlueDotRecent": None,
        "rsRating": dict(range_filter),
        "rs1m": dict(range_filter),
        "rs3m": dict(range_filter),
        "rs12m": dict(range_filter),
        "epsRating": dict(range_filter),
        "ibdGroupRank": dict(range_filter),
        "price": dict(range_filter),
        "adrPercent": dict(range_filter),
        "epsGrowth": dict(range_filter),
        "salesGrowth": dict(range_filter),
        "vcpScore": dict(range_filter),
        "vcpPivot": dict(range_filter),
        "vcpDetected": None,
        "vcpReady": None,
        "maAlignment": None,
        "passesTemplate": None,
        "pocketPivot": None,
        "powerTrend": None,
        "perfDay": dict(range_filter),
        "perfWeek": dict(range_filter),
        "perfMonth": dict(range_filter),
        "perf3m": dict(range_filter),
        "perf6m": dict(range_filter),
        "gapPercent": dict(range_filter),
        "volumeSurge": dict(range_filter),
        "ema10Distance": dict(range_filter),
        "ema20Distance": dict(range_filter),
        "ema50Distance": dict(range_filter),
        "week52HighDistance": dict(range_filter),
        "week52LowDistance": dict(range_filter),
        "ipoAfter": None,
        "beta": dict(range_filter),
        "betaAdjRs": dict(range_filter),
    }


def _filter_presets_table() -> sa.Table:
    metadata = sa.MetaData()
    return sa.Table(
        "filter_presets",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String),
        sa.Column("description", sa.Text),
        sa.Column("filters", sa.Text),
        sa.Column("sort_by", sa.String),
        sa.Column("sort_order", sa.String),
        sa.Column("position", sa.Integer),
    )


def _audit_table_ref() -> sa.Table:
    metadata = sa.MetaData()
    return sa.Table(
        _AUDIT_TABLE_NAME,
        metadata,
        sa.Column("filter_preset_id", sa.Integer, primary_key=True),
        sa.Column("seed_position", sa.Integer, nullable=False),
    )


def _build_filters_payload() -> str:
    payload = _empty_filter_shape()
    payload.update(CORRECTION_SURVIVORS_PRESET["filter_overrides"])
    return json.dumps(payload)


def _index_name(field: str) -> str:
    return f"ix_sfd_run_{field}"


def _index_expr(field: str) -> str:
    expressions = {
        "correction_survivor": "lower(details_json ->> 'correction_survivor')",
        "resilience_score": "CAST(details_json ->> 'resilience_score' AS FLOAT)",
    }
    return expressions[field]


def _seed_preset(bind) -> None:
    table = _filter_presets_table()
    preset = CORRECTION_SURVIVORS_PRESET
    existing_id = bind.execute(
        sa.select(table.c.id).where(table.c.name == preset["name"])
    ).scalar_one_or_none()

    inspector = sa.inspect(bind)
    if not inspector.has_table(_AUDIT_TABLE_NAME):
        op.create_table(
            _AUDIT_TABLE_NAME,
            sa.Column("filter_preset_id", sa.Integer, primary_key=True),
            sa.Column("seed_position", sa.Integer, nullable=False),
        )

    if existing_id is not None:
        return

    next_position = bind.execute(
        sa.select(sa.func.coalesce(sa.func.max(table.c.position), -1))
    ).scalar_one() + 1
    result = bind.execute(
        table.insert().values(
            name=preset["name"],
            description=preset["description"],
            filters=_build_filters_payload(),
            sort_by=preset["sort_by"],
            sort_order=preset["sort_order"],
            position=next_position,
        )
    )
    inserted_id = int(result.inserted_primary_key[0])
    bind.execute(
        _audit_table_ref().insert().values(
            filter_preset_id=inserted_id,
            seed_position=next_position,
        )
    )


def _create_indexes() -> None:
    with op.get_context().autocommit_block():
        for field in ("correction_survivor", "resilience_score"):
            op.execute(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_index_name(field)} "
                f"ON stock_feature_daily (run_id, ({_index_expr(field)}))"
            )


def _drop_indexes() -> None:
    with op.get_context().autocommit_block():
        for field in ("correction_survivor", "resilience_score"):
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_index_name(field)}")


def upgrade() -> None:
    bind = op.get_bind()
    _seed_preset(bind)
    if bind.dialect.name == "postgresql":
        _create_indexes()


def _delete_unchanged_seed(bind) -> None:
    inspector = sa.inspect(bind)
    if not inspector.has_table(_AUDIT_TABLE_NAME):
        return

    table = _filter_presets_table()
    audit = _audit_table_ref()
    audited_rows = bind.execute(
        sa.select(audit.c.filter_preset_id, audit.c.seed_position)
    ).all()
    preset = CORRECTION_SURVIVORS_PRESET
    for inserted_id, seed_position in audited_rows:
        bind.execute(
            table.delete().where(
                sa.and_(
                    table.c.id == inserted_id,
                    table.c.name == preset["name"],
                    table.c.description == preset["description"],
                    table.c.filters == _build_filters_payload(),
                    table.c.sort_by == preset["sort_by"],
                    table.c.sort_order == preset["sort_order"],
                    table.c.position == seed_position,
                )
            )
        )
    op.drop_table(_AUDIT_TABLE_NAME)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        _drop_indexes()
    _delete_unchanged_seed(bind)
