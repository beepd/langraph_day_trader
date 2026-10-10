"""The blog's fact bundle (blog_facts.py), against a stand-in database (no network). Run:  python test_blog_facts.py"""
import copy, json, sys
sys.path.insert(0, ".")
from datetime import date

import blog_facts as bf

BAD = []
def check(name, condition):
    print(("   ok   " if condition else "   BAD  ") + name)
    if not condition:
        BAD.append(name)


# ---------------------------------------------------------------- a stand-in database (select queries only)
class Q:
    def __init__(self, db, name): self.db, self.name, self.f = db, name, []
    def select(self, cols): return self
    def eq(self, c, v): self.f.append(("eq", c, v)); return self
    def in_(self, c, vs): self.f.append(("in", c, list(vs))); return self
    def execute(self):
        if self.name in self.db.get("_missing", []):
            raise RuntimeError(f'relation "{self.name}" does not exist')
        class R: pass
        r = R()
        r.data = copy.deepcopy([x for x in self.db.get(self.name, [])
                                if all((x.get(c) == v) if k == "eq" else (x.get(c) in v) for k, c, v in self.f)])
        return r
class Fake:
    def __init__(self, db): self.db = db
    def table(self, name): return Q(self.db, name)


INFO = {"AAA": {"company": "Alpha Ltd.", "sector": "Information Technology"},
        "BBB": {"company": "Beta Ltd.", "sector": "Healthcare"},
        "DDD": {"company": "Delta Ltd.", "sector": "Information Technology"}}
DAY = "2026-10-09"                                    # a Friday


def trading_day_db():
    """A made-up day: AAA and BBB bought (one target, one stop), CCC weak, DDD dropped by the sector rule,
    EEE no catalyst, FFF strong but skipped because of the position cap."""
    cand = lambda rank, sym, chg: {"run_id": 7, "symbol": sym, "rank": rank, "price": 100.0, "change_pct": chg,
                                   "rel_volume": 2.0, "avg_range": 5.0}
    verdict = lambda sym, **kw: {"run_id": 7, "symbol": sym, "has_catalyst": True, "bullish": True, "strength": "strong",
                                 "catalyst_type": "earnings", "reason": f"reason {sym}", "cited_positions": [1],
                                 "overruled_by_code": False, "on_watchlist": False, "event_status": "happened",
                                 "has_number": True, "checklist_notes": None, **kw}
    outcome = lambda sym, ret, whatif: {"run_id": 7, "symbol": sym, "return_pct": ret, "max_up_pct": 2.5,
                                        "max_down_pct": -0.5, "std_outcome": "target_hit", "std_return_pct": whatif}
    return {
        "runs": [{"id": 7, "market_date": DAY, "status": "finished", "data_is_live": True, "model_name": "gpt-4.1-mini",
                  "universe_size": 100, "passed_screen": 12, "started_at": "2026-10-09T04:05:00+00:00",   # 09:35 IST
                  "settings": {"analyst_mode": "checklist", "balance_at_start": 100000}, "note": None,
                  "error": "SECRET TEXT THAT MUST NOT TRAVEL"}],
        "daily_equity": [{"market_date": DAY, "starting_balance": 100000, "ending_balance": 100376, "pnl": 376,
                          "trades": 2, "benchmark_pct": 0.4, "capital_used": 49790}],
        "candidates": [cand(1, "AAA", 3.1), cand(2, "BBB", 2.2), cand(3, "CCC", 1.8), cand(4, "DDD", 1.5),
                       cand(5, "EEE", 1.1), cand(6, "FFF", 0.9)],
        "headlines": [
            {"run_id": 7, "symbol": "AAA", "position": 1, "title": "Alpha Q2 profit up 28%", "source": "Mint",
             "published_at": "2026-10-08T04:00:00+00:00"},
            {"run_id": 7, "symbol": "AAA", "position": 2, "title": "Alpha raises guidance", "source": None,
             "published_at": None},
            {"run_id": 7, "symbol": "AAA", "position": 3, "title": "Not cited, must not appear", "source": "X",
             "published_at": None}],
        "verdicts": [verdict("AAA", on_watchlist=True, cited_positions=[1, 2]),
                     verdict("BBB", on_watchlist=True, catalyst_type="order_win"),
                     verdict("CCC", strength="weak", catalyst_type="dividend", event_status="expected"),
                     verdict("DDD", checklist_notes="same sector (Information Technology) as AAA"),
                     verdict("EEE", has_catalyst=False, strength="weak", catalyst_type="other"),
                     verdict("FFF", on_watchlist=True)],
        "plans": [
            {"id": 1, "run_id": 7, "symbol": "AAA", "status": "accepted", "entry": 331.0, "stop": 328.85,
             "target": 337.4, "shares": 90, "cost": 29790, "max_loss": 193.5, "max_gain": 576.0,
             "gemini_reason": "stop below the day's low", "rejection_reason": None},
            {"id": 2, "run_id": 7, "symbol": "BBB", "status": "accepted", "entry": 500.0, "stop": 495.0,
             "target": 508.0, "shares": 40, "cost": 20000, "max_loss": 200.0, "max_gain": 320.0,
             "gemini_reason": "[adjusted by the rulebook: target moved to the limit] tight stop", "rejection_reason": None},
            {"id": 3, "run_id": 7, "symbol": "FFF", "status": "skipped", "rejection_reason": "only 3 positions a day"},
            {"id": 4, "run_id": 7, "symbol": "EEE", "status": "rejected", "rejection_reason": "stop is too close " + "x" * 200,
             "gemini_reason": "[adjusted by the rulebook: stop moved] tried"}],
        "trade_results": [
            {"plan_id": 1, "outcome": "target_hit", "exit_price": 337.4, "exit_time": "2026-10-09T05:35:00+00:00", "pnl": 576.0},
            {"plan_id": 2, "outcome": "stop_hit", "exit_price": 495.0, "exit_time": "2026-10-09T04:55:00+00:00", "pnl": -200.0}],
        "candidate_outcomes": [outcome("AAA", 1.2, 2.0), outcome("BBB", -1.0, -1.0), outcome("CCC", 0.5, 0.4),
                               outcome("DDD", 0.9, 1.5), outcome("EEE", -0.3, -0.5), outcome("FFF", 2.0, 1.2)],
    }


