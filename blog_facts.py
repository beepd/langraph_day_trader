"""
Blog step B2: gather the facts of ONE trading day into one plain bundle (a dict) for the blog writer.

Why this is its own file: the model that writes the post must never see the database and must never do any maths.
This file reads the saved rows, does every calculation in plain code, and hands over a bundle of finished facts.
(Think of it as the DTO the writer receives, built by a service layer.) The same bundle is saved with the post
(blog_posts.facts_used), so every number in a post can be traced and checked later.

Two parts, so each can be tested alone:
    fetch_day_rows(client, day)      the only part that talks to the database (select queries only, it never writes)
    build_day_facts(raw, info)       pure code: raw rows in, finished bundle out (no network, no database)
    collect_day_facts(day)           the two together
    summary_text(facts)              a short, readable summary of a bundle (for checking it by eye)

Try it on a real day (reads only, writes nothing to the database):
    python blog_facts.py 2026-10-09            prints a short summary
    python blog_facts.py 2026-10-09 --json     also saves the full bundle as blog_facts_2026-10-09.json

What the bundle says plainly when something was NOT recorded (see NOT_RECORDED), so the writer cannot invent it.
All P&L here is GROSS: brokerage, taxes and slippage are not modelled yet.
"""
import csv
import json
import logging
import sys
from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
log = logging.getLogger("blog_facts")

PNL_BASIS = "gross: before brokerage, taxes and slippage (none of these are modelled yet)"

# Things a trading-journal reader may expect that this app does NOT record. The writer is told to say so, not to guess.
NOT_RECORDED = [
    "Bank Nifty, market breadth and any news beyond the saved headlines",
    "chart patterns and intraday price levels (stops, targets and exits are rule-based)",
    "any reasoning beyond the recorded analyst and planner reasons",
    "brokerage, taxes and slippage (all P&L is gross)",
]

GROUP_LABELS = {
    "bought": "strong catalyst, bought",
    "strong_not_bought": "strong catalyst, on the watchlist but not bought",
    "strong_dropped": "strong by the rules, dropped (not on the watchlist, for example the one-per-sector rule)",
    "weak_catalyst": "catalyst judged weak or not bullish",
    "no_catalyst": "no catalyst",
}

NUDGE_MARK = "[adjusted by the rulebook"          # morning_run.py puts this at the start of a plan's reason when it nudged a stop or target
QUICK_STOP_MINUTES = 60                          # a stop hit within this many minutes of entry counts as a quick stop-out

# The app's own known weaknesses (from the README), so the writer discusses real ones instead of inventing any.
KNOWN_LIMITATIONS = [
    "the analyst reads headline titles only; the article text behind them is not read yet",
    "the day's positions are chosen by screener rank, not by the model",
    "stops and targets are filled at exactly their price; brokerage, taxes and slippage are ignored",
    "market holidays must be listed by hand (a backup check records a skipped day)",
    "stocks in one sector often move on the same story, so several can hit their stops together",
    "a few days of results prove nothing: luck can look like skill",
]


# ------------------------------------------------------------------------------ small helpers
def load_company_info(path: str = "nifty100.csv") -> dict:
    """symbol -> {'company', 'sector'} from the Nifty 100 file."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        return {row["Symbol"].strip(): {"company": row["Company Name"].strip(), "sector": row["Industry"].strip()}
                for row in csv.DictReader(f)}


def _num(value, digits: int = 2):
    return None if value is None else round(float(value), digits)


def _ist(value):
    """A database timestamp (text) as an India-time datetime, or None."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(IST)
    except ValueError:
        return None


def _avg(values):
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 2) if values else None


