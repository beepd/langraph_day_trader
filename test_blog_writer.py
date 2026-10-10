"""The blog writer and its checks (blog_writer.py), with a fake model (no network, no database). Run:  python test_blog_writer.py"""
import sys
sys.path.insert(0, ".")
from datetime import date

import blog_facts as bf
import blog_weekly as bw
import blog_writer as w

BAD = []
def check(name, condition):
    print(("   ok   " if condition else "   BAD  ") + name)
    if not condition:
        BAD.append(name)


# ---------------------------------------------------------------- made-up facts, built with the real code
def raw_day(iso, start, trades, nifty=0.2):
    """trades = (symbol, outcome, pnl). Each trade risked 200 rupees at its stop."""
    cands, verdicts, plans, results, outcomes, headlines = [], [], [], [], [], []
    total = 0.0
    for i, (symbol, outcome, pnl) in enumerate(trades, start=1):
        total += pnl
        cands.append({"run_id": 1, "symbol": symbol, "rank": i, "change_pct": 2.0, "rel_volume": 2.0})
        headlines.append({"run_id": 1, "symbol": symbol, "position": 1, "title": f"{symbol} Q2 profit up 28%", "source": "Mint",
                          "published_at": f"{iso}T02:00:00+00:00"})
        verdicts.append({"run_id": 1, "symbol": symbol, "has_catalyst": True, "bullish": True, "strength": "strong", "catalyst_type": "earnings",
                         "reason": f"{symbol} reported results", "cited_positions": [1], "overruled_by_code": False, "on_watchlist": True})
        plans.append({"id": i, "run_id": 1, "symbol": symbol, "status": "accepted", "entry": 100.0, "stop": 98.0, "target": 104.0, "shares": 100,
                      "cost": 10000.0, "max_loss": 200.0, "max_gain": 400.0, "gemini_reason": "stop under the low"})
        results.append({"plan_id": i, "outcome": outcome, "exit_price": 100.0, "exit_time": f"{iso}T05:00:00+00:00", "pnl": pnl})
        outcomes.append({"run_id": 1, "symbol": symbol, "return_pct": 1.0, "max_up_pct": 2.0, "max_down_pct": -0.5,
                         "std_outcome": "target_hit", "std_return_pct": 0.8})
    return {"market_date": iso, "run": {"id": 1, "status": "finished", "data_is_live": True, "model_name": "m", "universe_size": 100,
            "passed_screen": 12, "started_at": f"{iso}T04:05:00+00:00", "settings": {"analyst_mode": "classic", "balance_at_start": start}, "note": None},
            "equity": {"starting_balance": start, "ending_balance": start + total, "pnl": total, "trades": len(trades), "benchmark_pct": nifty,
                       "capital_used": 20000.0},
            "candidates": cands, "headlines": headlines, "verdicts": verdicts, "plans": plans, "results": results, "outcomes": outcomes}

INFO = {s: {"company": s + " Ltd.", "sector": "Sector " + s} for s in "ABCDE"}
DAY = bf.build_day_facts(raw_day("2026-10-09", 100000, [("A", "target_hit", 300.0), ("B", "stop_hit", -200.0)]), INFO)
WEEK_DAYS, POST = bw.week_dates(date(2026, 10, 10))
HISTORY = [bf.build_day_facts(raw_day(iso, start, [(sym, outcome, pnl)]), INFO) for iso, start, (sym, outcome, pnl) in [
    ("2026-10-05", 100000, ("A", "target_hit", 300.0)), ("2026-10-06", 100300, ("B", "stop_hit", -200.0)),
    ("2026-10-07", 100100, ("C", "closed_at_end", 150.0)), ("2026-10-08", 100250, ("D", "stop_hit", -100.0)),
    ("2026-10-09", 100150, ("E", "target_hit", 400.0))]]
WEEK = bw.build_week_facts(WEEK_DAYS, POST, HISTORY, date(2026, 10, 10))
check("test setup: the made-up week is complete and the day has two trades", WEEK["complete"] is True and DAY["day_status"] == "traded"
      and WEEK["week"]["trades"]["net_pnl_gross"] == 550.0)

# ---------------------------------------------------------------- 1. the number check
print("1. The number check")
f = DAY
unsupported = lambda text: w.find_unsupported_numbers(text, f)
check("numbers copied from the facts pass, in any format", unsupported("I made ₹100.00 gross; the day was +0.10%, Nifty 0.2%, 2 trades, 1 won, -₹200, 1.5R, 100,000 start") == [])
check("signs are ignored, so a loss may be written as a plain amount", unsupported("one trade lost ₹200 and the other made ₹300") == [])
check("rounding to a whole number is accepted", unsupported("about ₹100 gross") == [] and unsupported("a 0.1% day") == [])
check("an invented number is caught", unsupported("I made ₹1,200 today") == ["1,200"])
check("an average or a sum the model worked out is caught", unsupported("the average win was ₹875 across 7 trades") == ["875", "7"])
check("dates, times and list markers are not claims", unsupported("On 9 October 2026 at 09:45 IST, from 5-9 October.\n1. first point\n2. second") == [])
check("the fixed app rules are allowed", unsupported("at most 3 positions, 1% risk, 30% cap, stops inside 60 minutes, 100 stocks") == [])
check("the year of the post is allowed", unsupported("in 2026") == [])
check("numbers inside headlines in the facts are allowed (the 28% in the headline)", unsupported("the headline said profit was up 28%") == [])
check("each bad number is listed once", unsupported("₹1,200 and ₹1,200 again") == ["1,200"])