def facts_for(db, day=DAY):
    return bf.collect_day_facts(date.fromisoformat(day), client=Fake(db), info=INFO)


# ---------------------------------------------------------------- 1. a normal trading day
print("1. A normal trading day")
f = facts_for(trading_day_db())
check("day_status is traded", f["day_status"] == "traded")
check("date and weekday", f["market_date"] == DAY and f["weekday"] == "Friday")
check("the bundle can be saved as JSON", json.loads(json.dumps(f)) == f)
check("the failed-run error text never travels", "SECRET" not in json.dumps(f))
check("P&L is labelled gross", f["pnl_basis"].startswith("gross"))
check("run info", f["run"]["model"] == "gpt-4.1-mini" and f["run"]["analyst_mode"] == "checklist"
      and f["run"]["started_at_ist"] == "09:35" and f["run"]["passed_screen"] == 12)
check("money block", f["money"] == {"starting_balance": 100000.0, "ending_balance": 100376.0, "pnl": 376.0,
                                     "pnl_pct_of_start": 0.38, "trades": 2, "capital_used": 49790.0, "nifty_move_pct": 0.4})
check("2 trades and 4 others", [t["symbol"] for t in f["trades"]] == ["AAA", "BBB"]
      and [o["symbol"] for o in f["others"]] == ["CCC", "DDD", "EEE", "FFF"])
check("counts: 1 winner, 1 loser, 0 flat", f["counts"] == {"trades": 2, "winners": 1, "losers": 1, "flat": 0})
a, b = f["trades"]
check("company and sector come from the Nifty file", a["company"] == "Alpha Ltd." and a["sector"] == "Information Technology")
check("target trade: result, exit time in India time", a["result"]["outcome"] == "target_hit"
      and a["result"]["exit_price"] == 337.4 and a["result"]["exit_time_ist"] == "11:05" and a["result"]["pnl"] == 576.0)
check("R multiple = pnl / planned max loss (576 / 193.5)", a["result"]["r_multiple"] == 2.98)
check("stop trade: -1.0 R, exit time 10:25", b["result"]["r_multiple"] == -1.0 and b["result"]["exit_time_ist"] == "10:25")
check("plan numbers and the planner's reason", a["plan"]["entry"] == 331.0 and a["plan"]["shares"] == 90
      and a["plan"]["planner_reason"] == "stop below the day's low")
check("analyst answers incl. checklist columns", a["analyst"]["event_type"] == "earnings"
      and a["analyst"]["event_status"] == "happened" and a["analyst"]["reason"] == "reason AAA")
check("only the CITED headlines, with dates in India time", [h["number"] for h in a["cited_headlines"]] == [1, 2]
      and a["cited_headlines"][0]["date"] == "2026-10-08" and a["cited_headlines"][1]["date"] is None
      and a["cited_headlines"][0]["source"] == "Mint")
check("until-the-close numbers", a["until_close"]["return_pct"] == 1.2 and a["until_close"]["whatif_return_pct"] == 2.0)
others = {o["symbol"]: o for o in f["others"]}
check("groups are assigned", [a["group"], b["group"], others["CCC"]["group"], others["DDD"]["group"],
                              others["EEE"]["group"], others["FFF"]["group"]]
      == ["bought", "bought", "weak_catalyst", "strong_dropped", "no_catalyst", "strong_not_bought"])
