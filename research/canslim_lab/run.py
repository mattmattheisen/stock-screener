"""Read-only CAN SLIM research from dated, normalized evidence."""
import argparse
import csv
import io
import json
from datetime import date, timedelta
from pathlib import Path
from statistics import mean, median

VERSION = "claude-research-1"
MOMENTUM = (
    "snapshot_date ticker close close_src rs_rating ad_rating comp_rating eps_rating ibd50_rank "
    "group_name group_rank other_lists sma21 sma50 pct_vs_sma21 pct_vs_sma50 "
    "pivot pivot_src pct_from_pivot ret_4w ret_13w ret_26w spx_ret_4w spx_ret_13w next_earnings ibd50_status verdict"
).split()
VERDICTS = (
    "signal_id version verdict_date ticker mode verdict price_at_verdict pivot "
    "invalidation market_state ret_4w ret_8w spx_ret_4w spx_ret_8w baseline_ret_4w baseline_ret_8w"
).split()


def pct(current, reference):
    if current is None or reference is None or reference <= 0:
        return None
    return round(100 * (current / reference - 1), 6)


def regime(market):
    indexes = [market.get(name, {}) for name in ("nasdaq", "sp500")]
    counts = [i.get("distribution_days") for i in indexes]
    reasons = []
    for name, index in zip(("Nasdaq Composite", "S&P 500"), indexes):
        if index.get("follow_through_failed") is True:
            reasons.append(f"{name} follow-through failed")
        if index.get("above_50") is False and (index.get("distribution_days") or 0) >= 6:
            reasons.append(f"{name} below 50-day with at least six distribution days")
    if market.get("vix_curve") == "backwardation" and market.get("credit_widening") is True:
        reasons.append("VIX backwardation with widening credit")
    if reasons:
        return "Correction", reasons
    for name, index in zip(("Nasdaq Composite", "S&P 500"), indexes):
        if (index.get("distribution_days") or 0) >= 5 or index.get("above_21") is False:
            reasons.append(f"{name} distribution or 21-day weakness")
    if market.get("breadth_trend") == "deteriorating":
        reasons.append("Deteriorating breadth")
    if market.get("vix_curve") in ("flattening", "backwardation"):
        reasons.append("VIX curve stress")
    if reasons:
        return "Uptrend Under Pressure", reasons
    if (
        any(i.get("follow_through_active") is True for i in indexes)
        and all(i.get("above_50") is True and i.get("above_21") is True for i in indexes)
        and all(c is not None and c < 5 for c in counts)
        and market.get("breadth_trend") in ("stable", "improving")
        and market.get("vix_curve") == "contango"
        and all(i.get("follow_through_failed") is False for i in indexes)
    ):
        return "Confirmed Uptrend", ["Index trend, follow-through, breadth and volatility agree"]
    return "Unconfirmed", ["Evidence does not establish a regime"]


