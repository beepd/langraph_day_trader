"""The blog's weekly facts (blog_weekly.py), on hand-made days and a stand-in database (no network). Run:  python test_blog_weekly.py"""
import copy, json, sys
sys.path.insert(0, ".")
from datetime import date

import blog_weekly as bw

BAD = []
def check(name, condition):
    print(("   ok   " if condition else "   BAD  ") + name)
    if not condition:
        BAD.append(name)


# ---------------------------------------------------------------- hand-made daily bundles (the shape blog_facts produces)
def day(iso, start=None, trades=(), status="traded", note=None, nifty=0.0, others=(), beh=None):
    """trades = (symbol, setup, outcome, pnl, planned max loss). Skipped / no-run days have start=None."""
    d = date.fromisoformat(iso)
    built, total = [], 0.0
    for symbol, setup, outcome, pnl, max_loss in trades:
        total += pnl
        built.append({"symbol": symbol, "sector": "Sector " + symbol, "group": "bought",
                      "analyst": {"event_type": setup, "reason": f"reason {symbol}"},
                      "result": {"outcome": outcome, "pnl": pnl, "r_multiple": round(pnl / max_loss, 2)},
                      "until_close": {"return_pct": 1.0, "whatif_return_pct": 0.5}})
    money = None
    if start is not None:
        money = {"starting_balance": start, "ending_balance": round(start + total, 2), "pnl": round(total, 2),
                 "pnl_pct_of_start": round(total / start * 100, 2), "trades": len(built), "capital_used": 1.0, "nifty_move_pct": nifty}
    wins = sum(1 for t in built if t["result"]["pnl"] > 0)
    loss = sum(1 for t in built if t["result"]["pnl"] < 0)
    return {"market_date": iso, "weekday": d.strftime("%A"), "day_status": status, "note": note, "money": money,
            "trades": built, "others": list(others), "app_behaviour": beh, "counts": {"trades": len(built), "winners": wins, "losers": loss, "flat": len(built) - wins - loss}}


def behaviour(mode, total, without, judged, strong, onwl, over, dropped, acc, rej, skipped, nudged, tgt, stops, quick, close, same=None, reasons=()):
    return {"candidates": {"total": total, "without_headlines": without},
            "analyst": {"mode": mode, "judged": judged, "strong": strong, "on_watchlist": onwl, "overruled_by_code": over, "strong_but_dropped": dropped},
            "planner": {"accepted": acc, "rejected": rej, "skipped": skipped, "nudged": nudged, "rejected_reasons": list(reasons)},
            "positions": {"target_hits": tgt, "stop_hits": stops, "stop_hits_within_60_min": quick, "closed_at_end": close, "same_sector": same or {},
                          "same_sector_pnl": {k: round(sum(x["pnl"] for x in v), 2) for k, v in (same or {}).items()}},
            "known_limitations": ["x"]}
MON = behaviour("classic", 10, 2, 8, 5, 3, 1, 0, 2, 1, 1, 2, 1, 1, 1, 0, reasons=[{"symbol": "X", "reason": "stop too close"}])
THU = behaviour("checklist", 10, 1, 9, 4, 2, 0, 1, 2, 0, 0, 1, 0, 1, 0, 1, same={"Information Technology": [
    {"symbol": "D", "outcome": "stop_hit", "pnl": -250.0}, {"symbol": "E", "outcome": "closed_at_end", "pnl": -100.0}]})


def normal_history():
    return [
        day("2026-10-02", 99800, [("H", "earnings", "target_hit", 200.0, 200.0)], nifty=0.1),            # the week before
        day("2026-10-05", 100000, [("A", "earnings", "target_hit", 500.0, 250.0), ("B", "order_win", "stop_hit", -200.0, 200.0)], nifty=0.2, beh=MON),
        day("2026-10-06", 100300, [("C", "earnings", "stop_hit", -300.0, 300.0)], nifty=-0.5),
        day("2026-10-07", None, status="skipped", note="market holiday"),
        day("2026-10-08", 100000, [("D", "other", "stop_hit", -250.0, 250.0), ("E", "earnings", "closed_at_end", -100.0, 250.0)], nifty=-1.3, beh=THU,
            others=[{"symbol": "X", "group": "no_catalyst", "until_close": {"return_pct": -0.5, "whatif_return_pct": -0.7}}]),
        day("2026-10-09", 99650, [("F", "earnings", "target_hit", 400.0, 250.0), ("G", "broker_call", "closed_at_end", 100.0, 250.0)], nifty=0.6),
    ]
