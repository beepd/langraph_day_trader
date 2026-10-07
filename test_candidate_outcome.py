"""Checks the report-card code against a stand-in database (no network). Run from the project folder:  python test_outcomes_storage.py"""
import json, os, sys
sys.path.insert(0, ".")
os.environ.update({"SUPABASE_URL": "x", "SUPABASE_KEY": "y"})
import supabase
import pandas as pd
from settlement import candidate_outcome, outcomes_for_candidates

STORE, CALLS = {}, []
class Q:
    def __init__(self, name): self.name, self.f, self.payload, self.op, self.conflict = name, [], None, "select", None
    def select(self, c): self.op = "select"; return self
    def eq(self, c, v): self.f.append((c, v)); return self
    def order(self, *a, **k): return self
    def upsert(self, rows, on_conflict=None): self.op, self.payload, self.conflict = "upsert", rows, on_conflict; return self
    def execute(self):
        class R: pass
        r = R(); table = STORE.setdefault(self.name, {})
        if self.op == "upsert":
            json.dumps(self.payload)                                    # everything must be JSON-safe
            CALLS.append((self.name, self.conflict, len(self.payload)))
            for row in self.payload: table[tuple(row[k] for k in self.conflict.split(","))] = row
            r.data = self.payload
        else:
            r.data = [row for row in table.values() if all(row.get(c) == v for c, v in self.f)]
        return r
class Fake:
    def table(self, n): return Q(n)
supabase.create_client = lambda u, k: Fake()
import storage

failures = []
def check(label, ok, detail=""):
    print(f"   {'ok ' if ok else 'BAD'} {label} {detail}")
    if not ok: failures.append(label)

stamp = lambda hh, mm: pd.Timestamp(f"2026-10-07 {hh:02d}:{mm:02d}", tz="Asia/Kolkata")
candles_pfc = [(stamp(9, 40), 331.5, 328.0, 329.0), (stamp(10, 20), 329.0, 327.0, 327.5), (stamp(15, 10), 330.0, 327.5, 329.5)]
candles_abb = [(stamp(9, 40), 7130.0, 7110.0, 7125.0), (stamp(15, 10), 7150.0, 7100.0, 7140.0)]
candidates = [{"symbol": "PFC", "price": 331.0, "avg_range": 6.4, "rank": 1}, {"symbol": "ABB", "price": 7122.5, "avg_range": 165.2, "rank": 2},
              {"symbol": "NOCANDLES", "price": 100.0, "avg_range": 5.0, "rank": 3}, {"symbol": "NORANGE", "price": 100.0, "avg_range": None, "rank": 4}]

print("== 1. one report per candidate; the ones that cannot be reported are left out ==")
reports = outcomes_for_candidates(candidates, {"PFC": candles_pfc, "ABB": candles_abb})
check("reports for PFC and ABB only", sorted(reports) == ["ABB", "PFC"], f"{sorted(reports)}")
check("entry price is carried along", reports["PFC"]["entry_price"] == 331.0)
check("PFC what-if trade: stop hit (stop 328.40)", reports["PFC"]["std_outcome"] == "stop_hit" and reports["PFC"]["std_stop"] == 328.4, f"{reports['PFC']['std_outcome']} {reports['PFC']['std_stop']}")
check("report equals the step-1 function", reports["ABB"]["return_pct"] == candidate_outcome(7122.5, 165.2, candles_abb)["return_pct"])

print("== 2. saving ==")
saved = storage.save_candidate_outcomes(7, reports)
check("two rows saved", saved == 2 and STORE["candidate_outcomes"].keys() == {(7, "PFC"), (7, "ABB")})
check("an upsert on run_id,symbol was used", CALLS[-1] == ("candidate_outcomes", "run_id,symbol", 2), f"{CALLS[-1]}")
row = STORE["candidate_outcomes"][(7, "PFC")]
check("the exit time travelled as ISO text", isinstance(row["std_exit_time"], str) and row["std_exit_time"].startswith("2026-10-07T09:40"), f"{row['std_exit_time']}")
saved_again = storage.save_candidate_outcomes(7, reports)
check("saving again does not duplicate", len(STORE["candidate_outcomes"]) == 2 and saved_again == 2)
check("nothing to save -> 0 and no database call", storage.save_candidate_outcomes(7, {}) == 0 and CALLS[-1][2] == 2)

print("== 3. a report whose what-if trade is empty (range below one price step) still saves ==")
tiny = outcomes_for_candidates([{"symbol": "TINY", "price": 100.0, "avg_range": 0.04}], {"TINY": candles_abb})
check("saved with empty what-if fields", storage.save_candidate_outcomes(7, tiny) == 1 and STORE["candidate_outcomes"][(7, "TINY")]["std_outcome"] is None)

print("== 4. reading candidates back ==")
STORE["candidates"] = {(7, c["symbol"]): {**c, "run_id": 7} for c in candidates}
got = storage.get_candidates(7)
check("four candidates read for run 7", len(got) == 4, f"{[g['symbol'] for g in got]}")
print("\nALL CHECKS PASSED" if not failures else f"\n{len(failures)} CHECK(S) FAILED: {failures}")
sys.exit(1 if failures else 0)