"""Settlement with the report card, against a stand-in database and stand-in prices (no network). Run:  python test_report_card.py"""
import copy, html, json, os, re, sys
sys.path.insert(0, ".")
from datetime import datetime, timedelta, timezone
import pandas as pd, supabase, yfinance as yf

IST = timezone(timedelta(hours=5, minutes=30))
os.environ.update({"SUPABASE_URL": "x", "SUPABASE_KEY": "y"})

DB = {}
class Q:
    def __init__(self, name): self.name, self.f, self.op, self.payload, self.conflict, self.ord, self.lim = name, [], "select", None, None, None, None
    def select(self, cols): self.op = "select"; return self
    def eq(self, c, v): self.f.append(("eq", c, v)); return self
    def in_(self, c, vs): self.f.append(("in", c, list(vs))); return self
    def order(self, c, desc=False): self.ord = (c, desc); return self
    def limit(self, n): self.lim = n; return self
    def insert(self, rows): self.op, self.payload = "insert", rows; return self
    def upsert(self, rows, on_conflict=None): self.op, self.payload, self.conflict = "upsert", rows, on_conflict; return self
    def execute(self):
        class R: pass
        r = R(); rows = DB.setdefault(self.name, [])
        if self.op == "select":
            out = [x for x in rows if all((x.get(c) == v) if k == "eq" else (x.get(c) in v) for k, c, v in self.f)]
            if self.ord: out.sort(key=lambda x: x[self.ord[0]], reverse=self.ord[1])
            r.data = copy.deepcopy(out[: self.lim] if self.lim else out)
        elif self.op == "insert":
            for row in (self.payload if isinstance(self.payload, list) else [self.payload]):
                json.dumps(row); rows.append({"id": len(rows) + 1, **row})
            r.data = self.payload
        else:
            keys = self.conflict.split(","); new = self.payload if isinstance(self.payload, list) else [self.payload]
            for row in new:
                json.dumps(row)
                rows[:] = [x for x in rows if any(x.get(k) != row.get(k) for k in keys)] + [row]
            r.data = new
        return r
class Fake:
    def table(self, n): return Q(n)
supabase.create_client = lambda u, k: Fake()

def frame_for(kind, day="2026-10-05"):
    idx = pd.date_range(f"{day} 09:15", f"{day} 15:25", freq="5min", tz="Asia/Kolkata")
    close = []
    for ts in idx:
        k = max((ts.hour * 60 + ts.minute - 575) / 5, 0)
        close.append({"AAA": 1000 + k * 0.8, "BBB": 500 - k * 0.5, "DDD": 300.0}[kind])
    return pd.DataFrame({"Open": close, "High": [c + 0.5 for c in close], "Low": [c - 0.5 for c in close], "Close": close}, index=idx)
def fake_download(tickers, **kw):
    parts = {t: frame_for(t.split(".")[0]) for t in tickers if t.split(".")[0] in ("AAA", "BBB", "DDD")}
    return pd.concat(parts, axis=1) if parts else pd.DataFrame()
yf.download = fake_download
class FakeTicker:
    def __init__(self, s): pass
    def history(self, period=None, interval=None):
        idx = pd.date_range("2026-10-05 09:15", "2026-10-05 15:25", freq="5min", tz="Asia/Kolkata")
        c = [24000 + i for i in range(len(idx))]
        return pd.DataFrame({"Open": c, "High": c, "Low": c, "Close": c}, index=idx)
yf.Ticker = FakeTicker

import notify
MSGS = []
notify.send_telegram = lambda message: (MSGS.append(message), True)[1]
import settle_day
class FixedDT(datetime):
    fixed = datetime(2026, 10, 5, 16, 0, tzinfo=IST)
    @classmethod
    def now(cls, tz=None): return cls.fixed
settle_day.datetime = FixedDT