def assess(stock, state, policy):
    grades = {letter: stock.get("grades", {}).get(letter, "n/a") for letter in "CANSI"}
    ibd = stock.get("ibd", {})
    if not ibd.get("source") or not ibd.get("as_of"):
        ibd = {}
    rs = ibd.get("rs_rating")
    leadership = stock.get("leadership", {})
    if leadership.get("rs_line_near_high") is False or leadership.get("outperforming_peers") in (0, 1, 2):
        grades["L"] = "Fail"
    elif rs is not None and rs < policy["rs_min"]:
        grades["L"] = "Fail"
    elif leadership.get("rs_line_near_high") is True and (leadership.get("outperforming_peers") or 0) >= 3:
        grades["L"] = "Pass" if rs is not None else "Provisional"
    else:
        grades["L"] = "n/a"

    eps, sales = stock.get("eps_growth"), stock.get("sales_growth")
    if eps is not None and sales is not None:
        grades["C"] = "Pass" if eps >= policy["eps_min"] and (
            sales >= policy["sales_min"] or stock.get("sales_accelerating") is True
        ) else "Fail"
    annual = stock.get("annual_eps_growth")
    if annual is not None and len(annual) == 3:
        grades["A"] = "Pass" if min(annual) >= policy["annual_min"] else "Fail"
    annual_pass = grades["A"] == "Pass" or (
        stock.get("young_company") is True and grades["N"] == "Pass" and bool(stock.get("catalyst"))
    )
    entry = stock.get("entry", stock.get("close"))
    pivot = stock.get("pivot")
    invalidation = stock.get("invalidation")
    distance = pct(stock.get("close"), pivot)
    invalidation_return = pct(invalidation, entry)
    downside = -invalidation_return if invalidation_return is not None else None
    vol = pct(stock.get("breakout_volume"), stock.get("prior_daily_volume_average"))
    grade_a = (
        grades["C"] == grades["L"] == grades["S"] == "Pass"
        and annual_pass and bool(stock.get("bear_case")) and vol is not None
        and vol >= policy["volume_min"]
    )
    market_allows = state == "Confirmed Uptrend" or (state == "Uptrend Under Pressure" and grade_a)
    early = stock.get("early_entry") or {}
    early_distance = pct(stock.get("close"), early.get("trigger"))
    early_ready = (
        distance is not None and distance < 0 and early_distance is not None
        and 0 <= early_distance <= policy["buy_zone"] and bool(early.get("confirmation_needed"))
        and bool(early.get("setup"))
    )
    confirmed_entry = distance is not None and 0 <= distance <= policy["buy_zone"]
    earnings = stock.get("earnings_sessions")
    earnings_ok = stock.get("earnings_risk_accepted") is True or (
        earnings is not None and earnings > policy["earnings_buffer"]
    )
    price_in_zone = pct(entry, early.get("trigger") if early_ready else pivot)
    missing = []
    for field, value in (
        ("pivot or close", distance), ("entry invalidation", downside), ("breakout volume", vol),
        ("earnings timing", earnings if not stock.get("earnings_risk_accepted") else True),
        ("C", None if grades["C"] == "n/a" else grades["C"]),
        ("A or young-company catalyst", None if grades["A"] == "n/a" and not annual_pass else True),
        ("L", None if grades["L"] in ("n/a", "Provisional") else grades["L"]),
    ):
        if value is None:
            missing.append(field)
    if (
        grades["C"] == "Fail" or grades["L"] == "Fail" or stock.get("failed_breakout") is True
        or stock.get("heavy_distribution") is True or (downside is not None and downside > 8)
    ):
        verdict = "Avoid"
    elif distance is not None and distance > policy["buy_zone"]:
        verdict = "Extended"
    elif (
        not missing and grades["C"] == grades["L"] == "Pass" and annual_pass
        and market_allows and earnings_ok and (confirmed_entry or early_ready)
        and price_in_zone is not None and 0 <= price_in_zone <= policy["buy_zone"]
        and downside is not None and 0 < downside <= 8 and vol >= policy["volume_min"]
        and stock.get("base") and stock.get("pivot_basis") and stock.get("bear_case")
        and stock.get("thesis_invalidation")
    ):
        verdict = "Actionable"
    else:
        verdict = "Watch"
    return dict(
        ticker=stock["ticker"], verdict=verdict, grades=grades, ibd=ibd,
        pct_from_pivot=distance, downside_pct=downside, breakout_volume_pct=vol,
        missing=missing, market_allows=market_allows, earnings_ok=earnings_ok,
        entry_type="early" if early_ready else "pivot", evidence=stock,
    )


