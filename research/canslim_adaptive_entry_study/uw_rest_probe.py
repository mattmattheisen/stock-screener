"""Research-only Unusual Whales REST OHLC probe and archival.

Requires an independently authorized UW REST API token in UW_API_KEY.
The ChatGPT Unusual Whales connection does not expose that credential to Codespaces.

No automatic backfill or trading. Probe one ticker and archive the raw response
with SHA-256 so provider fields and entitlement can be audited before ingestion.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def fetch(ticker: str, token: str, *, opener=urlopen, limit: int = 300) -> bytes:
    if not ticker or not ticker.isascii() or not ticker.replace(".", "").replace("-", "").isalnum():
        raise ValueError("Invalid ticker")
    if not token:
        raise ValueError("UW_API_KEY not configured")
    if not 1 <= limit <= 500:
        raise ValueError("Limit must be 1..500 for a conservative initial probe")
    url = f"https://api.unusualwhales.com/api/stock/{ticker.upper()}/ohlc/1d?limit={limit}"
    request = Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    try:
        with opener(request, timeout=30) as response:
            payload = response.read(15_000_001)
    except HTTPError as exc:
        # Never print request headers, token, or response bodies.
        raise RuntimeError(f"Unusual Whales returned HTTP {exc.code}") from None
    except URLError:
        raise RuntimeError("Unusual Whales connection failed") from None
    if len(payload) > 15_000_000:
        raise ValueError("Response exceeds 15 MB probe limit")
    parsed = json.loads(payload)
    if not isinstance(parsed, (list, dict)):
        raise ValueError("Unexpected provider JSON structure")
    return payload


def archive(ticker: str, raw: bytes, destination: Path) -> dict:
    if destination.exists():
        raise FileExistsError("Refusing to overwrite archived provider response")
    payload = json.loads(raw)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(raw)
    # Do not assume the REST endpoint has the same schema as the ChatGPT MCP tool.
    records = payload if isinstance(payload, list) else payload.get("data")
    first = records[0] if isinstance(records, list) and records else None
    keys = sorted(first) if isinstance(first, dict) else []
    return {"ticker": ticker.upper(), "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw), "records": len(records) if isinstance(records, list) else None,
            "sample_field_names": keys,
            "has_underlying_volume_field": "volume" in keys,
            "price_adjustment_verified": False,
            "backtest_ready": False}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", default="ANET")
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    token = os.environ.get("UW_API_KEY", "")
    raw = fetch(args.ticker, token, limit=args.limit)
    print(json.dumps(archive(args.ticker, raw, args.output), indent=2))


if __name__ == "__main__":
    main()
