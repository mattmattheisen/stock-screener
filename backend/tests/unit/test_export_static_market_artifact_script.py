from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_export_static_market_artifact_writes_status_and_preserves_exit_code(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.scripts import export_static_market_artifact

    forwarded_args = []

    def fake_export_main(argv):
        forwarded_args.extend(argv)
        return 79

    monkeypatch.setattr(export_static_market_artifact.export_static_site, "main", fake_export_main)

    result = export_static_market_artifact.main(
        [
            "--output-dir",
            str(tmp_path),
            "--refresh-daily",
            "--market",
            "CN",
        ]
    )

    assert result == 79
    assert forwarded_args == [
        "--output-dir",
        str(tmp_path),
        "--refresh-daily",
        "--market",
        "CN",
    ]
    assert json.loads((tmp_path / "status" / "cn" / "status.json").read_text()) == {
        "market": "CN",
        "has_current_artifact": False,
        "has_price_bundle": False,
        "status": "failed",
        "reason": "no_current_artifact",
    }


def test_export_static_market_artifact_blocks_price_bundle_for_price_coverage_gap(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.scripts import export_static_market_artifact

    def fake_export_main(_argv):
        diagnostics_dir = tmp_path / "diagnostics" / "de"
        diagnostics_dir.mkdir(parents=True)
        (diagnostics_dir / "snapshot-failure.json").write_text(
            json.dumps(
                {
                    "market": "DE",
                    "status": "skipped",
                    "reason": "market_rs_not_ready",
                    "failure_diagnostics": {
                        "reason_code": "current_adjusted_price_coverage_below_threshold",
                        "diagnostics": {
                            "current_price_coverage": 0.84,
                            "minimum_current_price_coverage": 0.88,
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        return export_static_market_artifact.export_static_site.STATIC_EXPORT_NO_CURRENT_ARTIFACT_EXIT_CODE

    monkeypatch.setattr(export_static_market_artifact.export_static_site, "main", fake_export_main)

    result = export_static_market_artifact.main(
        [
            "--output-dir",
            str(tmp_path),
            "--refresh-daily",
            "--market",
            "DE",
        ]
    )

    assert result == export_static_market_artifact.export_static_site.STATIC_EXPORT_NO_CURRENT_ARTIFACT_EXIT_CODE
    assert json.loads((tmp_path / "status" / "de" / "status.json").read_text())[
        "has_price_bundle"
    ] is False


def test_export_static_market_artifact_allows_price_bundle_for_exposure_soft_skip(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.scripts import export_static_market_artifact

    def fake_export_main(_argv):
        diagnostics_dir = tmp_path / "diagnostics" / "de"
        diagnostics_dir.mkdir(parents=True)
        (diagnostics_dir / "snapshot-failure.json").write_text(
            json.dumps(
                {
                    "market": "DE",
                    "status": "skipped",
                    "reason": "market_exposure_not_ready",
                    "failure_diagnostics": {"error": "market_breadth_not_ready"},
                }
            ),
            encoding="utf-8",
        )
        return export_static_market_artifact.export_static_site.STATIC_EXPORT_NO_CURRENT_ARTIFACT_EXIT_CODE

    monkeypatch.setattr(export_static_market_artifact.export_static_site, "main", fake_export_main)

    result = export_static_market_artifact.main(
        [
            "--output-dir",
            str(tmp_path),
            "--refresh-daily",
            "--market",
            "DE",
        ]
    )

    assert result == export_static_market_artifact.export_static_site.STATIC_EXPORT_NO_CURRENT_ARTIFACT_EXIT_CODE
    assert json.loads((tmp_path / "status" / "de" / "status.json").read_text())[
        "has_price_bundle"
    ] is True


@pytest.mark.parametrize("payload", [
    {
        "market": "DE",
        "status": "skipped",
        "failure_diagnostics": {"error": "missing reason"},
    },
    {
        "market": "DE",
        "status": "skipped",
        "reason": "new_unclassified_soft_skip",
        "failure_diagnostics": {"error": "unknown"},
    },
])
def test_export_static_market_artifact_blocks_price_bundle_for_unknown_soft_skip(
    monkeypatch,
    tmp_path: Path,
    payload: dict,
) -> None:
    from app.scripts import export_static_market_artifact

    def fake_export_main(_argv):
        diagnostics_dir = tmp_path / "diagnostics" / "de"
        diagnostics_dir.mkdir(parents=True)
        (diagnostics_dir / "snapshot-failure.json").write_text(
            json.dumps(payload),
            encoding="utf-8",
        )
        return export_static_market_artifact.export_static_site.STATIC_EXPORT_NO_CURRENT_ARTIFACT_EXIT_CODE

    monkeypatch.setattr(export_static_market_artifact.export_static_site, "main", fake_export_main)

    result = export_static_market_artifact.main(
        [
            "--output-dir",
            str(tmp_path),
            "--refresh-daily",
            "--market",
            "DE",
        ]
    )

    assert result == export_static_market_artifact.export_static_site.STATIC_EXPORT_NO_CURRENT_ARTIFACT_EXIT_CODE
    assert json.loads((tmp_path / "status" / "de" / "status.json").read_text())[
        "has_price_bundle"
    ] is False


def test_export_static_market_artifact_allows_price_bundle_for_benchmark_gap(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.scripts import export_static_market_artifact

    def fake_export_main(_argv):
        diagnostics_dir = tmp_path / "diagnostics" / "de"
        diagnostics_dir.mkdir(parents=True)
        (diagnostics_dir / "snapshot-failure.json").write_text(
            json.dumps(
                {
                    "market": "DE",
                    "status": "skipped",
                    "reason": "market_rs_not_ready",
                    "failure_diagnostics": {
                        "reason_code": "benchmark_adjusted_anchor_missing",
                        "diagnostics": {"date": "2026-08-03"},
                    },
                }
            ),
            encoding="utf-8",
        )
        return export_static_market_artifact.export_static_site.STATIC_EXPORT_NO_CURRENT_ARTIFACT_EXIT_CODE

    monkeypatch.setattr(export_static_market_artifact.export_static_site, "main", fake_export_main)

    result = export_static_market_artifact.main(
        [
            "--output-dir",
            str(tmp_path),
            "--refresh-daily",
            "--market",
            "DE",
        ]
    )

    assert result == export_static_market_artifact.export_static_site.STATIC_EXPORT_NO_CURRENT_ARTIFACT_EXIT_CODE
    assert json.loads((tmp_path / "status" / "de" / "status.json").read_text())[
        "has_price_bundle"
    ] is True


def test_export_static_market_artifact_writes_success_status(monkeypatch, tmp_path: Path) -> None:
    from app.scripts import export_static_market_artifact

    monkeypatch.setattr(export_static_market_artifact.export_static_site, "main", lambda argv: 0)

    result = export_static_market_artifact.main(
        [
            "--output-dir",
            str(tmp_path),
            "--market",
            "CN",
        ]
    )

    assert result == 0
    assert json.loads((tmp_path / "status" / "cn" / "status.json").read_text()) == {
        "market": "CN",
        "has_current_artifact": True,
        "has_price_bundle": True,
        "status": "published",
        "reason": None,
    }


def test_export_static_market_artifact_writes_skipped_status_for_not_trading_day(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.scripts import export_static_market_artifact

    monkeypatch.setattr(
        export_static_market_artifact.export_static_site,
        "main",
        lambda argv: export_static_market_artifact.export_static_site.STATIC_EXPORT_SKIPPED_EXIT_CODE,
    )

    result = export_static_market_artifact.main(
        [
            "--output-dir",
            str(tmp_path),
            "--market",
            "CN",
        ]
    )

    assert result == export_static_market_artifact.export_static_site.STATIC_EXPORT_SKIPPED_EXIT_CODE
    assert json.loads((tmp_path / "status" / "cn" / "status.json").read_text()) == {
        "market": "CN",
        "has_current_artifact": False,
        "has_price_bundle": False,
        "status": "skipped",
        "reason": "not_trading_day",
    }


def test_export_static_market_artifact_writes_failed_status_when_export_raises(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.scripts import export_static_market_artifact

    def fail_export(_argv):
        raise RuntimeError("boom")

    monkeypatch.setattr(export_static_market_artifact.export_static_site, "main", fail_export)

    with pytest.raises(RuntimeError, match="boom"):
        export_static_market_artifact.main(
            [
                "--output-dir",
                str(tmp_path),
                "--market",
                "CN",
            ]
        )

    assert json.loads((tmp_path / "status" / "cn" / "status.json").read_text()) == {
        "market": "CN",
        "has_current_artifact": False,
        "has_price_bundle": False,
        "status": "failed",
        "reason": "export_failed",
    }


def test_export_static_market_artifact_writes_failed_status_when_export_exits(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.scripts import export_static_market_artifact

    def exit_export(_argv):
        raise SystemExit("--combine-artifacts-dir cannot be used together with --refresh-daily")

    monkeypatch.setattr(export_static_market_artifact.export_static_site, "main", exit_export)

    with pytest.raises(SystemExit):
        export_static_market_artifact.main(
            [
                "--output-dir",
                str(tmp_path),
                "--market",
                "CN",
            ]
        )

    assert json.loads((tmp_path / "status" / "cn" / "status.json").read_text()) == {
        "market": "CN",
        "has_current_artifact": False,
        "has_price_bundle": False,
        "status": "failed",
        "reason": "export_failed",
    }