def holding(stock, state):
    risk = pct(stock.get("close"), stock.get("actual_entry"))
    flags = stock.get("exit_flags", {})
    if (risk is not None and risk <= -8) or flags.get("failed_breakout") or flags.get("thesis_invalidated"):
        action, trigger = "Exit", "Reassess only after a new qualifying setup"
    elif state == "Correction" or flags.get("confirmed_50_break"):
        action, trigger = "Trim", "Exit on thesis invalidation or the initial-loss trigger"
    elif state in ("Uptrend Under Pressure", "Unconfirmed") or any(flags.get(k) for k in (
        "21_break", "50_break", "rs_falling", "ad_falling", "earnings_risk", "group_weakening"
    )):
        action, trigger = "Tighten", "Escalate after a confirmed 50-day break or failed breakout"
    elif risk is None:
        action, trigger = "Unconfirmed", "Supply the actual entry and current close"
    else:
        action, trigger = "Hold", "Review on a failed breakout or deterioration in price, earnings or leadership"
    actual_entry = stock.get("actual_entry")
    return dict(ticker=stock["ticker"], verdict=action, trigger=trigger, return_from_entry=risk,
                planned_initial_stop=round(actual_entry * .92, 6) if actual_entry and actual_entry > 0 else None,
                evidence=stock)


def csv_rows(rows, fields):
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows({key: "n/a" if row.get(key) is None else row[key] for key in fields} for row in rows)
    return output.getvalue()


def score(log, outcomes, as_of):
    """Use supplied point-in-time closes and matched baseline returns."""
    today = date.fromisoformat(as_of)
    summary = {}
    for weeks in (4, 8):
        for verdict in ("Actionable", "Watch", "Extended", "Avoid"):
            observations = {"spx": [], "baseline": []}
            count = 0
            for row in log:
                if row["verdict"] != verdict:
                    continue
                signal_date = date.fromisoformat(row["verdict_date"])
                maturity = signal_date + timedelta(weeks=weeks)
                if maturity > today:
                    continue
                observation = outcomes.get(row["signal_id"], {}).get(str(weeks), {})
                if observation:
                    observed = date.fromisoformat(observation["date"])
                    if not maturity <= observed <= today:
                        raise ValueError("Outcome date is outside the mature observation window")
                    if not observation.get("source"):
                        raise ValueError("An outcome requires its source")
                    price = row["price_at_verdict"]
                    row[f"ret_{weeks}w"] = pct(observation.get("close"), float(price) if price not in (None, "n/a") else None)
                    row[f"spx_ret_{weeks}w"] = observation.get("spx_return")
                    row[f"baseline_ret_{weeks}w"] = observation.get("matched_baseline_return")
                ret = row.get(f"ret_{weeks}w")
                if ret in (None, "n/a"):
                    continue
                count += 1
                for key, values in observations.items():
                    benchmark = row.get(f"{key}_ret_{weeks}w")
                    if benchmark not in (None, "n/a"):
                        values.append(float(ret) - float(benchmark))
            summary[f"{verdict}_{weeks}w"] = {
                "count": count,
                "comparisons": {
                    key: dict(count=len(values), mean_excess=mean(values), median_excess=median(values),
                              hit_rate=sum(value > 0 for value in values) / len(values),
                              sufficient_sample=len(values) >= 30)
                    if values else dict(count=0, sufficient_sample=False)
                    for key, values in observations.items()
                },
            }
    return summary