# ------------------------------------------------------------------------------ part 1: read the database
def _pick_official(runs: list):
    """The day's official run, with the same preference as the database view: a real (finished, live) run beats a skip,
    a skip beats a failure; within a kind the latest run wins. Runs still 'running' and non-live runs are ignored."""
    def rank(run):
        if run["status"] == "finished" and run.get("data_is_live"):
            return 0
        return {"skipped": 1, "failed": 2}.get(run["status"])
    usable = [r for r in runs if rank(r) is not None]
    return min(usable, key=lambda r: (rank(r), -r["id"])) if usable else None


def fetch_day_rows(client, market_date: date) -> dict:
    """Read every row the bundle needs for one day. Select queries only: this never writes anything."""
    day = market_date.isoformat()
    runs = client.table("runs").select("*").eq("market_date", day).execute().data
    run = _pick_official(runs)
    equity = client.table("daily_equity").select("*").eq("market_date", day).execute().data
    raw = {"market_date": day, "run": run, "equity": equity[0] if equity else None,
           "candidates": [], "headlines": [], "verdicts": [], "plans": [], "results": [], "outcomes": []}
    if run is None or run["status"] != "finished":
        return raw
    for key, table in (("candidates", "candidates"), ("headlines", "headlines"),
                       ("verdicts", "verdicts"), ("plans", "plans")):
        raw[key] = client.table(table).select("*").eq("run_id", run["id"]).execute().data
    plan_ids = [p["id"] for p in raw["plans"]]
    if plan_ids:
        raw["results"] = client.table("trade_results").select("*").in_("plan_id", plan_ids).execute().data
    try:
        raw["outcomes"] = client.table("candidate_outcomes").select("*").eq("run_id", run["id"]).execute().data
    except Exception as error:                      # an older database may not have the report-card table yet
        log.warning("Could not read the report card for %s: %s", day, error)
    return raw


# ------------------------------------------------------------------------------ part 2: build the bundle (pure code)
def _cited_headlines(headlines: list, symbol: str, positions) -> list:
    wanted = set(positions or [])
    out = []
    for h in sorted((h for h in headlines if h["symbol"] == symbol and h["position"] in wanted),
                    key=lambda h: h["position"]):
        published = _ist(h.get("published_at"))
        out.append({"number": h["position"], "date": published.date().isoformat() if published else None,
                    "source": h.get("source"), "title": h["title"]})
    return out


def _group(is_bought: bool, verdict: dict | None) -> str:
    if is_bought:
        return "bought"
    v = verdict or {}
    if v.get("on_watchlist"):
        return "strong_not_bought"
    if v.get("strength") == "strong":
        return "strong_dropped"
    if v.get("has_catalyst"):
        return "weak_catalyst"
    return "no_catalyst"


def _analyst(v: dict | None) -> dict | None:
    if v is None:
        return None
    return {"has_catalyst": v.get("has_catalyst"), "bullish": v.get("bullish"), "strength": v.get("strength"),
            "event_type": v.get("catalyst_type"), "event_status": v.get("event_status"),   # status: checklist mode only
            "has_number": v.get("has_number"), "reason": v.get("reason"), "notes": v.get("checklist_notes"),
            "overruled_by_code": v.get("overruled_by_code")}


def _until_close(o: dict | None) -> dict | None:
    if o is None:
        return None
    return {"return_pct": _num(o.get("return_pct")), "max_up_pct": _num(o.get("max_up_pct")),
            "max_down_pct": _num(o.get("max_down_pct")), "whatif_outcome": o.get("std_outcome"),
            "whatif_return_pct": _num(o.get("std_return_pct"))}


