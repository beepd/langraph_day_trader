"""
Blog step B3: the facts of ONE trading week, calculated in plain code, for the weekly blog post.

It builds on blog_facts.py: it collects the daily bundles of Monday to Friday (and of every earlier day, for the
"since the start" figures), then does all the weekly maths here. The model that writes the post only explains these
numbers; it never calculates anything.

    week_dates(any_date)          Monday..Friday of that week, and the Saturday the post is dated
    build_week_facts(...)         pure code: daily bundles in, weekly bundle out (no network, no database)
    collect_week_facts(any_date)  reads the database (select queries only) and builds the weekly bundle
    summary_text(facts)           a short readable summary, for checking by eye

Try it on a real week (reads only, writes nothing to the database):
    python blog_weekly.py 2026-10-10            prints a short summary (any date of that week works)
    python blog_weekly.py 2026-10-10 --json     also saves the full bundle as blog_weekly_2026-10-10.json

Definitions (kept in the bundle too, so the post can state them):
  * win rate       = winning trades / all completed trades. A trade with exactly 0 profit counts as "flat", not a win.
  * profit factor  = gross profit / gross loss. With no losing trade it is "not meaningful" (None), never infinity.
  * expectancy     = average gross P&L per completed trade.
  * R multiple     = a trade's P&L / the loss the plan risked at its stop (-1.0R means the stop was hit as planned).
  * max drawdown   = largest fall from a peak of the end-of-day balance (all trades close by 3:15 PM IST, so nothing is
                     carried overnight and there is no open-position value to add).
  * All P&L is GROSS: brokerage, taxes and slippage are not modelled yet.
A "setup" is the analyst's event type (earnings, order_win, ...). A group with fewer than 10 trades is flagged small_sample.
"""
import json
import logging
import sys
from datetime import date, datetime, timedelta, timezone

from blog_facts import GROUP_LABELS, KNOWN_LIMITATIONS, NOT_RECORDED, PNL_BASIS, _num, collect_day_facts, load_company_info

IST = timezone(timedelta(hours=5, minutes=30))
log = logging.getLogger("blog_weekly")

SMALL_SAMPLE = 10                  # fewer completed trades than this: do not read much into the numbers
TOLERANCE = 0.05                   # rupees; the books must agree to within 5 paise

DEFINITIONS = {
    "win_rate": "winning trades / all completed trades; a trade with exactly 0 profit is flat, not a win",
    "profit_factor": "gross profit / gross loss; not meaningful (None) when there is no losing trade",
    "expectancy": "average gross P&L per completed trade",
    "r_multiple": "trade P&L / the loss risked at the stop (-1.0R = stopped out as planned)",
    "max_drawdown": "largest fall from a peak of the end-of-day balance (nothing is carried overnight)",
    "setup": "the analyst's event type for the stock",
}


# ------------------------------------------------------------------------------ the week
def week_dates(any_date: date):
    """(the five weekdays Monday..Friday of the week holding any_date, the Saturday the post is dated).
    A Saturday or Sunday belongs to the week that just ended."""
    monday = any_date - timedelta(days=any_date.weekday())
    return [monday + timedelta(days=i) for i in range(5)], monday + timedelta(days=5)


# ------------------------------------------------------------------------------ the maths (pure code)
def _trade_records(bundles: list) -> list:
    """One flat record per completed trade (a bought stock whose result is known), oldest first."""
    records = []
    for b in sorted(bundles, key=lambda b: b["market_date"]):
        for t in b["trades"]:
            r = t.get("result")
            if r is None or r.get("pnl") is None:
                continue
            records.append({"date": b["market_date"], "symbol": t["symbol"], "sector": t.get("sector"),
                            "setup": (t.get("analyst") or {}).get("event_type") or "unknown",
                            "outcome": r["outcome"], "pnl": r["pnl"], "r_multiple": r.get("r_multiple"),
                            "reason": (t.get("analyst") or {}).get("reason")})
    return records


def _trade_stats(records: list) -> dict:
    pnls = [r["pnl"] for r in records]
    wins, losses = [p for p in pnls if p > 0], [p for p in pnls if p < 0]
    n, gross_profit, gross_loss = len(pnls), sum(wins), -sum(losses)
    rs = [r["r_multiple"] for r in records if r["r_multiple"] is not None]
    if gross_loss > 0:
        factor, note = _num(gross_profit / gross_loss), None
    else:
        factor, note = None, "no trades" if n == 0 else "no losing trade, so a profit factor is not meaningful"
    return {"trades": n, "winners": len(wins), "losers": len(losses), "flat": n - len(wins) - len(losses),
            "win_rate_pct": _num(len(wins) / n * 100, 1) if n else None,
            "gross_profit": _num(gross_profit), "gross_loss": _num(gross_loss), "net_pnl_gross": _num(sum(pnls)),
            "avg_win": _num(gross_profit / len(wins)) if wins else None,
            "avg_loss": _num(gross_loss / len(losses)) if losses else None,
            "expectancy_per_trade": _num(sum(pnls) / n) if n else None,
            "avg_r_multiple": _num(sum(rs) / len(rs)) if rs else None,
            "profit_factor": factor, "profit_factor_note": note,
            "exits": {k: sum(1 for r in records if r["outcome"] == k) for k in ("target_hit", "stop_hit", "closed_at_end")},
            "best_trade": _pick(records, max), "worst_trade": _pick(records, min),
            "small_sample": n < SMALL_SAMPLE}


