"""Local bridge for exported Unusual Whales MCP daily OHLC JSON.

The ChatGPT connector cannot automatically deliver its credentials to Codespaces.
Users can provide an authorized local JSON export without placing data in Git.
Only a quality report is printed; no historical rows are committed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .unusual_whales_adapter import adapt_daily_rows


def inspect_export(raw: object, ticker: str) -> dict:
    if isinstance(raw, list):
        records = raw
    elif isinstance(raw, dict):
        records = raw.get("result", raw.get("data"))
    else:
        records = None
    if not isinstance(records, list):
        raise ValueError("Expected a list or a result/data list")
    bars, report = adapt_daily_rows(records, ticker)
    report["sufficient_252_session_window"] = len(bars) >= 252
    report["sufficient_253_session_window"] = len(bars) >= 253
    report["missing_share_volume_rows"] = len(bars)
    report["price_only_52w_high_possible"] = len(bars) >= 252
    report["full_canslim_backtest_ready"] = False
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--ticker", required=True)
    args = parser.parse_args()
    raw = json.loads(args.input.read_text(encoding="utf-8"))
    print(json.dumps(inspect_export(raw, args.ticker), indent=2))


if __name__ == "__main__":
    main()