def _behaviour(raw: dict, facts: dict, verdicts: dict) -> dict:
    """How the APP behaved today (not how the stocks did): plain counts the writer can base 'what to improve' on."""
    with_headlines = {h["symbol"] for h in raw["headlines"]}
    plans = raw["plans"]
    rejected = [p for p in plans if p["status"] == "rejected"]
    nudged = [p for p in plans if p["status"] in ("accepted", "rejected") and (p.get("gemini_reason") or "").startswith(NUDGE_MARK)]
    by_sector = {}
    for t in facts["trades"]:
        if t.get("sector"):
            by_sector.setdefault(t["sector"], []).append(t)
    same_sector = {sector: [{"symbol": t["symbol"], "outcome": (t["result"] or {}).get("outcome"), "pnl": (t["result"] or {}).get("pnl")}
                            for t in ts] for sector, ts in by_sector.items() if len(ts) > 1}
    done = [t["result"] for t in facts["trades"] if t["result"]]
    stops = [r for r in done if r["outcome"] == "stop_hit"]
    return {
        "candidates": {"total": len(raw["candidates"]),
                       "without_headlines": sum(1 for c in raw["candidates"] if c["symbol"] not in with_headlines)},
        "analyst": {"mode": facts["run"]["analyst_mode"], "judged": len(verdicts),
                    "strong": sum(1 for v in verdicts.values() if v.get("strength") == "strong"),
                    "on_watchlist": sum(1 for v in verdicts.values() if v.get("on_watchlist")),
                    "overruled_by_code": sum(1 for v in verdicts.values() if v.get("overruled_by_code")),
                    "strong_but_dropped": sum(1 for o in facts["others"] if o["group"] == "strong_dropped")},
        "planner": {"accepted": sum(1 for p in plans if p["status"] == "accepted"), "rejected": len(rejected),
                    "skipped": sum(1 for p in plans if p["status"] == "skipped"), "nudged": len(nudged),
                    "rejected_reasons": [{"symbol": p["symbol"], "reason": (p.get("rejection_reason") or "")[:140]} for p in rejected]},
        "positions": {"target_hits": sum(1 for r in done if r["outcome"] == "target_hit"), "stop_hits": len(stops),
                      "stop_hits_within_60_min": sum(1 for r in stops if r.get("minutes_in_trade") is not None
                                                     and r["minutes_in_trade"] <= QUICK_STOP_MINUTES),
                      "closed_at_end": sum(1 for r in done if r["outcome"] == "closed_at_end"),
                      "same_sector": same_sector},
        "known_limitations": list(KNOWN_LIMITATIONS),
    }