def _pick(records: list, chooser):
    """The trade with the highest (max) or lowest (min) P&L; the worst one may still be a win in a good week."""
    return dict(chooser(records, key=lambda r: r["pnl"])) if records else None


def _equity_stats(bundles: list):
    days = sorted((b for b in bundles if b["money"]), key=lambda b: b["market_date"])
    if not days:
        return None
    start, end = days[0]["money"]["starting_balance"], days[-1]["money"]["ending_balance"]
    peak, worst_pct, worst_rs = start, 0.0, 0.0
    for d in days:
        balance = d["money"]["ending_balance"]
        peak = max(peak, balance)
        drop = peak - balance
        if peak and drop / peak * 100 > worst_pct:
            worst_pct, worst_rs = drop / peak * 100, drop
    return {"first_day": days[0]["market_date"], "last_day": days[-1]["market_date"], "trading_days": len(days),
            "starting_balance": _num(start), "ending_balance": _num(end), "pnl_gross": _num(end - start),
            "return_pct": _num((end - start) / start * 100) if start else None,
            "max_drawdown_pct": _num(worst_pct), "max_drawdown_rs": _num(worst_rs)}


def _setups(records: list) -> list:
    groups = {}
    for r in records:
        groups.setdefault(r["setup"], []).append(r)
    out = []
    for setup, rows in groups.items():
        pnls = [r["pnl"] for r in rows]
        wins = sum(1 for p in pnls if p > 0)
        out.append({"setup": setup, "trades": len(rows), "winners": wins,
                    "win_rate_pct": _num(wins / len(rows) * 100, 1), "net_pnl_gross": _num(sum(pnls)),
                    "avg_pnl_per_trade": _num(sum(pnls) / len(rows)), "small_sample": len(rows) < SMALL_SAMPLE})
    return sorted(out, key=lambda s: (-s["trades"], s["setup"]))


def _report_card(bundles: list) -> dict:
    """Did the analyst's picks do better than the rest? Every candidate of the period, by group, until the close."""
    groups = {}
    for b in bundles:
        for stock in b["trades"] + b["others"]:
            groups.setdefault(stock["group"], []).append(stock.get("until_close"))
    avg = lambda values: round(sum(values) / len(values), 2) if values else None
    card = {}
    for group, rows in groups.items():
        graded = [o for o in rows if o is not None]
        card[group] = {"label": GROUP_LABELS[group], "stocks": len(rows), "graded": len(graded),
                       "avg_return_to_close_pct": avg([o["return_pct"] for o in graded if o["return_pct"] is not None]),
                       "avg_whatif_trade_pct": avg([o["whatif_return_pct"] for o in graded if o["whatif_return_pct"] is not None])}
    return card


def _period(bundles: list) -> dict:
    records = _trade_records(bundles)
    return {"equity": _equity_stats(bundles), "trades": _trade_stats(records),
            "setups": _setups(records), "report_card": _report_card(bundles)}


def _behaviour(week: list):
    """How the APP behaved over the week: the daily 'app_behaviour' counts added up (None if no day ran)."""
    days = [b for b in week if b.get("app_behaviour")]
    if not days:
        return None
    total = lambda *path: sum(_dig(b["app_behaviour"], path) for b in days)
    return {
        "days_covered": len(days),
        "analyst_mode_by_day": {b["market_date"]: b["app_behaviour"]["analyst"]["mode"] for b in days},
        "candidates": {"total": total("candidates", "total"), "without_headlines": total("candidates", "without_headlines")},
        "analyst": {k: total("analyst", k) for k in ("judged", "strong", "on_watchlist", "overruled_by_code", "strong_but_dropped")},
        "planner": {**{k: total("planner", k) for k in ("accepted", "rejected", "skipped", "nudged")},
                    "rejected_reasons": [{"date": b["market_date"], **r} for b in days for r in b["app_behaviour"]["planner"]["rejected_reasons"]]},
        "positions": {**{k: total("positions", k) for k in ("target_hits", "stop_hits", "stop_hits_within_60_min", "closed_at_end")},
                      "same_sector_days": [{"date": b["market_date"], "sector": sector, "trades": rows,
                                            "pnl_total": b["app_behaviour"]["positions"]["same_sector_pnl"][sector]}
                                           for b in days for sector, rows in b["app_behaviour"]["positions"]["same_sector"].items()],
                      "same_sector_pnl_total": round(sum(v for b in days for v in b["app_behaviour"]["positions"]["same_sector_pnl"].values()), 2)},
        "known_limitations": list(KNOWN_LIMITATIONS),
    }


