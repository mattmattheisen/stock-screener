"""Move backend-owned materialization versions out of scan criteria.

Revision ID: 20260823_0029
Revises: 20260821_0028
"""

from __future__ import annotations

import json
from collections.abc import Mapping

import sqlalchemy as sa

from alembic import op

revision = "20260823_0029"
down_revision = "20260821_0028"
branch_labels = None
depends_on = None

_VERSIONS_KEY = "materialization_versions"
_OPPORTUNITY_KEY = "opportunity_state"
_OPPORTUNITY_VERSION = 1


def decode_json(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        decoded = json.loads(value)
        return dict(decoded) if isinstance(decoded, Mapping) else {}
    return {}


def _with_opportunity_version(value: object) -> dict[str, object]:
    payload = decode_json(value)
    raw_versions = payload.get(_VERSIONS_KEY)
    versions = dict(raw_versions) if isinstance(raw_versions, Mapping) else {}
    versions[_OPPORTUNITY_KEY] = _OPPORTUNITY_VERSION
    payload[_VERSIONS_KEY] = versions
    return payload


def _without_opportunity_version(value: object) -> dict[str, object]:
    payload = decode_json(value)
    raw_versions = payload.get(_VERSIONS_KEY)
    if not isinstance(raw_versions, Mapping):
        return payload
    versions = dict(raw_versions)
    versions.pop(_OPPORTUNITY_KEY, None)
    if versions:
        payload[_VERSIONS_KEY] = versions
    else:
        payload.pop(_VERSIONS_KEY, None)
    return payload


def _owns_opportunity_version(value: object) -> bool:
    versions = decode_json(value).get(_VERSIONS_KEY)
    return (
        isinstance(versions, Mapping)
        and versions.get(_OPPORTUNITY_KEY) == _OPPORTUNITY_VERSION
    )


def _scan_table() -> sa.TableClause:
    return sa.table(
        "scans",
        sa.column("id", sa.Integer),
        sa.column("criteria", sa.JSON),
        sa.column("metadata_json", sa.JSON),
    )


def upgrade() -> None:
    op.add_column("scans", sa.Column("metadata_json", sa.JSON(), nullable=True))
    connection = op.get_bind()
    scans = _scan_table()
    rows = connection.execute(
        sa.select(scans.c.id, scans.c.criteria, scans.c.metadata_json)
    ).mappings()
    for row in rows:
        if not _owns_opportunity_version(row["criteria"]):
            continue
        connection.execute(
            scans.update()
            .where(scans.c.id == row["id"])
            .values(
                criteria=_without_opportunity_version(row["criteria"]),
                metadata_json=_with_opportunity_version(row["metadata_json"]),
            )
        )


def downgrade() -> None:
    connection = op.get_bind()
    scans = _scan_table()
    rows = connection.execute(
        sa.select(scans.c.id, scans.c.criteria, scans.c.metadata_json)
    ).mappings()
    for row in rows:
        if not _owns_opportunity_version(row["metadata_json"]):
            continue
        connection.execute(
            scans.update()
            .where(scans.c.id == row["id"])
            .values(criteria=_with_opportunity_version(row["criteria"]))
        )
    with op.batch_alter_table("scans") as batch_op:
        batch_op.drop_column("metadata_json")