check("a skipped plan keeps its reason", others["FFF"]["plan_status"] == "skipped"
      and others["FFF"]["plan_reason"] == "only 3 positions a day")
check("the sector-rule note is kept", "same sector" in others["DDD"]["analyst"]["notes"])
rc = f["report_card"]
check("report card: bought average (1.2 and -1.0 -> 0.1; what-if 2.0 and -1.0 -> 0.5)",
      rc["bought"]["stocks"] == 2 and rc["bought"]["avg_return_to_close_pct"] == 0.1 and rc["bought"]["avg_whatif_trade_pct"] == 0.5)
check("report card: other groups", rc["strong_not_bought"]["avg_return_to_close_pct"] == 2.0
      and rc["strong_dropped"]["avg_return_to_close_pct"] == 0.9 and rc["weak_catalyst"]["avg_return_to_close_pct"] == 0.5
      and rc["no_catalyst"]["avg_return_to_close_pct"] == -0.3)
check("report card groups carry plain-words labels", rc["bought"]["label"] == "strong catalyst, bought")
check("the 'not recorded' list is present", len(f["not_recorded"]) == 4 and any("Bank Nifty" in x for x in f["not_recorded"]))

# ---------------------------------------------------------------- 2. days without trading
print("2. Skipped, failed, missing and unsettled days")
db = {"runs": [{"id": 3, "market_date": DAY, "status": "skipped", "note": "market holiday", "data_is_live": False}]}
f = facts_for(db)
check("skipped day: status, note, no trades", f["day_status"] == "skipped" and f["note"] == "market holiday"
      and f["trades"] == [] and f["money"] is None)
db = {"runs": [{"id": 3, "market_date": DAY, "status": "failed", "error": "boom", "data_is_live": None}]}
f = facts_for(db)
check("failed day: status only, no error text", f["day_status"] == "failed" and "boom" not in json.dumps(f))
f = facts_for({}, "2026-10-10")
check("no run at all (a weekend): no_run", f["day_status"] == "no_run" and f["weekday"] == "Saturday" and f["trades"] == [])
db = trading_day_db(); db["daily_equity"] = []
f = facts_for(db)
check("run exists but not settled yet: not_settled_yet, money is empty", f["day_status"] == "not_settled_yet" and f["money"] is None)
db = trading_day_db(); db["plans"] = [p for p in db["plans"] if p["status"] != "accepted"]; db["trade_results"] = []
db["daily_equity"][0]["trades"] = 0
f = facts_for(db)
check("settled day with no accepted plan: no_trades", f["day_status"] == "no_trades" and f["trades"] == [] and f["counts"]["trades"] == 0)

# ---------------------------------------------------------------- 3. which run is the official one
print("3. Choosing the day's official run")
db = trading_day_db()
db["runs"] += [{"id": 9, "market_date": DAY, "status": "failed", "data_is_live": None},
               {"id": 10, "market_date": DAY, "status": "finished", "data_is_live": False, "model_name": "forced test"},
               {"id": 11, "market_date": DAY, "status": "running", "data_is_live": None}]
f = facts_for(db)
check("a later failed / non-live / running run does not replace the real finished run", f["run"]["model"] == "gpt-4.1-mini")
db = trading_day_db()
db["runs"].append({"id": 12, "market_date": DAY, "status": "finished", "data_is_live": True, "model_name": "second run",
                   "settings": {}, "started_at": "2026-10-09T04:30:00+00:00"})
db["candidates"] = [dict(c, run_id=12) for c in db["candidates"][:1]]
f = facts_for(db)
check("two finished live runs: the latest wins", f["run"]["model"] == "second run" and f["run"]["analyst_mode"] == "classic")

# ---------------------------------------------------------------- 4. older data shapes
print("4. Older or incomplete data")
db = trading_day_db()
for v in db["verdicts"]:
    for key in ("event_status", "has_number", "checklist_notes"):
        v.pop(key)                                    # a classic-mode run has no checklist columns
f = facts_for(db)
check("classic-mode verdicts: checklist fields are None, nothing crashes", f["trades"][0]["analyst"]["event_status"] is None
      and f["trades"][0]["analyst"]["reason"] == "reason AAA")
db = trading_day_db(); db["_missing"] = ["candidate_outcomes"]
f = facts_for(db)
check("no report-card table: the day still builds and says so", f["day_status"] == "traded"
      and f["trades"][0]["until_close"] is None and any("report card" in x for x in f["not_recorded"]))
check("...and the report card groups hold no averages", f["report_card"]["bought"]["avg_return_to_close_pct"] is None
      and f["report_card"]["bought"]["graded"] == 0)