def _dig(data: dict, path: tuple):
    for key in path:
        data = data[key]
    return data


def _day_row(b: dict) -> dict:
    m, c = b["money"], b["counts"]
    return {"date": b["market_date"], "weekday": b["weekday"], "status": b["day_status"], "note": b["note"],
            "trades": c["trades"], "winners": c["winners"], "losers": c["losers"],
            "pnl_gross": m["pnl"] if m else None, "pnl_pct_of_start": m["pnl_pct_of_start"] if m else None,
            "ending_balance": m["ending_balance"] if m else None, "nifty_move_pct": m["nifty_move_pct"] if m else None}


def _warnings(days: list, bundles: dict, history: list, today: date) -> list:
    """Anything that makes the week's numbers unreliable. A report with warnings should be checked before publishing."""
    out = []
    for d in days:
        b = bundles[d.isoformat()]
        if d > today:
            out.append(f"{d} has not happened yet: the week is not finished")
        elif b["day_status"] == "no_run":
            out.append(f"{d}: no run recorded (a holiday that was not listed, or the app did not run)")
        elif b["day_status"] == "failed":
            out.append(f"{d}: the morning run failed")
        elif b["day_status"] == "not_settled_yet":
            out.append(f"{d}: the run exists but the day is not settled yet")
        if b["money"]:
            m = b["money"]
            traded = round(sum(t["result"]["pnl"] for t in b["trades"] if t["result"] and t["result"]["pnl"] is not None), 2)
            if abs(traded - m["pnl"]) > TOLERANCE:
                out.append(f"{d}: the trades add up to {traded} but the day's P&L is {m['pnl']}")
            if abs((m["ending_balance"] - m["starting_balance"]) - m["pnl"]) > TOLERANCE:
                out.append(f"{d}: ending minus starting balance does not equal the day's P&L")
    in_week = {d.isoformat() for d in days}
    money_days = sorted((b for b in history if b["money"]), key=lambda b: b["market_date"])
    for earlier, later in zip(money_days, money_days[1:]):
        if later["market_date"] in in_week and abs(earlier["money"]["ending_balance"] - later["money"]["starting_balance"]) > TOLERANCE:
            out.append(f"{later['market_date']}: starting balance differs from the ending balance of {earlier['market_date']}")
    return out


def build_week_facts(days: list, post_date: date, history: list, today: date) -> dict:
    """days = the five weekdays; history = daily bundles (blog_facts) of those days AND of every earlier day."""
    by_date = {b["market_date"]: b for b in history}
    stub = lambda d: {"market_date": d.isoformat(), "weekday": d.strftime("%A"), "day_status": "no_run", "note": None,
                      "money": None, "trades": [], "others": [], "counts": {"trades": 0, "winners": 0, "losers": 0, "flat": 0}}
    week = [by_date.get(d.isoformat()) or stub(d) for d in days]
    everything = [b for b in history if b["market_date"] <= days[-1].isoformat()]
    warnings = _warnings(days, {b["market_date"]: b for b in week}, everything, today)
    session_days = [b["market_date"] for b in week if b["money"]]
    return {"kind": "weekly", "market_date": post_date.isoformat(), "weekday": post_date.strftime("%A"),
            "week_start": days[0].isoformat(), "week_end": days[-1].isoformat(),
            "last_session": session_days[-1] if session_days else None,
            "pnl_basis": PNL_BASIS, "definitions": DEFINITIONS,
            "days": [_day_row(b) for b in week],
            "week": _period(week), "cumulative": _period(everything), "app_behaviour": _behaviour(week),
            "warnings": warnings, "complete": not warnings,
            "not_recorded": list(NOT_RECORDED)}


# ------------------------------------------------------------------------------ reading the database
def collect_week_facts(any_date: date, client=None, info: dict | None = None, today: date | None = None) -> dict:
    """The weekly bundle for the week holding any_date. Safe to call any time: it only reads."""
    if client is None:
        from storage import get_client                      # imported here so the pure part needs no database library
        client = get_client()
    if info is None:
        info = load_company_info()
    days, post_date = week_dates(any_date)
    settled = [date.fromisoformat(r["market_date"]) for r in client.table("daily_equity").select("market_date").execute().data]
    wanted = sorted({d for d in settled if d <= days[-1]} | set(days))
    history = [collect_day_facts(d, client, info) for d in wanted]
    return build_week_facts(days, post_date, history, today or datetime.now(IST).date())


