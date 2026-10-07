"""The backfill against a stand-in database and prices (no network). Run:  python test_backfill.py"""
import contextlib, copy, io, json, os, sys
sys.path.insert(0, ".")
from datetime import datetime, timedelta, timezone
import pandas as pd, supabase, yfinance as yf

IST = timezone(timedelta(hours=5, minutes=30))
os.environ.update({"SUPABASE_URL": "x", "SUPABASE_KEY": "y"})
DB, DL = {}, []
class Q:
    def __init__(self, name): self.name, self.f, self.op, self.payload, self.conflict, self.ord = name, [], "select", None, None, None
    def select(self, c): self.op = "select"; return self
    def eq(self, c, v): self.f.append((c, v)); return self
    def order(self, c, desc=False): self.ord = (c, desc); return self
    def insert(self, rows): self.op, self.payload = "insert", rows; return self
    def upsert(self, rows, on_conflict=None): self.op, self.payload, self.conflict = "upsert", rows, on_conflict; return self
    def execute(self):
        class R: pass
        r = R(); rows = DB.setdefault(self.name, [])
        if self.op == "select":
            out = [x for x in rows if all(x.get(c) == v for c, v in self.f)]
            if self.ord: out.sort(key=lambda x: x[self.ord[0]], reverse=self.ord[1])
            r.data = copy.deepcopy(out)
        else:
            keys = self.conflict.split(","); new = self.payload if isinstance(self.payload, list) else [self.payload]
            for row in new:
                json.dumps(row); rows[:] = [x for x in rows if any(x.get(k) != row.get(k) for k in keys)] + [row]
            r.data = new
        return r
class Fake:
    def table(self, n): return Q(n)
supabase.create_client = lambda u, k: Fake()

DAYS = {"2026-10-05": 0.8, "2026-10-06": -0.5, "2026-10-07": 0.0}          # each day has its own slope, to prove the right day's candles are used
def fake_download(tickers, **kw):
    DL.append(kw.get("period"))
    parts = {}
    for t in tickers:
        if t.split(".")[0] != "AAA": continue
        frames = []
        for day, slope in DAYS.items():
            idx = pd.date_range(f"{day} 09:15", f"{day} 15:25", freq="5min", tz="Asia/Kolkata")
            close = [1000 + max((ts.hour * 60 + ts.minute - 575) / 5, 0) * slope for ts in idx]
            frames.append(pd.DataFrame({"Open": close, "High": [c + 0.5 for c in close], "Low": [c - 0.5 for c in close], "Close": close}, index=idx))
        parts[t] = pd.concat(frames)
    return pd.concat(parts, axis=1) if parts else pd.DataFrame()
yf.download = fake_download
import notify; notify.send_telegram = lambda m: True
import settle_day, backfill_report_cards as bf
class FixedDT(datetime):
    fixed = datetime(2026, 10, 8, 10, 0, tzinfo=IST)
    @classmethod
    def now(cls, tz=None): return cls.fixed
bf.datetime = FixedDT; settle_day.datetime = FixedDT

def seed():
    DB.clear(); DL.clear()
    DB["runs"] = [
        {"id": 1, "market_date": "2026-10-05", "status": "finished", "data_is_live": True,  "started_at": "2026-10-05T04:06:31+00:00"},
        {"id": 2, "market_date": "2026-10-06", "status": "finished", "data_is_live": True,  "started_at": "2026-10-06T04:06:31+00:00"},
        {"id": 3, "market_date": "2026-10-07", "status": "finished", "data_is_live": True,  "started_at": "2026-10-07T04:06:31+00:00"},
        {"id": 4, "market_date": "2026-10-07", "status": "finished", "data_is_live": True,  "started_at": "2026-10-07T09:00:00+00:00"},   # a later run the same day: THIS is official
        {"id": 5, "market_date": "2026-10-04", "status": "finished", "data_is_live": False, "started_at": "2026-10-04T04:00:00+00:00"},   # stale test run
        {"id": 6, "market_date": "2026-10-08", "status": "finished", "data_is_live": True,  "started_at": "2026-10-08T04:06:31+00:00"},   # today: not over
        {"id": 7, "market_date": "2026-08-01", "status": "finished", "data_is_live": True,  "started_at": "2026-08-01T04:06:31+00:00"},   # far too old
    ]
    DB["candidates"] = [{"run_id": r, "symbol": "AAA", "rank": 1, "price": 1000.0, "avg_range": 20.0} for r in (1, 2, 3, 4, 5, 6, 7)]
    DB["verdicts"] = [{"run_id": r, "symbol": "AAA", "on_watchlist": True} for r in (1, 2, 3, 4, 5, 6, 7)]
    DB["candidate_outcomes"] = []

def run(*flags):
    sys.argv = ["backfill_report_cards.py", *flags]; buf = io.StringIO()
    with contextlib.redirect_stdout(buf): bf.main()
    return buf.getvalue()

failures = []
def check(label, ok, detail=""):
    print(f"   {'ok ' if ok else 'BAD'} {label} {detail}")
    if not ok: failures.append(label)

print("== 1. first run: grades the official run of each past day, and nothing else ==")
seed(); text = run()
graded = sorted(r["run_id"] for r in DB["candidate_outcomes"])
check("runs 1, 2 and 4 graded (4 is the official run of Oct 7, not 3)", graded == [1, 2, 4], f"{graded}")
check("no stale run, no today, no too-old day", all(x not in graded for x in (3, 5, 6, 7)))
by = {r["run_id"]: r for r in DB["candidate_outcomes"]}
check("each day used ITS OWN candles (rising, falling, flat)", by[1]["return_pct"] > 5 and by[2]["return_pct"] < -3 and abs(by[4]["return_pct"]) < 0.001, f"{by[1]['return_pct']}% / {by[2]['return_pct']}% / {by[4]['return_pct']}%")
check("the longer 5-minute history was requested", set(DL) == {"60d"}, f"{set(DL)}")
check("the printout explains each skip", "skipped, the day is not over" in text and "too old" in text, "")

print("== 2. second run: nothing to do, nothing duplicated ==")
DL.clear(); text = run()
check("already-graded days are skipped", text.count("already has a report card") == 3 and not DL)
check("still three rows", len(DB["candidate_outcomes"]) == 3)

print("== 3. --force redoes them without duplicating ==")
run("--force"); check("three rows after --force", len(DB["candidate_outcomes"]) == 3)

print("== 4. one failing day does not stop the others ==")
seed(); real = settle_day.get_candidates
def flaky(run_id):
    if run_id == 2: raise RuntimeError("simulated outage")
    return real(run_id)
settle_day.get_candidates = flaky; text = run(); settle_day.get_candidates = real
check("day 2 reported as FAILED, days 1 and 4 still graded", "FAILED" in text and sorted(r["run_id"] for r in DB["candidate_outcomes"]) == [1, 4], "")
print("\nALL CHECKS PASSED" if not failures else f"\n{len(failures)} CHECK(S) FAILED: {failures}")
sys.exit(1 if failures else 0)