def run(mode, snapshot, momentum, log, ticker=None):
    as_of = snapshot["as_of"]
    date.fromisoformat(as_of)
    state, reasons = regime(snapshot.get("market", {}))
    permissions = {
        "Confirmed Uptrend": "New buys permitted",
        "Uptrend Under Pressure": "Only A-grade setups at reduced size",
        "Correction": "Watchlist only for new candidates",
        "Unconfirmed": "Wait for regime evidence",
    }
    result = dict(version=VERSION, as_of=as_of, data_inventory=snapshot.get("sources", {}),
                  prior_momentum_rows=len(momentum), prior_verdict_rows=len(log),
                  regime=state, reasons=reasons, permission=permissions[state],
                  market_evidence=snapshot.get("market", {}))
    if mode == "REGIME":
        return result
    if mode == "SCORE":
        result["score"] = score(log, snapshot.get("outcomes", {}), as_of)
        result["verdict_csv"] = csv_rows(log, VERDICTS)
        return result
    policy = dict(eps_min=25, sales_min=20, annual_min=25, rs_min=80,
                  volume_min=40, buy_zone=5, earnings_buffer=10)
    overrides = snapshot.get("research_defaults", {})
    if overrides.keys() - policy.keys():
        raise ValueError("Unknown research default")
    policy.update(overrides)
    result["research_defaults"] = policy
    stocks = snapshot.get("stocks", [])
    if len({s["ticker"] for s in stocks}) != len(stocks):
        raise ValueError("Duplicate tickers in snapshot")
    if mode == "DEEP-DIVE":
        stocks = [s for s in stocks if s["ticker"] == ticker]
        if not stocks:
            raise ValueError(f"{ticker} was not in the supplied snapshot")
    if mode == "HOLDING-REVIEW":
        stocks = [s for s in stocks if s.get("holding") is True]
    findings = []
    snapshots = {(r["ticker"], r["snapshot_date"]): r for r in momentum}
    signal_ids = {r["signal_id"] for r in log}
    for stock in stocks:
        symbol = stock["ticker"]
        finding = holding(stock, state) if mode == "HOLDING-REVIEW" else assess(stock, state, policy)
        ibd = stock.get("ibd", {})
        if not ibd.get("source") or not ibd.get("as_of"):
            ibd = {}
        row = {key: stock.get(key) for key in MOMENTUM}
        for key in ("rs_rating", "ad_rating", "comp_rating", "eps_rating", "ibd50_rank",
                    "group_name", "group_rank", "other_lists", "ibd50_status"):
            row[key] = ibd.get(key)
        row.update(snapshot_date=as_of, verdict=finding["verdict"],
                   pct_vs_sma21=pct(stock.get("close"), stock.get("sma21")),
                   pct_vs_sma50=pct(stock.get("close"), stock.get("sma50")),
                   pct_from_pivot=pct(stock.get("close"), stock.get("pivot")))
        prior = max((r for (s, d), r in snapshots.items() if s == symbol and d < as_of),
                    key=lambda r: r["snapshot_date"], default=None)
        if prior:
            finding["momentum_comparison"] = {
                "prior_date": prior["snapshot_date"], "current_date": as_of,
                "changes": {key: [prior.get(key), row.get(key)] for key in MOMENTUM[2:]
                            if str(prior.get(key) if prior.get(key) is not None else "n/a")
                            != str(row.get(key) if row.get(key) is not None else "n/a")},
            }
        snapshots[symbol, as_of] = row
        signal_id = f"{VERSION}|{as_of}|{symbol}|{mode}"
        if signal_id not in signal_ids:
            log.append(dict(signal_id=signal_id, version=VERSION, verdict_date=as_of, ticker=symbol,
                            mode=mode, verdict=finding["verdict"], price_at_verdict=stock.get("close"),
                            pivot=stock.get("pivot"), invalidation=stock.get("invalidation"), market_state=state))
        findings.append(finding)
    if mode == "SCREEN":
        order = {"Actionable": 0, "Watch": 1, "Extended": 2, "Avoid": 3}
        findings.sort(key=lambda f: (order[f["verdict"]],
                                     -sum(v == "Pass" for v in f["grades"].values()), f["ticker"]))
    result.update(findings=findings, momentum_csv=csv_rows(snapshots.values(), MOMENTUM),
                  verdict_csv=csv_rows(log, VERDICTS))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("REGIME", "SCREEN", "DEEP-DIVE", "HOLDING-REVIEW", "SCORE"))
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--ticker")
    parser.add_argument("--momentum", type=Path)
    parser.add_argument("--verdicts", type=Path)
    args = parser.parse_args()

    def read_csv(path):
        if path is None:
            return []
        with path.open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))

    try:
        snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
        result = run(args.mode, snapshot, read_csv(args.momentum), read_csv(args.verdicts), args.ticker)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