def seed(with_plans=True, with_candidates=True):
    DB.clear()
    DB["runs"] = [{"id": 1, "market_date": "2026-10-05", "status": "finished", "data_is_live": True, "started_at": "2026-10-05T04:06:31+00:00", "settings": {"balance_at_start": 100000}}]
    DB["plans"] = ([{"id": 1, "run_id": 1, "symbol": "AAA", "status": "accepted", "entry": 1000.0, "stop": 992.0, "target": 1012.0, "shares": 40, "cost": 40000.0},
                    {"id": 2, "run_id": 1, "symbol": "BBB", "status": "accepted", "entry": 500.0, "stop": 495.0, "target": 506.0, "shares": 100, "cost": 50000.0}] if with_plans else [])
    DB["candidates"] = ([{"id": i + 1, "run_id": 1, **c} for i, c in enumerate([
        {"symbol": "AAA", "rank": 1, "price": 1000.0, "avg_range": 20.0}, {"symbol": "BBB", "rank": 2, "price": 500.0, "avg_range": 10.0},
        {"symbol": "DDD", "rank": 3, "price": 300.0, "avg_range": 6.0}, {"symbol": "CCC", "rank": 4, "price": 100.0, "avg_range": 5.0}])] if with_candidates else [])
    DB["verdicts"] = [{"run_id": 1, "symbol": "AAA", "on_watchlist": True}, {"run_id": 1, "symbol": "BBB", "on_watchlist": True},
                      {"run_id": 1, "symbol": "DDD", "on_watchlist": False}, {"run_id": 1, "symbol": "CCC", "on_watchlist": False}]
    DB["trade_results"], DB["daily_equity"], DB["candidate_outcomes"] = [], [], []
    MSGS.clear()

def run(argv=("2026-10-05",)):
    sys.argv = ["settle_day.py", *argv]
    out = []
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try: settle_day.main()
        except SystemExit as e:
            if e.code not in (0, None): out.append("EXIT: " + str(e.code))
    return buf.getvalue() + "\n".join(out)

failures = []
def check(label, ok, detail=""):
    print(f"   {'ok ' if ok else 'BAD'} {label} {detail}")
    if not ok: failures.append(label)
plain = lambda m: re.sub(r"</?(b|i|code)>", "", html.unescape(m))

print("== 1. a normal day: the balance AND the report card ==")
seed(); text = run()
check("balance updated as before (100,000 + 480 - 500)", DB["daily_equity"][0]["ending_balance"] == 99980.0, f"{DB['daily_equity'][0]['ending_balance']}")
keys = {(r["run_id"], r["symbol"]) for r in DB["candidate_outcomes"]}
check("report card saved for AAA, BBB and DDD, not CCC (no prices)", keys == {(1, "AAA"), (1, "BBB"), (1, "DDD")}, f"{sorted(keys)}")
by = {r["symbol"]: r for r in DB["candidate_outcomes"]}
check("AAA: what-if trade hit its target", by["AAA"]["std_outcome"] == "target_hit" and by["AAA"]["return_pct"] > 5, f"{by['AAA']['std_outcome']}, return {by['AAA']['return_pct']}%")
check("BBB: what-if trade hit its stop", by["BBB"]["std_outcome"] == "stop_hit", f"{by['BBB']['std_outcome']}")
check("DDD (flat): closed at the end, return 0", by["DDD"]["std_outcome"] == "closed_at_end" and by["DDD"]["return_pct"] == 0.0)
check("the output says what was saved and who is missing", "saved 3 of 4 candidates (no data for: CCC)" in text, "")
msg = plain(MSGS[-1])
check("the Telegram message carries the report-card line", "Report card" in msg and "strong-catalyst stocks" in msg and "the other candidates +0.00% (1)" in msg, "")
print("      line:", [l for l in msg.splitlines() if "Report card" in l][0])

print("== 2. running it again changes nothing and duplicates nothing ==")
before = copy.deepcopy(DB["candidate_outcomes"]); run()
check("still exactly three rows", len(DB["candidate_outcomes"]) == 3)
check("one daily_equity row", len(DB["daily_equity"]) == 1)

print("== 3. the report card breaks: the balance is still saved and the message still goes out ==")
seed(); real = settle_day.get_candidates
settle_day.get_candidates = lambda run_id: (_ for _ in ()).throw(RuntimeError("simulated outage in the report card"))
text = run(); settle_day.get_candidates = real
check("balance row saved anyway", len(DB["daily_equity"]) == 1 and len(DB["trade_results"]) == 2)
check("the problem is reported, not hidden", "could not record the report card" in text)
check("the settlement message was still sent, without the extra line", "Day settled" in plain(MSGS[-1]) and "Report card" not in plain(MSGS[-1]))
check("no half-written report card", len(DB["candidate_outcomes"]) == 0)

print("== 4. a day with candidates but no accepted plans still gets a report card ==")
seed(with_plans=False); run()
check("zero-trade day recorded", len(DB["daily_equity"]) == 1 and DB["daily_equity"][0]["trades"] == 0)
check("report card saved for the three that have prices", len(DB["candidate_outcomes"]) == 3)

print("== 5. a run with no candidates at all ==")
seed(with_candidates=False); text = run()
check("settlement completes and says so", "no candidates" in text and len(DB["daily_equity"]) == 1)
print("\nALL CHECKS PASSED" if not failures else f"\n{len(failures)} CHECK(S) FAILED: {failures}")
sys.exit(1 if failures else 0)