def build_day_facts(raw: dict, info: dict | None = None) -> dict:
    """Raw rows in, the finished fact bundle out. `info` is symbol -> {'company', 'sector'} (see load_company_info)."""
    info = info or {}
    day = date.fromisoformat(raw["market_date"])
    run, equity = raw["run"], raw["equity"]
    facts = {"kind": "daily", "market_date": raw["market_date"], "weekday": day.strftime("%A"),
             "day_status": None, "note": None, "pnl_basis": PNL_BASIS,
             "run": None, "money": None, "trades": [], "others": [], "report_card": {},
             "counts": {"trades": 0, "winners": 0, "losers": 0, "flat": 0}, "app_behaviour": None,
             "not_recorded": list(NOT_RECORDED)}

    # --- what kind of day was it?
    if run is None:
        facts["day_status"] = "no_run"                   # weekend, or nothing recorded
        return facts
    facts["note"] = run.get("note")
    if run["status"] in ("skipped", "failed"):           # the error text of a failed run is deliberately not passed on
        facts["day_status"] = run["status"]
        return facts

    settings = run.get("settings") or {}
    started = _ist(run.get("started_at"))
    facts["run"] = {"model": run.get("model_name"), "analyst_mode": settings.get("analyst_mode", "classic"),
                    "started_at_ist": started.strftime("%H:%M") if started else None,
                    "stocks_checked": run.get("universe_size"), "passed_screen": run.get("passed_screen"),
                    "balance_at_start": _num(settings.get("balance_at_start"))}

    verdicts = {v["symbol"]: v for v in raw["verdicts"]}
    plans = {p["symbol"]: p for p in raw["plans"]}
    results = {r["plan_id"]: r for r in raw["results"]}
    outcomes = {o["symbol"]: o for o in raw["outcomes"]}
    accepted = {s for s, p in plans.items() if p["status"] == "accepted"}

    if equity is not None:
        start, pnl = float(equity["starting_balance"]), float(equity["pnl"])
        facts["money"] = {"starting_balance": _num(start), "ending_balance": _num(equity["ending_balance"]),
                          "pnl": _num(pnl), "pnl_pct_of_start": _num(pnl / start * 100) if start else None,
                          "trades": equity.get("trades"), "capital_used": _num(equity.get("capital_used")),
                          "nifty_move_pct": _num(equity.get("benchmark_pct"))}

    # --- every candidate: the bought ones become 'trades', the rest 'others'; all of them feed the report card
    groups = {}
    for c in sorted(raw["candidates"], key=lambda c: c["rank"]):
        symbol = c["symbol"]
        v, p, o = verdicts.get(symbol), plans.get(symbol), outcomes.get(symbol)
        group = _group(symbol in accepted, v)
        groups.setdefault(group, []).append(o)
        who = info.get(symbol, {})
        stock = {"rank": c["rank"], "symbol": symbol, "company": who.get("company"), "sector": who.get("sector"),
                 "morning_change_pct": _num(c.get("change_pct")), "relative_volume": _num(c.get("rel_volume")),
                 "group": group, "analyst": _analyst(v),
                 "cited_headlines": _cited_headlines(raw["headlines"], symbol, (v or {}).get("cited_positions")),
                 "until_close": _until_close(o)}
        if group == "bought":
            r = results.get(p["id"])
            max_loss = _num(p.get("max_loss"))
            exit_time = _ist(r.get("exit_time")) if r else None
            pnl = _num(r["pnl"]) if r else None
            stock.update({
                "plan": {"entry": _num(p.get("entry")), "stop": _num(p.get("stop")), "target": _num(p.get("target")),
                         "shares": p.get("shares"), "cost": _num(p.get("cost")), "max_loss": max_loss,
                         "max_gain": _num(p.get("max_gain")), "planner_reason": p.get("gemini_reason")},
                "result": None if r is None else {
                    "outcome": r["outcome"], "exit_price": _num(r.get("exit_price")),
                    "exit_time_ist": exit_time.strftime("%H:%M") if exit_time else None, "pnl": pnl,
                    "minutes_in_trade": round((exit_time - started).total_seconds() / 60) if (exit_time and started) else None,
                    "r_multiple": _num(pnl / max_loss) if (pnl is not None and max_loss) else None}})
            facts["trades"].append(stock)
        else:
            stock["plan_status"] = p["status"] if p else None          # 'rejected' or 'skipped' keep their reason
            stock["plan_reason"] = p.get("rejection_reason") if p else None
            facts["others"].append(stock)

    # --- the report card, by group (see sql/analysis_group_comparison.sql for the same idea in SQL)
    for group, rows in groups.items():
        graded = [o for o in rows if o is not None]
        facts["report_card"][group] = {
            "label": GROUP_LABELS[group], "stocks": len(rows), "graded": len(graded),
            "avg_return_to_close_pct": _avg(_num(o.get("return_pct")) for o in graded),
            "avg_whatif_trade_pct": _avg(_num(o.get("std_return_pct")) for o in graded)}
    if facts["trades"] and not raw["outcomes"]:
        facts["not_recorded"].append("the report card (what every candidate did until the close)")

    # --- the day's status, and the win/loss count (plain counting, never done by the writer)
    pnls = [t["result"]["pnl"] for t in facts["trades"] if t["result"] and t["result"]["pnl"] is not None]
    facts["counts"] = {"trades": len(facts["trades"]), "winners": sum(1 for x in pnls if x > 0),
                       "losers": sum(1 for x in pnls if x < 0), "flat": sum(1 for x in pnls if x == 0)}
    facts["app_behaviour"] = _behaviour(raw, facts, verdicts)
    if equity is None:
        facts["day_status"] = "not_settled_yet"           # the run exists but settlement has not run
    else:
        facts["day_status"] = "traded" if facts["trades"] else "no_trades"
    return facts