db = trading_day_db(); db["trade_results"] = [r for r in db["trade_results"] if r["plan_id"] != 2]
f = facts_for(db)
check("a bought stock without a result yet: result is None, counted once", f["trades"][1]["result"] is None
      and f["counts"] == {"trades": 2, "winners": 1, "losers": 0, "flat": 0})

# ---------------------------------------------------------------- 5. how the app behaved
print("5. App behaviour")
ab = facts_for(trading_day_db())["app_behaviour"]
check("candidates: 6 in total, 5 without a single headline", ab["candidates"] == {"total": 6, "without_headlines": 5})
check("analyst: 6 judged, 4 strong, 3 on the watchlist, 0 overruled, 1 strong but dropped",
      ab["analyst"] == {"mode": "checklist", "judged": 6, "strong": 4, "on_watchlist": 3, "overruled_by_code": 0, "strong_but_dropped": 1})
check("planner: 2 accepted, 1 rejected, 1 skipped, 2 nudged (one accepted, one rejected)",
      (ab["planner"]["accepted"], ab["planner"]["rejected"], ab["planner"]["skipped"], ab["planner"]["nudged"]) == (2, 1, 1, 2))
check("a rejected plan keeps its symbol and a reason cut to 140 characters", ab["planner"]["rejected_reasons"][0]["symbol"] == "EEE"
      and len(ab["planner"]["rejected_reasons"][0]["reason"]) == 140)
check("positions: 1 target, 1 stop (hit after 50 minutes, so a quick stop-out), no 3:15 close, no shared sector",
      ab["positions"] == {"target_hits": 1, "stop_hits": 1, "stop_hits_within_60_min": 1, "closed_at_end": 0, "same_sector": {}})
trades = {t["symbol"]: t for t in facts_for(trading_day_db())["trades"]}
check("minutes in trade: 90 for the target trade, 50 for the stop trade", trades["AAA"]["result"]["minutes_in_trade"] == 90
      and trades["BBB"]["result"]["minutes_in_trade"] == 50)
check("the known limitations travel with the bundle", len(ab["known_limitations"]) >= 5 and any("headline titles" in x for x in ab["known_limitations"]))
shared = dict(INFO, BBB={"company": "Beta Ltd.", "sector": "Information Technology"})
same = bf.collect_day_facts(date.fromisoformat(DAY), client=Fake(trading_day_db()), info=shared)["app_behaviour"]["positions"]["same_sector"]
check("two trades in one sector are reported with their outcomes", same == {"Information Technology": [
      {"symbol": "AAA", "outcome": "target_hit", "pnl": 576.0}, {"symbol": "BBB", "outcome": "stop_hit", "pnl": -200.0}]})
slow = trading_day_db(); slow["trade_results"][1]["exit_time"] = "2026-10-09T06:00:00+00:00"            # 115 minutes after the start
check("a stop hit after 60 minutes is not a quick stop-out", facts_for(slow)["app_behaviour"]["positions"]["stop_hits_within_60_min"] == 0)
check("skipped, failed and no-run days have no behaviour block", facts_for({"runs": [{"id": 3, "market_date": DAY, "status": "skipped"}]})["app_behaviour"] is None
      and facts_for({})["app_behaviour"] is None)
check("the summary mentions the app lines", "app: 5 of 6 candidates had no headlines" in bf.summary_text(facts_for(trading_day_db())))

# ---------------------------------------------------------------- 6. the printed summary
print("6. The short summary")
text = bf.summary_text(facts_for(trading_day_db()))
check("summary shows status, money and both trades", "traded" in text and "+376.00" in text and "AAA" in text
      and "target_hit at 337.4 (11:05 IST)" in text and "-1.0R" in text)
check("summary shows the report-card groups", "strong catalyst, bought: 2 stock(s), 2 graded" in text)
for name, database in (("skipped", {"runs": [{"id": 3, "market_date": DAY, "status": "skipped", "note": "holiday"}]}),
                       ("no run", {}), ("unsettled", dict(trading_day_db(), daily_equity=[]))):
    try:
        bf.summary_text(facts_for(database)); ok = True
    except Exception as error:
        ok = False; print("      ", name, error)
    check(f"summary works for a {name} day", ok)

# ---------------------------------------------------------------- 7. the real Nifty file loads
print("7. The Nifty file")
info = bf.load_company_info("nifty100.csv")
check("nifty100.csv gives company and sector", len(info) >= 90 and info["ABB"] == {"company": "ABB India Ltd.", "sector": "Capital Goods"})

print()
print("ALL CHECKS PASSED" if not BAD else "FAILED: " + "; ".join(BAD))
sys.exit(1 if BAD else 0)