DAYS, POST = bw.week_dates(date(2026, 10, 10))
TODAY = date(2026, 10, 10)


# ---------------------------------------------------------------- 1. which days make a week
print("1. The week")
check("a Saturday belongs to the week that just ended", [d.isoformat() for d in DAYS] ==
      ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"] and POST == date(2026, 10, 10))
check("a Friday, a Sunday and a Monday", bw.week_dates(date(2026, 10, 9))[0][0] == date(2026, 10, 5)
      and bw.week_dates(date(2026, 10, 11))[0][0] == date(2026, 10, 5) and bw.week_dates(date(2026, 10, 12))[0][0] == date(2026, 10, 12))

# ---------------------------------------------------------------- 2. a normal week, every number worked out by hand
print("2. A normal week")
f = bw.build_week_facts(DAYS, POST, normal_history(), TODAY)
w, c = f["week"], f["cumulative"]
check("it is a weekly bundle dated on the Saturday", f["kind"] == "weekly" and f["market_date"] == "2026-10-10" and f["weekday"] == "Saturday")
check("it can be saved as JSON", json.loads(json.dumps(f)) == f)
check("no warnings, complete", f["warnings"] == [] and f["complete"] is True)
check("last session is Friday", f["last_session"] == "2026-10-09")
check("five day rows, the holiday keeps its note", [d["status"] for d in f["days"]] == ["traded", "traded", "skipped", "traded", "traded"]
      and f["days"][2]["note"] == "market holiday" and f["days"][2]["pnl_gross"] is None)
check("day rows carry the Nifty move", f["days"][0]["nifty_move_pct"] == 0.2 and f["days"][3]["nifty_move_pct"] == -1.3)
e = w["equity"]
check("week balance 100000 -> 100150, pnl +150 (0.15%)", (e["starting_balance"], e["ending_balance"], e["pnl_gross"], e["return_pct"]) == (100000.0, 100150.0, 150.0, 0.15))
check("4 trading days in the week", e["trading_days"] == 4 and e["first_day"] == "2026-10-05" and e["last_day"] == "2026-10-09")
check("max drawdown: peak 100300 to 99650 = 650 = 0.65%", e["max_drawdown_rs"] == 650.0 and e["max_drawdown_pct"] == 0.65)
t = w["trades"]
check("7 trades: 3 won, 4 lost, win rate 42.9", (t["trades"], t["winners"], t["losers"], t["flat"], t["win_rate_pct"]) == (7, 3, 4, 0, 42.9))
check("gross profit 1000, gross loss 850, net 150", (t["gross_profit"], t["gross_loss"], t["net_pnl_gross"]) == (1000.0, 850.0, 150.0))
check("profit factor 1000/850 = 1.18", t["profit_factor"] == 1.18 and t["profit_factor_note"] is None)
check("average win 333.33, average loss 212.5, expectancy 21.43", (t["avg_win"], t["avg_loss"], t["expectancy_per_trade"]) == (333.33, 212.5, 21.43))
check("average R = 0.6 / 7 = 0.09", t["avg_r_multiple"] == 0.09)
check("exits: 2 targets, 3 stops, 2 closes", t["exits"] == {"target_hit": 2, "stop_hit": 3, "closed_at_end": 2})
check("best trade A (+500), worst trade C (-300)", (t["best_trade"]["symbol"], t["best_trade"]["pnl"]) == ("A", 500.0)
      and (t["worst_trade"]["symbol"], t["worst_trade"]["pnl"], t["worst_trade"]["date"]) == ("C", -300.0, "2026-10-06"))
check("the best trade keeps the analyst's reason", t["best_trade"]["reason"] == "reason A" and t["best_trade"]["setup"] == "earnings")
check("a week of 7 trades is flagged as a small sample", t["small_sample"] is True)
s = {x["setup"]: x for x in w["setups"]}
check("setups: earnings 4 trades, 2 wins, 50.0%, +500, 125 avg", (s["earnings"]["trades"], s["earnings"]["winners"], s["earnings"]["win_rate_pct"],
      s["earnings"]["net_pnl_gross"], s["earnings"]["avg_pnl_per_trade"]) == (4, 2, 50.0, 500.0, 125.0))
check("other setups and the order (most trades first)", [x["setup"] for x in w["setups"]] == ["earnings", "broker_call", "order_win", "other"]
      and s["order_win"]["net_pnl_gross"] == -200.0 and s["broker_call"]["net_pnl_gross"] == 100.0)
rc = w["report_card"]
check("report card over the week: bought 7 stocks, no-catalyst 1", rc["bought"]["stocks"] == 7 and rc["bought"]["avg_return_to_close_pct"] == 1.0
      and rc["no_catalyst"]["stocks"] == 1 and rc["no_catalyst"]["avg_return_to_close_pct"] == -0.5)
ce, ct = c["equity"], c["trades"]
check("since the start: 99800 -> 100150 over 5 days", (ce["starting_balance"], ce["ending_balance"], ce["pnl_gross"], ce["trading_days"], ce["first_day"])
      == (99800.0, 100150.0, 350.0, 5, "2026-10-02"))
check("since the start: 8 trades, 4 won, 4 lost, win rate 50.0, profit factor 1200/850 = 1.41",
      (ct["trades"], ct["winners"], ct["losers"], ct["win_rate_pct"], ct["profit_factor"]) == (8, 4, 4, 50.0, 1.41))
check("since the start: the earlier week's trade is counted, the week figures are not mixed in",
      ct["net_pnl_gross"] == 350.0 and t["net_pnl_gross"] == 150.0)
check("P&L is labelled gross and the definitions travel with the bundle", f["pnl_basis"].startswith("gross") and "win_rate" in f["definitions"])

# ---------------------------------------------------------------- 2b. how the app behaved
print("2b. App behaviour over the week")
a = bw.build_week_facts(DAYS, POST, normal_history(), TODAY)["app_behaviour"]
check("only the days that have a behaviour block are counted (Monday and Thursday)", a["days_covered"] == 2
      and a["analyst_mode_by_day"] == {"2026-10-05": "classic", "2026-10-08": "checklist"})
check("candidates and analyst counts are added up", a["candidates"] == {"total": 20, "without_headlines": 3}
      and a["analyst"] == {"judged": 17, "strong": 9, "on_watchlist": 5, "overruled_by_code": 1, "strong_but_dropped": 1})
check("planner counts are added up, rejected reasons keep their date",
      (a["planner"]["accepted"], a["planner"]["rejected"], a["planner"]["skipped"], a["planner"]["nudged"]) == (4, 1, 1, 3)
      and a["planner"]["rejected_reasons"] == [{"date": "2026-10-05", "symbol": "X", "reason": "stop too close"}])
check("position counts are added up", {k: v for k, v in a["positions"].items() if k not in ("same_sector_days", "same_sector_pnl_total")}
      == {"target_hits": 1, "stop_hits": 2, "stop_hits_within_60_min": 1, "closed_at_end": 1})
check("stocks held together in one sector: their rupee total per day and for the week (-250 - 100 = -350)",
      a["positions"]["same_sector_days"][0]["pnl_total"] == -350.0 and a["positions"]["same_sector_pnl_total"] == -350.0)
check("the day with two trades in one sector is listed with its date", len(a["positions"]["same_sector_days"]) == 1
      and a["positions"]["same_sector_days"][0]["date"] == "2026-10-08" and a["positions"]["same_sector_days"][0]["sector"] == "Information Technology"
      and [x["symbol"] for x in a["positions"]["same_sector_days"][0]["trades"]] == ["D", "E"])
check("the known limitations come through", a["known_limitations"] and "headline titles" in " ".join(a["known_limitations"]))
check("the summary prints the app lines", "APP BEHAVIOUR (week):" in bw.summary_text(bw.build_week_facts(DAYS, POST, normal_history(), TODAY))
      and "same sector on 2026-10-08: Information Technology D stop_hit, E closed_at_end (together -350.00)" in bw.summary_text(bw.build_week_facts(DAYS, POST, normal_history(), TODAY)))

# ---------------------------------------------------------------- 3. awkward weeks
print("3. Awkward weeks")
wins_only = [day("2026-10-05", 100000, [("A", "earnings", "target_hit", 300.0, 200.0), ("B", "earnings", "closed_at_end", 100.0, 200.0)])]
f = bw.build_week_facts(DAYS, POST, wins_only, date(2026, 10, 6))
t = f["week"]["trades"]
check("no losing trade: profit factor is None with a reason, not infinity", t["profit_factor"] is None and "not meaningful" in t["profit_factor_note"]
      and t["avg_loss"] is None and t["win_rate_pct"] == 100.0)
check("the worst trade may still be a win", t["worst_trade"]["pnl"] == 100.0)
f = bw.build_week_facts(DAYS, POST, [day(d.isoformat(), None, status="skipped", note="holiday") for d in DAYS], TODAY)
check("a week with no trades at all does not crash", f["week"]["equity"] is None and f["week"]["trades"]["trades"] == 0
      and f["week"]["trades"]["win_rate_pct"] is None and f["week"]["trades"]["best_trade"] is None and f["last_session"] is None)
check("...and it still prints", "no settled days" in bw.summary_text(f))
check("...and has no behaviour block", f["app_behaviour"] is None)
flat = [day("2026-10-05", 100000, [("A", "earnings", "closed_at_end", 0.0, 200.0)])]
check("a trade with exactly 0 profit is flat, not a win", bw.build_week_facts(DAYS, POST, flat, TODAY)["week"]["trades"]["flat"] == 1
      and bw.build_week_facts(DAYS, POST, flat, TODAY)["week"]["trades"]["winners"] == 0)
big = [day("2026-10-05", 100000, [(f"S{i}", "earnings", "target_hit", 10.0, 10.0) for i in range(10)])]
check("10 trades is no longer a small sample", bw.build_week_facts(DAYS, POST, big, TODAY)["week"]["trades"]["small_sample"] is False)
unknown = [day("2026-10-05", 100000, [("A", None, "target_hit", 10.0, 10.0)])]
check("a trade with no setup is grouped as 'unknown'", bw.build_week_facts(DAYS, POST, unknown, TODAY)["week"]["setups"][0]["setup"] == "unknown")

# ---------------------------------------------------------------- 4. warnings: the books must reconcile
print("4. Warnings")
def warn(history, today=TODAY):
    return bw.build_week_facts(DAYS, POST, history, today)["warnings"]
check("a day that did not happen yet is a warning", any("2026-10-09 has not happened yet" in x for x in warn(normal_history()[:5], date(2026, 10, 8))))
h = normal_history(); h[5] = day("2026-10-09", None, status="no_run")
check("a missing run is a warning", any("no run recorded" in x for x in warn(h)))
h = normal_history(); h[5] = day("2026-10-09", None, status="failed")
check("a failed run is a warning", any("run failed" in x for x in warn(h)))
h = normal_history(); h[5] = day("2026-10-09", 99650, [("F", "earnings", "target_hit", 400.0, 250.0)], status="not_settled_yet")
check("an unsettled day is a warning", any("not settled yet" in x for x in warn(h)))
h = normal_history(); h[5]["money"]["pnl"] = 450.0
check("trades that do not add up to the day's P&L are a warning", any("the trades add up to 500.0 but the day's P&L is 450.0" in x for x in warn(h)))
h = normal_history(); h[5]["money"]["ending_balance"] = 99999.0
check("ending minus starting balance that disagrees with the P&L is a warning", any("does not equal the day's P&L" in x for x in warn(h)))
h = normal_history(); h[4] = day("2026-10-08", 100100, [("D", "other", "stop_hit", -250.0, 250.0), ("E", "earnings", "closed_at_end", -100.0, 250.0)])
check("a starting balance that differs from the day before is a warning", any("2026-10-08: starting balance differs" in x for x in warn(h)))
f = bw.build_week_facts(DAYS, POST, h, TODAY)
check("with a warning the week is not 'complete'", f["complete"] is False and "WARNING" in bw.summary_text(f))

# ---------------------------------------------------------------- 5. reading the database with a stand-in client
print("5. collect_week_facts with a stand-in database")
class Q:
    def __init__(self, db, name): self.db, self.name, self.f = db, name, []
    def select(self, cols): return self
    def eq(self, c, v): self.f.append(("eq", c, v)); return self
    def in_(self, c, vs): self.f.append(("in", c, list(vs))); return self
    def execute(self):
        class R: pass
        r = R()
        r.data = copy.deepcopy([x for x in self.db.get(self.name, [])
                                if all((x.get(c) == v) if k == "eq" else (x.get(c) in v) for k, c, v in self.f)])
        return r
class Fake:
    def __init__(self, db): self.db = db
    def table(self, name): return Q(self.db, name)

DB, PLAN = {}, [0]
def add_day(run_id, iso, start, trades, nifty=0.0):
    """trades = (symbol, setup, outcome, pnl, max_loss); writes the rows the daily facts read."""
    total = 0.0
    DB.setdefault("runs", []).append({"id": run_id, "market_date": iso, "status": "finished", "data_is_live": True, "model_name": "m",
                                      "universe_size": 100, "passed_screen": 10, "started_at": f"{iso}T04:05:00+00:00", "settings": {}})
    for rank, (symbol, setup, outcome, pnl, max_loss) in enumerate(trades, start=1):
        PLAN[0] += 1
        total += pnl
        DB.setdefault("candidates", []).append({"run_id": run_id, "symbol": symbol, "rank": rank, "change_pct": 1.0, "rel_volume": 2.0})
        DB.setdefault("verdicts", []).append({"run_id": run_id, "symbol": symbol, "has_catalyst": True, "bullish": True, "strength": "strong",
                                              "catalyst_type": setup, "reason": "r", "cited_positions": [], "on_watchlist": True})
        DB.setdefault("plans", []).append({"id": PLAN[0], "run_id": run_id, "symbol": symbol, "status": "accepted", "entry": 100.0, "stop": 99.0,
                                           "target": 102.0, "shares": 10, "cost": 1000.0, "max_loss": max_loss, "max_gain": 2 * max_loss})
        DB.setdefault("trade_results", []).append({"plan_id": PLAN[0], "outcome": outcome, "exit_price": 100.0,
                                                   "exit_time": f"{iso}T05:00:00+00:00", "pnl": pnl})
    DB.setdefault("daily_equity", []).append({"market_date": iso, "starting_balance": start, "ending_balance": start + total, "pnl": total,
                                              "trades": len(trades), "benchmark_pct": nifty, "capital_used": 2000.0})

add_day(1, "2026-10-02", 99800, [("H", "earnings", "target_hit", 200.0, 200.0)])
add_day(2, "2026-10-08", 100000, [("D", "other", "stop_hit", -250.0, 250.0)], nifty=-1.3)
add_day(3, "2026-10-09", 99750, [("F", "earnings", "target_hit", 400.0, 250.0)], nifty=0.6)
add_day(4, "2026-10-12", 100150, [("Z", "earnings", "target_hit", 999.0, 250.0)])           # NEXT week: must be ignored
DB["daily_equity"][0]["ending_balance"] = 100000.0                                              # keep the books continuous
f = bw.collect_week_facts(date(2026, 10, 10), client=Fake(DB), info={}, today=TODAY)
check("the week holds Thursday and Friday, next week's day is ignored", f["week"]["trades"]["trades"] == 2
      and f["cumulative"]["trades"]["trades"] == 3 and f["cumulative"]["equity"]["last_day"] == "2026-10-09")
check("week pnl +150, since-the-start pnl +350", f["week"]["equity"]["pnl_gross"] == 150.0 and f["cumulative"]["equity"]["pnl_gross"] == 350.0)
check("Mon-Wed have no run, so the week is flagged", len([x for x in f["warnings"] if "no run recorded" in x]) == 3 and f["complete"] is False)
check("the stored Nifty move comes through, never recalculated", [d["nifty_move_pct"] for d in f["days"][3:]] == [-1.3, 0.6])
check("the summary prints", "WEEK (gross):" in bw.summary_text(f) and "CUMULATIVE (gross):" in bw.summary_text(f))

print()
print("ALL CHECKS PASSED" if not BAD else "FAILED: " + "; ".join(BAD))
sys.exit(1 if BAD else 0)