# ------------------------------------------------------------------------------ both together
def collect_day_facts(market_date: date, client=None, info: dict | None = None) -> dict:
    """The fact bundle of one day, read from the database. Safe to call any time: it only reads."""
    if client is None:
        from storage import get_client                      # imported here so the pure part needs no database library
        client = get_client()
    if info is None:
        info = load_company_info()
    return build_day_facts(fetch_day_rows(client, market_date), info)


# ------------------------------------------------------------------------------ a short summary, and a command line
def summary_text(facts: dict) -> str:
    """A compact, readable summary of one bundle: enough to check by eye that the facts look right."""
    lines = [f"{facts['market_date']} ({facts['weekday']}): {facts['day_status']}"]
    if facts.get("note"):
        lines.append(f"note: {facts['note']}")
    run = facts["run"]
    if run:
        lines.append(f"run: {run['model']}, analyst {run['analyst_mode']}, started {run['started_at_ist']} IST, "
                     f"{run['passed_screen']} of {run['stocks_checked']} stocks passed the screen")
    m = facts["money"]
    if m:
        lines.append(f"money (gross): {m['starting_balance']:,.2f} -> {m['ending_balance']:,.2f}  pnl {m['pnl']:+,.2f} "
                     f"({m['pnl_pct_of_start']:+.2f}%), Nifty {m['nifty_move_pct']}%, capital used {m['capital_used']}")
    c = facts["counts"]
    lines.append(f"trades {c['trades']}: {c['winners']} won, {c['losers']} lost, {c['flat']} flat")
    for t in facts["trades"]:
        r = t["result"]
        outcome = "no result yet" if r is None else f"{r['outcome']} at {r['exit_price']} ({r['exit_time_ist']} IST), pnl {r['pnl']:+,.2f}, {r['r_multiple']}R"
        lines.append(f"  {t['symbol']} [{t['sector']}]: {outcome}; analyst {t['analyst']['event_type']}/{t['analyst']['event_status']}, "
                     f"{len(t['cited_headlines'])} cited headline(s)")
    b = facts.get("app_behaviour")
    if b:
        lines.append(f"app: {b['candidates']['without_headlines']} of {b['candidates']['total']} candidates had no headlines; analyst judged {b['analyst']['judged']} "
                     f"({b['analyst']['strong']} strong, {b['analyst']['overruled_by_code']} overruled by code); planner accepted {b['planner']['accepted']}, "
                     f"rejected {b['planner']['rejected']}, skipped {b['planner']['skipped']}, nudged {b['planner']['nudged']}")
        p = b["positions"]
        shared = "; ".join(k + " " + "+".join(x["symbol"] for x in v) for k, v in p["same_sector"].items()) or "none"
        lines.append(f"app: stops {p['stop_hits']} ({p['stop_hits_within_60_min']} within 60 min), targets {p['target_hits']}, "
                     f"3:15 closes {p['closed_at_end']}; same-sector trades: {shared}")
    lines.append(f"others: {len(facts['others'])} stocks")
    for group, g in facts["report_card"].items():
        lines.append(f"  report card - {g['label']}: {g['stocks']} stock(s), {g['graded']} graded, "
                     f"avg to close {g['avg_return_to_close_pct']}%, avg what-if trade {g['avg_whatif_trade_pct']}%")
    lines.append(f"not recorded: {len(facts['not_recorded'])} items")
    return "\n".join(lines)


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        raise SystemExit("Usage: python blog_facts.py YYYY-MM-DD [--json]")
    market_date = date.fromisoformat(args[0])
    facts = collect_day_facts(market_date)
    print(summary_text(facts))
    if "--json" in sys.argv:
        path = f"blog_facts_{market_date.isoformat()}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(facts, f, indent=2, ensure_ascii=False)
        print(f"full bundle saved to {path}")


if __name__ == "__main__":
    main()