# ------------------------------------------------------------------------------ a short summary, and a command line
def _trade_line(label: str, t) -> str:
    return f"{label}: none" if t is None else f"{label}: {t['symbol']} on {t['date']} {t['outcome']} {t['pnl']:+,.2f} ({t['r_multiple']}R, {t['setup']})"


def summary_text(facts: dict) -> str:
    lines = [f"Week {facts['week_start']} to {facts['week_end']} (post dated {facts['market_date']}, {facts['weekday']}); "
             f"complete: {facts['complete']}"]
    lines += [f"  WARNING: {w}" for w in facts["warnings"]]
    for d in facts["days"]:
        money = "" if d["pnl_gross"] is None else f" pnl {d['pnl_gross']:+,.2f} ({d['pnl_pct_of_start']:+.2f}%), Nifty {d['nifty_move_pct']}%"
        lines.append(f"  {d['date']} {d['weekday'][:3]} {d['status']}: {d['trades']} trade(s), {d['winners']} won, {d['losers']} lost{money}"
                     + (f" [{d['note']}]" if d["note"] else ""))
    for name in ("week", "cumulative"):
        p = facts[name]
        e, t = p["equity"], p["trades"]
        lines.append(f"{name.upper()} (gross):")
        if e is None:
            lines.append("  no settled days")
            continue
        lines.append(f"  balance {e['starting_balance']:,.2f} -> {e['ending_balance']:,.2f}  pnl {e['pnl_gross']:+,.2f} ({e['return_pct']:+.2f}%), "
                     f"max drawdown {e['max_drawdown_pct']}% (Rs {e['max_drawdown_rs']:,.2f}), {e['trading_days']} day(s) from {e['first_day']}")
        lines.append(f"  trades {t['trades']}: {t['winners']} won, {t['losers']} lost, {t['flat']} flat, win rate {t['win_rate_pct']}%, "
                     f"profit factor {t['profit_factor'] if t['profit_factor'] is not None else 'n/a'}, expectancy {t['expectancy_per_trade']}/trade, "
                     f"avg R {t['avg_r_multiple']}" + (", SMALL SAMPLE" if t["small_sample"] else ""))
        lines.append(f"  exits {t['exits']}")
        lines.append("  " + _trade_line("best", t["best_trade"]))
        lines.append("  " + _trade_line("worst", t["worst_trade"]))
        for s in p["setups"]:
            lines.append(f"  setup {s['setup']}: {s['trades']} trade(s), win rate {s['win_rate_pct']}%, pnl {s['net_pnl_gross']:+,.2f}")
        for g, row in p["report_card"].items():
            lines.append(f"  report card - {g}: {row['stocks']} stock(s), avg to close {row['avg_return_to_close_pct']}%, what-if {row['avg_whatif_trade_pct']}%")
    a = facts.get("app_behaviour")
    if a:
        lines.append("APP BEHAVIOUR (week):")
        lines.append(f"  analyst modes: {sorted(set(a['analyst_mode_by_day'].values()))}; {a['candidates']['without_headlines']} of {a['candidates']['total']} candidates had no headlines; "
                     f"judged {a['analyst']['judged']}, strong {a['analyst']['strong']}, overruled by code {a['analyst']['overruled_by_code']}, strong but dropped {a['analyst']['strong_but_dropped']}")
        lines.append(f"  planner: accepted {a['planner']['accepted']}, rejected {a['planner']['rejected']}, skipped {a['planner']['skipped']}, nudged {a['planner']['nudged']}")
        p = a["positions"]
        lines.append(f"  stops {p['stop_hits']} ({p['stop_hits_within_60_min']} within 60 min), targets {p['target_hits']}, 3:15 closes {p['closed_at_end']}")
        for d in p["same_sector_days"]:
            lines.append(f"  same sector on {d['date']}: {d['sector']} " + ", ".join(f"{t['symbol']} {t['outcome']}" for t in d["trades"])
                         + f" (together {d['pnl_total']:+,.2f})")
    return "\n".join(lines)


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        raise SystemExit("Usage: python blog_weekly.py YYYY-MM-DD [--json]   (any date inside the week)")
    any_date = date.fromisoformat(args[0])
    facts = collect_week_facts(any_date)
    print(summary_text(facts))
    if "--json" in sys.argv:
        path = f"blog_weekly_{facts['market_date']}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(facts, f, indent=2, ensure_ascii=False)
        print(f"full bundle saved to {path}")


if __name__ == "__main__":
    main()
