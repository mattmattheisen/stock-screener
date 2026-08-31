from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.scripts.describe_static_breadth_contributor_metadata import (
    main as describe_main,
)
from app.scripts.restore_static_breadth_contributor_metadata import main as restore_main
from app.services.github_release_sync_service import (
    NamedAssetFetchResult,
    NamedAssetFetchStatus,
)
from app.services.static_breadth_contributor_metadata_contract import (
    build_static_breadth_contributor_metadata_plan,
)
from app.services.static_breadth_contributor_metadata_release import (
    StaticBreadthContributorMetadataReleaseRestorer,
    StaticBreadthContributorMetadataRestoreResult,
    StaticBreadthContributorMetadataRestoreStatus,
)


def test_metadata_release_restorer_retries_transient_failure(tmp_path):
    output_path = tmp_path / "breadth-contributor-metadata-us.json.gz"
    results = iter(
        [
            NamedAssetFetchResult(
                status=NamedAssetFetchStatus.NETWORK_ERROR,
                asset_name=output_path.name,
                error="temporary",
            ),
            NamedAssetFetchResult(
                status=NamedAssetFetchStatus.SUCCESS,
                asset_name=output_path.name,
                output_path=output_path,
            ),
        ]
    )
    calls: list[dict[str, object]] = []
    sleeps: list[float] = []

    def fetch(**kwargs):
        calls.append(kwargs)
        return next(results)

    restorer = StaticBreadthContributorMetadataReleaseRestorer(
        sync_service=SimpleNamespace(fetch_named_asset=fetch),
        sleep=sleeps.append,
    )

    restored = restorer.restore(
        repository_full_name="xang1234/stock-screener",
        release_tag="breadth-contributor-metadata-data",
        asset_name=output_path.name,
        output_path=output_path,
        github_token="token",
        request_timeout_seconds=60,
        attempts=3,
        retry_delay_seconds=2,
    )

    assert restored.status is StaticBreadthContributorMetadataRestoreStatus.RESTORED
    assert restored.safe_to_publish is True
    assert len(calls) == 2
    assert sleeps == [2]


def test_metadata_release_restorer_does_not_retry_missing_asset(tmp_path):
    output_path = tmp_path / "breadth-contributor-metadata-us.json.gz"
    calls = 0

    def fetch(**_kwargs):
        nonlocal calls
        calls += 1
        return NamedAssetFetchResult(
            status=NamedAssetFetchStatus.MISSING,
            asset_name=output_path.name,
            reason="not published yet",
        )

    restored = StaticBreadthContributorMetadataReleaseRestorer(
        sync_service=SimpleNamespace(fetch_named_asset=fetch),
        sleep=lambda _seconds: None,
    ).restore(
        repository_full_name="xang1234/stock-screener",
        release_tag="breadth-contributor-metadata-data",
        asset_name=output_path.name,
        output_path=output_path,
        github_token=None,
        request_timeout_seconds=60,
        attempts=3,
        retry_delay_seconds=2,
    )

    assert restored.status is StaticBreadthContributorMetadataRestoreStatus.MISSING
    assert restored.safe_to_publish is True
    assert calls == 1


@pytest.mark.parametrize(
    ("status", "expected_exit", "safe_to_publish"),
    [
        (StaticBreadthContributorMetadataRestoreStatus.RESTORED, 0, True),
        (StaticBreadthContributorMetadataRestoreStatus.MISSING, 0, True),
        (StaticBreadthContributorMetadataRestoreStatus.FAILED, 1, False),
    ],
)
def test_restore_metadata_cli_reports_publication_safety(
    tmp_path,
    capsys,
    status,
    expected_exit,
    safe_to_publish,
):
    output_path = tmp_path / "breadth-contributor-metadata-us.json.gz"
    calls: list[dict[str, object]] = []

    def restore(**kwargs):
        calls.append(kwargs)
        return StaticBreadthContributorMetadataRestoreResult(
            status=status,
            asset_name=output_path.name,
            output_path=output_path,
            detail="fixture",
        )

    exit_code = restore_main(
        [
            "--repository",
            "xang1234/stock-screener",
            "--asset-name",
            output_path.name,
            "--output-path",
            str(output_path),
            "--attempts",
            "2",
            "--retry-delay-seconds",
            "0",
        ],
        restorer=SimpleNamespace(restore=restore),
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == expected_exit
    assert payload == {
        "asset_name": output_path.name,
        "detail": "fixture",
        "output_path": str(output_path),
        "safe_to_publish": safe_to_publish,
        "status": status.value,
    }
    assert calls[0]["release_tag"] == "breadth-contributor-metadata-data"
    assert calls[0]["attempts"] == 2


def test_describe_metadata_cli_emits_canonical_plan(tmp_path, capsys):
    exit_code = describe_main(
        ["--market", "US", "--directory", str(tmp_path)]
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == (
        build_static_breadth_contributor_metadata_plan(
            market="US",
            directory=tmp_path,
        ).as_dict()
    )
