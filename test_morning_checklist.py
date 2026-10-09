"""Stage 2 of 7b: the checklist analyst inside the live run, with stand-in modules and a fake model (no network,
no database, no packages beyond pydantic/dotenv). Run:  python test_morning_checklist.py"""
import os, sys, types
sys.path.insert(0, ".")
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
os.environ.update({"SUPABASE_URL": "x", "SUPABASE_KEY": "y", "TELEGRAM_ENABLED": "0"})

# ---- stand-ins for the heavy packages -------------------------------------------------------------------------
class FakeGraph:
    def __init__(self, *a, **k): self.nodes = {}
    def add_node(self, name, fn): self.nodes[name] = fn
    def add_edge(self, *a): pass
    def add_conditional_edges(self, *a): pass
    def compile(self): return self
lg = types.ModuleType("langgraph"); lgg = types.ModuleType("langgraph.graph")
lgg.StateGraph, lgg.START, lgg.END = FakeGraph, "START", "END"
sys.modules.update({"langgraph": lg, "langgraph.graph": lgg})
sys.modules["yfinance"] = types.ModuleType("yfinance")
sup = types.ModuleType("supabase"); sup.create_client = lambda u, k: None; sys.modules["supabase"] = sup

class FakeLLM:
    """Answers from a script keyed by company name; counts calls."""
    script, calls = {}, {}
    def with_structured_output(self, schema):
        outer = self
        class Bound:
            def invoke(self, prompt):
                for company, make in outer.script.items():
                    if f"{company} is up" in prompt:
                        outer.calls[company] = outer.calls.get(company, 0) + 1
                        return make()
                raise AssertionError("model asked about an unexpected stock:\n" + prompt[:200])
        return Bound()
fake_llm = FakeLLM()
ls = types.ModuleType("llm_setup"); ls.build_llm = lambda: fake_llm; ls.PROVIDER, ls.MODEL = "fake", "fake-model"
sys.modules["llm_setup"] = ls

import morning_run as M
import storage as S
from checklist import Checklist

ok = 0
def check(name, cond):
    global ok
    if not cond:
        print("  FAIL:", name); sys.exit(1)
    ok += 1; print("  ok:", name)

M.VERBOSE = False
sent = []
M.send_telegram = lambda text: sent.append(text)

now = datetime.now(IST)
def ago(days): return (now - timedelta(days=days)).isoformat()
def h(text, days): return {"text": text, "title": text, "source": "x", "published_at": ago(days), "url": "u"}
def answer(event, status="happened", bullish=True, number=True, reason="Short factual reason.", cites=(1,)):
    return lambda: Checklist(event_type=event, status=status, bullish=bullish, has_number=number,
                             reason=reason, source_numbers=list(cites))

ORDER = ["TCS", "HCLTECH", "APOLLOHOSP", "SBIN", "ONGC", "INFY", "WIPRO"]
state = {
    "stocks": ORDER,
    "changes": {s: 2.0 for s in ORDER}, "rel_volumes": {s: 1.5 for s in ORDER},
    "headlines": {
        "TCS": [h("TCS Q2 profit rises 9%", 0)],
        "HCLTECH": [h("HCL Technologies Q2 profit up 7%", 0)],
        "APOLLOHOSP": [h("Apollo Hospitals gets drug regulator nod", 1)],
        "SBIN": [h("State Bank of India target raised to 900 by broker", 6)],
        "ONGC": [h("Top stocks to buy today", 0)],
        "INFY": [],
        "WIPRO": [h("Wipro wins order", 0)],
    },
}
U = M.UNIVERSE
fake_llm.script = {
    U["TCS"]: answer("earnings"),
    U["HCLTECH"]: answer("earnings"),
    U["APOLLOHOSP"]: answer("regulatory_approval"),
    U["SBIN"]: answer("broker_target"),
    U["ONGC"]: answer("other", status="rumour_or_opinion", bullish=False, number=False, cites=()),
    U["WIPRO"]: answer("order_win", reason="x" * 500),            # garbled, every time
}

print("== 1. the checklist analyst on a 7-stock morning ==")
M.ANALYST_MODE = "checklist"
out = M.analyst_step(state)
v = out["verdicts"]
check("watchlist is TCS and APOLLOHOSP, in rank order", out["watchlist"] == ["TCS", "APOLLOHOSP"])
check("every stock has a verdict", set(v) == set(ORDER))
check("TCS: strong, earnings, happened, number", (v["TCS"].strength, v["TCS"].catalyst_type, v["TCS"].event_status, v["TCS"].has_number) == ("strong", "earnings", "happened", True))
check("HCLTECH: strong by rules but dropped by the sector rule",
      v["HCLTECH"].strength == "strong" and "HCLTECH" not in out["watchlist"] and "sector rule" in v["HCLTECH"].checklist_notes and "TCS" in v["HCLTECH"].checklist_notes)