# ---------------------------------------------------------------- 2. the other checks
print("2. The other checks")
def good_daily():
    words = " ".join(["The bot bought on recorded reasons and two stocks ended with a small gross gain."] * 6)
    return {"title": "NSE paper trading: 9 October 2026", "meta_description": "A paper-trading diary of one NSE day with fake money.",
            "body_markdown": "This is a simulation with fake money. Gross result: ₹100.00.\n\n## The trades\n\n" + words + "\n\n## One idea to test next\n\n" + words}
check("a good draft passes", w.check_draft(good_daily(), DAY, "daily") == [])
d = good_daily(); d["title"] = "x" * 80
check("a title over 70 characters fails", any("title" in p for p in w.check_draft(d, DAY, "daily")))
d = good_daily(); d["meta_description"] = "y" * 200
check("a meta description over 160 characters fails", any("meta description" in p for p in w.check_draft(d, DAY, "daily")))
d = good_daily(); d["body_markdown"] = "This is a simulation with fake money. Short."
check("a text that is too short fails", any("words" in p for p in w.check_draft(d, DAY, "daily")))
d = good_daily(); d["body_markdown"] = d["body_markdown"].replace("simulation with fake money", "diary")
check("not saying it is a simulation fails", any("simulation" in p for p in w.check_draft(d, DAY, "daily")))
d = good_daily(); d["body_markdown"] += "\n\nThe stock will rise tomorrow, you should buy."
check("a prediction or advice fails", len([p for p in w.check_draft(d, DAY, "daily") if "no advice" in p]) == 2)
d = good_daily(); d["body_markdown"] += "\n\nThe bot felt confident and was excited."
check("feelings attributed to the bot fail", len([p for p in w.check_draft(d, DAY, "daily") if "no recorded feelings" in p]) == 2)
d = good_daily(); d["body_markdown"] += "\n\n| a | b |\n|---|---|"
check("a table written by the model fails", any("tables" in p for p in w.check_draft(d, DAY, "daily")))
d = good_daily(); d["body_markdown"] += "\n\nI made ₹9,999 in total."
check("an invented number fails and is named", any("9,999" in p for p in w.check_draft(d, DAY, "daily")))
check("a weekly post has a longer length range", w.check_draft(good_daily(), WEEK, "weekly") != [] and w.LENGTH["weekly"][0] > w.LENGTH["daily"][0])

# ---------------------------------------------------------------- 3. the tables (built by code)
print("3. The tables")
dt = w.daily_tables(DAY)
check("daily table: header, one row per trade, formatted money", dt.startswith("| Stock | Setup | Result | Exit (IST) | Gross P&L | R |")
      and "| A | earnings | target hit | 10:30 | +₹300.00 | +1.50R |" in dt and "| B | earnings | stop hit | 10:30 | −₹200.00 | -1.00R |" in dt)
check("daily table: day total with the Nifty, labelled gross", "**Day total (gross):** +₹100.00 (+0.10% of the starting balance). Nifty over the same window: +0.20%." in dt)
check("a day with no trades has no table", w.daily_tables(dict(DAY, trades=[])) == "")
wt = w.weekly_tables(WEEK)
check("weekly days table has five rows", sum(1 for line in wt.splitlines() if line[:2] == "| " and line.split("|")[1].strip()[:3] in ("Mon", "Tue", "Wed", "Thu", "Fri")) == 5
      and "| Mon 10-05 | 1 | 1 / 0 | +₹300.00 | +0.20% |" in wt)
check("weekly stats table: this week and since the start side by side", "| Gross P&L | +₹550.00 | +₹550.00 |" in wt
      and "| Win rate | 60.0% | 60.0% |" in wt and "| Starting balance | ₹100,000.00 | ₹100,000.00 |" in wt)
check("weekly stats: profit factor and drawdown are formatted", "| Profit factor | 2.83 | 2.83 |" in wt and "| Maximum drawdown (end-of-day balances) | 0.20% (₹200.00) | 0.20% (₹200.00) |" in wt)
check("a small sample is labelled under the table", "Small sample" in wt)
holiday = dict(WEEK, days=[dict(WEEK["days"][0], status="skipped", pnl_gross=None, pnl_pct_of_start=None, note="market holiday")] + WEEK["days"][1:])
check("a holiday row shows its note", "| Mon 10-05 | – | – | skipped (market holiday) | – |" in w.weekly_tables(holiday))

