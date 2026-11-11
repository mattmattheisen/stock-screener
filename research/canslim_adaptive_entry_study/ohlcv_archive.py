"""Research-only, dependency-free OHLCV archive importer.

Input: provider-exported CSV with columns
symbol,date,open,high,low,close,volume,adjustment_basis,source

The importer never fetches data, changes the scanner, or silently imputes bars.
Its output is a normalized CSV plus SHA-256 provenance manifest.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path

FIELDS = ("symbol", "date", "open", "high", "low", "close", "volume", "adjustment_basis", "source")
ALLOWED_BASIS = {"split_adjusted", "raw_as_traded", "total_return_adjusted"}


def normalize(rows):
    seen = set()
    output = []
    for line, row in enumerate(rows, start=2):
        if any(not str(row.get(key) or "").strip() for key in FIELDS):
            raise ValueError(f"line {line}: missing required value")
        symbol = row["symbol"].strip().upper()
        if not symbol or not all(ch.isalnum() or ch in ".-" for ch in symbol):
            raise ValueError(f"line {line}: invalid symbol")
        day = date.fromisoformat(row["date"].strip())
        basis = row["adjustment_basis"].strip()
        if basis not in ALLOWED_BASIS:
            raise ValueError(f"line {line}: unknown adjustment basis")
        source = row["source"].strip()
        prices = [float(row[k]) for k in ("open", "high", "low", "close")]
        volume_number = float(row["volume"])
        if any(not math.isfinite(v) or v <= 0 for v in prices):
            raise ValueError(f"line {line}: invalid price")
        if not math.isfinite(volume_number) or volume_number < 0 or not volume_number.is_integer():
            raise ValueError(f"line {line}: invalid volume")
        op, high, low, close = prices
        if low > min(op, close) or high < max(op, close) or low > high:
            raise ValueError(f"line {line}: inconsistent OHLC")
        key = (symbol, day.isoformat())
        if key in seen:
            raise ValueError(f"line {line}: duplicate symbol/date")
        seen.add(key)
        output.append(dict(symbol=symbol, date=day.isoformat(), open=op, high=high,
                           low=low, close=close, volume=int(volume_number),
                           adjustment_basis=basis, source=source))
    output.sort(key=lambda r: (r["symbol"], r["date"]))
    return output


def import_csv(input_path: Path, output_path: Path, manifest_path: Path):
    if output_path.exists() or manifest_path.exists():
        raise FileExistsError("Refusing to overwrite an existing research artifact")
    with input_path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or any(k not in reader.fieldnames for k in FIELDS):
            raise ValueError("CSV missing required columns")
        records = normalize(reader)
    if not records:
        raise ValueError("No OHLCV observations")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)
    digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
    manifest = dict(schema_version=1, generated_at=datetime.now(timezone.utc).isoformat(),
                    input_sha256=hashlib.sha256(input_path.read_bytes()).hexdigest(),
                    output_sha256=digest, rows=len(records),
                    symbols=len({r["symbol"] for r in records}),
                    first_date=min(r["date"] for r in records),
                    last_date=max(r["date"] for r in records),
                    adjustment_bases=sorted({r["adjustment_basis"] for r in records}),
                    sources=sorted({r["source"] for r in records}),
                    limitations=["No provider publication timestamp", "No delisted universe verification",
                                 "No historical fundamentals or licensed IBD RS",
                                 "No corporate-action reconciliation"])
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description="Validate and archive external OHLCV research CSV")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(import_csv(args.input, args.output, args.manifest), indent=2))


if __name__ == "__main__":
    main()
