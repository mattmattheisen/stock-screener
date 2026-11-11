import csv
import json

import pytest

from research.canslim_adaptive_entry_study.ohlcv_archive import import_csv, normalize


def sample(**changes):
    row = dict(symbol="XYZ", date="2024-01-02", open="10", high="11", low="9",
               close="10.5", volume="1000", adjustment_basis="split_adjusted",
               source="research_export")
    row.update(changes)
    return row


def test_normalizes_and_sorts():
    records = normalize([sample(date="2024-01-03"), sample(date="2024-01-02")])
    assert [r["date"] for r in records] == ["2024-01-02", "2024-01-03"]


@pytest.mark.parametrize("change", [
    {"volume": "-1"}, {"close": "nan"}, {"high": "9"},
    {"adjustment_basis": "unknown"}, {"date": "2024-02-30"},
    {"source": ""}, {"volume": "1.5"}
])
def test_rejects_invalid_rows(change):
    with pytest.raises((ValueError, OverflowError)):
        normalize([sample(**change)])


def test_rejects_duplicate():
    with pytest.raises(ValueError, match="duplicate"):
        normalize([sample(), sample()])


def test_import_writes_hash_manifest_and_no_overwrite(tmp_path):
    inp, out, manifest = (tmp_path / name for name in ("input.csv", "bars.csv", "manifest.json"))
    with inp.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(sample()))
        writer.writeheader()
        writer.writerow(sample())
    summary = import_csv(inp, out, manifest)
    assert summary["rows"] == 1
    assert summary["symbols"] == 1
    assert len(summary["output_sha256"]) == 64
    assert json.loads(manifest.read_text())["output_sha256"] == summary["output_sha256"]
    with pytest.raises(FileExistsError):
        import_csv(inp, out, manifest)