# ---------------------------------------------------------------- 4. the prompt
print("4. The prompt")
p = w.build_prompt(DAY, "daily")
check("the prompt holds the facts, the rules and the daily structure", '"market_date": "2026-10-09"' in p and "NUMBERS." in p and "How the app behaved" in p
      and "One idea to test next" in p and "APP RULES" in p)
check("the weekly prompt has the weekly structure", "What I will test next week" in w.build_prompt(WEEK, "weekly") and "Best and toughest trade" in w.build_prompt(WEEK, "weekly"))
check("the prompt tells the model not to reveal who the author is", "Do not mention any job, employer, city or background" in p)

# ---------------------------------------------------------------- 5. writing, retrying, refusing
print("5. write_post")
calls = []
def make_generate(drafts):
    def generate(prompt):
        calls.append(prompt)
        item = drafts[min(len(calls) - 1, len(drafts) - 1)]
        if isinstance(item, Exception):
            raise item
        return item
    return generate

calls.clear()
r = w.write_post(DAY, make_generate([good_daily()]), "daily")
check("a good draft: ok, one try, no problems", r["ok"] and r["tries"] == 1 and r["problems"] == [] and len(calls) == 1)
body = r["body_markdown"]
check("assembled: first paragraph, then the table, then the rest, then the disclosure",
      body.index("This is a simulation") < body.index("| Stock |") < body.index("## The trades") < body.index("Simulation notice"))
check("the disclosure is the fixed code text", body.endswith(w.DISCLOSURE) and "written by an AI" in body)
check("title and description are kept", r["title"].startswith("NSE paper trading") and r["meta_description"])

calls.clear()
bad = good_daily(); bad["body_markdown"] += "\n\nI made ₹9,999."
r = w.write_post(DAY, make_generate([bad, good_daily()]), "daily")
check("a bad first draft is retried once with the problems listed", r["ok"] and r["tries"] == 2 and len(calls) == 2
      and "PREVIOUS DRAFT HAD THESE PROBLEMS" in calls[1] and "9,999" in calls[1] and "PREVIOUS" not in calls[0])

calls.clear()
r = w.write_post(DAY, make_generate([bad]), "daily")
check("still bad after the retries: not ok, the problems are returned, a draft is still assembled", not r["ok"] and r["tries"] == 2
      and any("9,999" in x for x in r["problems"]) and r["body_markdown"])

calls.clear()
r = w.write_post(DAY, make_generate([RuntimeError("quota exceeded")]), "daily")
check("a model failure is reported, not raised", not r["ok"] and r["tries"] == 1 and "quota exceeded" in r["problems"][0] and r["body_markdown"] is None)

calls.clear()
skipped = bf.build_day_facts({"market_date": "2026-10-07", "run": {"id": 1, "status": "skipped", "note": "holiday"}, "equity": None,
                              "candidates": [], "headlines": [], "verdicts": [], "plans": [], "results": [], "outcomes": []}, INFO)
r = w.write_post(skipped, make_generate([good_daily()]), "daily")
check("a skipped day is refused and the model is never called", r["refused"] and "skipped" in r["refused"] and calls == [])
r = w.write_post(dict(DAY, day_status="not_settled_yet"), make_generate([good_daily()]), "daily")
check("an unsettled day is refused", "not_settled_yet" in r["refused"] and calls == [])
r = w.write_post(dict(WEEK, complete=False, warnings=["2026-10-09: no run recorded"]), make_generate([good_daily()]), "weekly")
check("an incomplete week is refused with the warnings", "incomplete" in r["refused"] and "no run recorded" in r["refused"] and calls == [])

weekly_text = " ".join(["The week was small and the bot stayed inside its rules."] * 15)
weekly_draft = {"title": "NSE paper trading: week of 5-9 October 2026", "meta_description": "One week of a paper-trading bot on the NSE, with fake money.",
                "body_markdown": "A simulation with fake money. Gross result ₹550.00, 5 trades.\n\n## What the numbers say\n\n" + weekly_text + "\n\n## What I will test next week\n\n" + weekly_text + "\n\n" + weekly_text}
r = w.write_post(WEEK, make_generate([weekly_draft]), "weekly")
check("a weekly post passes and has both tables", r["ok"] and "| Day | Trades |" in r["body_markdown"] and "| Measure | This week |" in r["body_markdown"])

# ---------------------------------------------------------------- 6. the model wrapper
print("6. The model wrapper")
class FakeLLM:
    def with_structured_output(self, schema):
        class Runner:
            def invoke(self, prompt):
                return schema(title="T", meta_description="M", body_markdown="B " + prompt[:5])
        return Runner()
out = w.make_generate(FakeLLM())("hello world")
check("make_generate returns the three fields as a dict", out == {"title": "T", "meta_description": "M", "body_markdown": "B hello"})

print()
print("ALL CHECKS PASSED" if not BAD else "FAILED: " + "; ".join(BAD))
sys.exit(1 if BAD else 0)