check("SBIN: stale headline means weak, with a reason", v["SBIN"].strength == "weak" and "older than" in v["SBIN"].checklist_notes)
check("SBIN: stale headline means has_catalyst is False", v["SBIN"].has_catalyst is False)
check("ONGC: 'other' is weak", v["ONGC"].strength == "weak" and not v["ONGC"].has_catalyst)
check("Telegram message shows the event label and the whole reason", "earnings · happened · figure in headline" in sent[0] and "Short factual reason." in sent[0])
check("INFY: no headlines, model not asked", v["INFY"].reason == "No headlines found" and U["INFY"] not in fake_llm.calls and v["INFY"].strength == "weak")
check("WIPRO: garbled twice, asked exactly twice, weak, no answer", fake_llm.calls[U["WIPRO"]] == 2 and v["WIPRO"].strength == "weak" and "garbled" in v["WIPRO"].reason)
check("a Telegram analyst message was sent with the two watchlist stocks", len(sent) == 1 and "TCS" in sent[0] and "APOLLOHOSP" in sent[0] and "same sector" in sent[0])

print("== 2. the model cannot talk its way past the code ==")
sent.clear(); fake_llm.calls.clear()
state2 = dict(state, stocks=["SBIN"], headlines={"SBIN": [h("Banks rally on rate hopes", 0)]})
fake_llm.script = {U["SBIN"]: answer("broker_target")}
r = M.analyst_step(state2)
check("claims broker target but the headline does not name the bank: weak, overruled", r["watchlist"] == [] and r["verdicts"]["SBIN"].reason.startswith("REJECTED by code"))

print("== 3. the prompt ==")
p = M.checklist_prompt("Acme Ltd.", 2.5, 1.7, "[1] Acme wins order\n")
for word in ("earnings", "order_win", "regulatory_approval", "deal_or_acquisition", "broker_target", "block_deal", "dividend",
             "product_or_partnership", "management_change", "sector_or_market_move", "other",
             "happened", "expected", "rumour_or_opinion", "not older than 3 days", "Do not judge"):
    check(f"prompt mentions {word}", word in p)
check("prompt carries the company line and headlines", "Acme Ltd. is up 2.5%" in p and "[1] Acme wins order" in p)
check("prompt's freshness days match FRESH_DAYS", f"{M.FRESH_DAYS} days" in p)

print("== 4. classic mode is untouched ==")
check("classic analyst still registered", M.ANALYSTS["classic"] is M.analyze_news)
M.ANALYST_MODE = "classic"
called = []
M.ANALYSTS = dict(M.ANALYSTS, classic=lambda s: called.append("classic") or {"verdicts": {}, "watchlist": []})
M.analyst_step({}); check("dispatcher calls classic when ANALYST_MODE=classic", called == ["classic"])
M.ANALYSTS["checklist"] = lambda s: called.append("checklist") or {"verdicts": {}, "watchlist": []}
M.ANALYST_MODE = "checklist"; M.analyst_step({}); check("dispatcher calls checklist when ANALYST_MODE=checklist", called == ["classic", "checklist"])
check("graph node is the dispatcher", M.graph.nodes["analyze_news_node"] is M.analyst_step)

print("== 5. settings saved with the run ==")
M.ANALYST_MODE = "classic"; st = M.build_settings(1000.0)
check("classic: analyst_mode recorded, no checklist knobs", st["analyst_mode"] == "classic" and "fresh_days" not in st)
M.ANALYST_MODE = "checklist"; st = M.build_settings(1000.0)
check("checklist: knobs recorded", st["analyst_mode"] == "checklist" and st["fresh_days"] == 3 and st["max_per_sector"] == 1)

print("== 6. storage rows ==")
cv = M.CheckedVerdict(True, True, "strong", "earnings", "r", [1], "happened", True, "n")
classic = M.Verdict(has_catalyst=True, bullish=True, strength="strong", catalyst_type="earnings", reason="REJECTED by code: x", source_numbers=[1])
row = S._verdict_row(1, "TCS", cv, True)
check("checklist row has the new columns", (row["event_status"], row["has_number"], row["checklist_notes"]) == ("happened", True, "n"))
row = S._verdict_row(1, "TCS", classic, False)
check("classic row has NO new columns (safe before the migration)", "event_status" not in row and row["overruled_by_code"] is True and row["on_watchlist"] is False)

print("== 7. fail closed before trading ==")
class BadClient:
    def table(self, n): raise RuntimeError("column does not exist")
S.get_client = lambda: BadClient()
try: S.check_checklist_columns(); check("raises when columns are missing", False)
except RuntimeError as e: check("raises when columns are missing, naming migration 006", "migration_006" in str(e))

calls = []
M.start_run = lambda *a: calls.append("start_run") or 7
M.check_checklist_columns = lambda: (_ for _ in ()).throw(RuntimeError("needs migration_006"))
M.app = types.SimpleNamespace(invoke=lambda s: calls.append("invoke") or {})
M.mark_run = lambda *a, **k: None
M.ANALYST_MODE = "checklist"
try: M.main(); check("main stops", False)
except RuntimeError: check("checklist mode: main stops on missing columns BEFORE the pipeline runs", "invoke" not in calls and "start_run" in calls)
calls.clear(); M.ANALYST_MODE = "chekclist"
try: M.main(); check("typo stops", False)
except ValueError as e: check("a typo in ANALYST_MODE is refused before anything is recorded", calls == [] and "classic" in str(e) and "checklist" in str(e))

print(f"\nALL CHECKS PASSED ({ok})")