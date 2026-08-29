import json

import pytest

from app.services.breadth.contributors import (
    BREADTH_CONTRIBUTOR_SIGNALS,
    CONTRIBUTOR_SCHEMA_ID,
)
from app.services.breadth.types import CURRENT_BREADTH_CALCULATION_REVISION
from app.services.static_breadth_contributor_asset_validator import (
    StaticBreadthContributorAssetError,
    validate_static_breadth_contributor_asset,
)


def _valid_asset(tmp_path):
    market_dir = tmp_path / "markets" / "us"
    contributor_dir = market_dir / "breadth" / "contributors"
    contributor_dir.mkdir(parents=True)
    calculation_date = "2026-08-28"
    index = {
        "schema": CONTRIBUTOR_SCHEMA_ID,
        "market": "US",
        "calculation_revision": CURRENT_BREADTH_CALCULATION_REVISION,
        "dates": [calculation_date],
    }
    breadth_row = {
        "date": calculation_date,
        **{
            definition.aggregate_field: 0
            for definition in BREADTH_CONTRIBUTOR_SIGNALS.values()
        },
    }
    breadth = {"payload": {"history_90d": [breadth_row]}}
    document = {
        "schema": CONTRIBUTOR_SCHEMA_ID,
        "market": "US",
        "date": calculation_date,
        "calculation_revision": CURRENT_BREADTH_CALCULATION_REVISION,
        "contributors": [],
    }
    paths = {
        "index": contributor_dir / "index.json",
        "breadth": market_dir / "breadth.json",
        "document": contributor_dir / f"{calculation_date}.json",
    }
    paths["index"].write_text(json.dumps(index), encoding="utf-8")
    paths["breadth"].write_text(json.dumps(breadth), encoding="utf-8")
    paths["document"].write_text(json.dumps(document), encoding="utf-8")
    descriptor = {
        "index_path": "markets/us/breadth/contributors/index.json",
    }
    return market_dir, descriptor, paths, index


@pytest.mark.parametrize(
    ("target", "malformed"),
    (
        ("index", "{"),
        ("index", "[]"),
        ("breadth", "[]"),
        ("document", "[]"),
    ),
)
def test_validator_normalizes_malformed_json_shapes(
    tmp_path,
    target,
    malformed,
):
    """Catches corrupt optional shards escaping the combiner boundary."""
    market_dir, descriptor, paths, _index = _valid_asset(tmp_path)
    paths[target].write_text(malformed, encoding="utf-8")

    with pytest.raises(StaticBreadthContributorAssetError):
        validate_static_breadth_contributor_asset(
            market="US",
            market_dir=market_dir,
            descriptor=descriptor,
        )


def test_validator_normalizes_mixed_type_index_dates(tmp_path):
    """Catches mixed date values raising TypeError during sorting."""
    market_dir, descriptor, paths, index = _valid_asset(tmp_path)
    index["dates"] = ["2026-08-28", 1]
    paths["index"].write_text(json.dumps(index), encoding="utf-8")

    with pytest.raises(StaticBreadthContributorAssetError):
        validate_static_breadth_contributor_asset(
            market="US",
            market_dir=market_dir,
            descriptor=descriptor,
        )


def test_validator_rejects_non_object_contributor_rows(tmp_path):
    market_dir, descriptor, paths, _index = _valid_asset(tmp_path)
    document = json.loads(paths["document"].read_text(encoding="utf-8"))
    document["contributors"] = [1]
    paths["document"].write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(
        StaticBreadthContributorAssetError,
        match="contributors are invalid",
    ):
        validate_static_breadth_contributor_asset(
            market="US",
            market_dir=market_dir,
            descriptor=descriptor,
        )


def test_validator_rejects_non_string_contributor_company_names(tmp_path):
    market_dir, descriptor, paths, _index = _valid_asset(tmp_path)
    document = json.loads(paths["document"].read_text(encoding="utf-8"))
    document["contributors"] = [
        {
            "symbol": "AAA",
            "company_name": {"unexpected": "object"},
            "daily_change_pct": 5,
            "signals": {"up_4pct": 5},
        }
    ]
    breadth = json.loads(paths["breadth"].read_text(encoding="utf-8"))
    breadth["payload"]["history_90d"][0]["stocks_up_4pct"] = 1
    paths["document"].write_text(json.dumps(document), encoding="utf-8")
    paths["breadth"].write_text(json.dumps(breadth), encoding="utf-8")

    with pytest.raises(
        StaticBreadthContributorAssetError,
        match="invalid contributors",
    ):
        validate_static_breadth_contributor_asset(
            market="US",
            market_dir=market_dir,
            descriptor=descriptor,
        )
