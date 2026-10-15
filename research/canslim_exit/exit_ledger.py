"""Research-only CAN SLIM Exit Ledger. No trade execution or live feeds."""
import csv
import sys

WEIGHTS = {
    "below_ma21": 10, "below_ma50": 20, "heavy_ma50_break": 10,
    "rs_decline": 10, "rs_below_80": 10, "accdis_weakening": 10,
    "rank_decline": 5, "leadership_loss": 5, "group_weakening": 10,
    "failed_breakout": 15, "distribution": 15,
    "earnings_thesis_broken": 15, "risk_off": 10,
}

def number(row, key):
    value = row.get(key)
    return None if value is None or str(value).strip() == "" else float(value)

def flag(row, key):
    value = str(row.get(key, "")).strip().lower()
    if value in ("true", "yes", "1"):
        return True
    if value in ("false", "no", "0"):
        return False
    return None

def evaluate(row):
    """Compute observations without converting missing readings into HOLD."""
    close, entry = number(row, "close"), number(row, "entry_price")
    ma21, ma50 = number(row, "ma21"), number(row, "ma50")
    volume = number(row, "volume_ratio")
    def observed(*xs):
        return all(x is not None for x in xs)
    facts = {
        "below_ma21": (close < ma21) if observed(close, ma21) else None,
        "below_ma50": (close < ma50) if observed(close, ma50) else None,
        "heavy_ma50_break": (close < ma50 and volume >= 1.5) if observed(close, ma50, volume) else None,
        "group_weakening": flag(row, "group_weakening"),
        "failed_breakout": flag(row, "failed_breakout"),
        "earnings_thesis_broken": flag(row, "earnings_thesis_broken"),
        "risk_off": flag(row, "risk_off"),
    }
    comparisons = (
        ("rs_decline", "rs_change_3w", lambda x: x <= -5),
        ("rs_below_80", "rs_rating", lambda x: x < 80),
        ("accdis_weakening", "accdis_downgrades", lambda x: x >= 2),
        ("rank_decline", "rank_drop", lambda x: x >= 10),
        ("leadership_loss", "leadership_lists_lost", lambda x: x >= 2),
        ("distribution", "distribution_days", lambda x: x >= 2),
    )
    for key, field, test in comparisons:
        value = number(row, field)
        facts[key] = test(value) if value is not None else None
    raw = sum(WEIGHTS[k] for k, v in facts.items() if v is True)
    coverage = sum(WEIGHTS[k] for k, v in facts.items() if v is not None) / sum(WEIGHTS.values())
    stop = entry * 0.92 if entry is not None and entry > 0 else None
    breached = close <= stop if observed(close, stop) else None
    change = (close / entry - 1) * 100 if observed(close, entry) and entry > 0 else None
    peak, atr = number(row, "peak_close_since_entry"), number(row, "atr22")
    # Proxy only: standard Chandelier uses rolling highest HIGH, not highest close since entry.
    trail = peak - 3 * atr if observed(peak, atr) and atr > 0 else None
    if breached:
        state = "HARD STOP BREACH - REVIEW IMMEDIATELY"
    elif facts["failed_breakout"] is True and change is not None and change <= 0:
        state = "FAILED BREAKOUT - EXIT REVIEW"
    elif coverage < 0.75:
        state = "INSUFFICIENT DATA - MANUAL REVIEW"
    elif raw >= 65:
        state = "EXIT REVIEW"
    elif raw >= 50:
        state = "TRIM REVIEW"
    elif raw >= 35:
        state = "TIGHTEN REVIEW"
    elif raw >= 20:
        state = "WATCH"
    else:
        state = "HOLD - OBSERVED FACTORS ONLY"
    return {
        "symbol": row.get("symbol", ""),
        "data_as_of": row.get("data_as_of", ""),
        "entry_price": entry if entry is not None else "",
        "close": close if close is not None else "",
        "return_pct": round(change, 2) if change is not None else "",
        "initial_8pct_reference": round(stop, 2) if stop is not None else "",
        "stop_breached_at_close": breached if breached is not None else "",
        "chandelier_close_proxy": round(trail, 2) if trail is not None else "",
        "chandelier_proxy_breached": (close < trail) if observed(close, trail) else "",
        "raw_deterioration_score": raw,
        "indicator_coverage_pct": round(coverage * 100),
        "status": state,
        "triggered": "; ".join(k for k, v in facts.items() if v is True),
        "missing": "; ".join(k for k, v in facts.items() if v is None),
    }

def run(input_path, output_path):
    with open(input_path, newline="", encoding="utf-8-sig") as source:
        rows = list(csv.DictReader(source))
    if not rows:
        raise ValueError("No positions supplied")
    results = [evaluate(row) for row in rows]
    with open(output_path, "w", newline="", encoding="utf-8") as destination:
        writer = csv.DictWriter(destination, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)

if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python exit_ledger.py input.csv output.csv")
    run(sys.argv[1], sys.argv[2])
