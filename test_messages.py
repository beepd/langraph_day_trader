"""Telegram messages are complete: nothing is cut short. Offline. Run:  python test_messages.py"""
import sys
sys.path.insert(0, ".")
import messages as m
from notify import _chunks, MAX_LENGTH

bad = []
def check(name, cond):
    print(("  ok: " if cond else "  BAD: ") + name)
    if not cond: bad.append(name)

LONG = "Profit rose sharply after the company announced results. " * 12          # ~670 characters
print("== analyst ==")
t = m.analyst([("TCS", LONG, "earnings · happened · figure in headline")], 5, mode="checklist")
check("long reason shown in full", LONG.strip() in t)
check("label and mode shown", "earnings · happened · figure in headline" in t and "checklist" in t)
t = m.analyst([(f"S{i}", f"reason {i}") for i in range(9)], 9)
check("all 9 watchlist stocks shown, no '…and N more'", all(f"S{i}" in t for i in range(9)) and "more" not in t)
t = m.analyst([("TCS", "r", None)], 3, dropped=[("HCLTECH", "Information Technology", "TCS")])
check("sector-dropped stock explained", "HCLTECH" in t and "TCS already covers the same sector (Information Technology)" in t)
check("no strong catalyst message unchanged", "no strong catalyst among 4" in m.analyst([], 4))
check("no strong but dropped still listed", "WIPRO" in m.analyst([], 4, dropped=[("WIPRO", "IT", "TCS")]))
check("HTML in a reason is escaped", "&lt;b&gt;" in m.analyst([("A", "<b>x</b> & y")], 1))

print("== screener / news ==")
top = [(f"S{i}", 100.0, 1.0, 1.5) for i in range(10)]
t = m.screener(10, 100, top, True)
check("all 10 movers listed", all(f"S{i}</b>" in t for i in range(10)) and "more go on" not in t)
t = m.news(2, 10, [f"N{i}" for i in range(9)])
check("all stocks without headlines listed", all(f"N{i}" in t for i in range(9)))

print("== plans ==")
plan = {"symbol": "TCS", "shares": 10, "entry": 100.0, "stop": 98.0, "target": 104.0, "max_loss": 20, "max_gain": 40,
        "nudges": ["stop moved from 98.50 to 98.00"], "reason": LONG}
t = m.plans([plan], [("SBIN", LONG)], [], 100000)
check("planner's reason shown in full", LONG.strip() in t)
check("rejection reason shown in full", t.count(LONG.strip()) == 2)
check("nudge text shown", "stop moved from 98.50 to 98.00" in t)
plan2 = dict(plan, nudges=[], reason="")
check("no 'why' line when there is no reason; no nudge line", "why:" not in m.plans([plan2], [], [], 1000) and "adjusted" not in m.plans([plan2], [], [], 1000))

print("== errors ==")
E = "x" * 900
check("balance problem in full", E in m.balance_problem(E))
check("save error in full", E in m.run_complete([], 1000, 1, E))
check("crash in full", E in m.crash("Morning run", RuntimeError(E)))

print("== the sender splits, never cuts ==")
msg = "\n".join(f"line {i} " + "y" * 60 for i in range(300))
parts = _chunks(msg)
check("long message becomes several parts, each within the limit", len(parts) > 1 and all(len(p) <= MAX_LENGTH for p in parts))
check("joined parts equal the message exactly", "\n".join(parts) == msg)
one = "z" * (MAX_LENGTH * 2 + 10)
check("one enormous line is split with nothing lost", "".join(_chunks(one)) == one)

print("\nALL CHECKS PASSED" if not bad else f"\n{len(bad)} CHECK(S) FAILED: {bad}")
sys.exit(1 if bad else 0)
