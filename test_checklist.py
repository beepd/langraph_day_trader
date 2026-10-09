"""Tests the 7b checklist decision logic with stand-in headlines (no network, no database, no model).
Run:  python test_checklist.py   (from the repo root, because it reads nifty100.csv and morning_run.py)"""
import ast
import csv
import sys
from datetime import date
from typing import get_args

sys.path.insert(0, ".")
from pydantic import ValidationError

import checklist as C

failures = []
def check(label, ok, detail=""):
    print(f"   {'ok ' if ok else 'BAD'} {label} {detail}")
    if not ok: failures.append(label)

TODAY = date(2026, 10, 9)
with open("nifty100.csv", newline="", encoding="utf-8-sig") as f:
    COMPANY = {row["Symbol"].strip(): row["Company Name"].strip() for row in csv.DictReader(f)}
SECTORS = C.load_sectors("nifty100.csv")

def hl(text, day="2026-10-09", time="09:05:00+05:30"):
    return {"text": text, "published_at": f"{day}T{time}"}

def answer(event_type="earnings", status="happened", bullish=True, has_number=True, source_numbers=(1,)):
    return C.Checklist(event_type=event_type, status=status, bullish=bullish, has_number=has_number,
                       reason="stand-in", source_numbers=list(source_numbers))

def decide(symbol, ans, headlines):
    return C.evaluate(symbol, COMPANY[symbol], ans, headlines, TODAY)

TCS_NEWS = [hl("TCS results: profit and revenue rise")]

print("== 1. this morning's five 'strong' picks, with stand-in headlines shaped like their reasons ==")
d = decide("TCS", answer("earnings"), TCS_NEWS)
check("TCS, earnings, happened: strong", d.strong, f"{d.failed}")
d = decide("APOLLOHOSP", answer("broker_target"), [hl("Apollo Hospitals target price raised by brokerage", day="2026-10-08")])
check("APOLLOHOSP, broker target raised yesterday: strong", d.strong, f"{d.failed}")
d = decide("VEDL", answer("dividend"), [hl("Vedanta announces interim dividend, record date 14 Oct")])
check("VEDL, dividend: NOT strong, and the reason says why", (not d.strong) and "dividend" in d.failed[0], f"{d.failed}")
d = decide("LTM", answer("product_or_partnership"), [hl("LTM expands partnership with Google Cloud", day="2026-10-08")])
check("LTM, partnership: NOT strong", not d.strong, f"{d.failed}")
d = decide("HCLTECH", answer("product_or_partnership"), [hl("HCL Technologies launches 20 AI solutions")])
check("HCLTECH, product launch: NOT strong", not d.strong, f"{d.failed}")

print("== 2. each rule on its own, against a good baseline (TCS earnings) ==")
check("baseline is strong", decide("TCS", answer(), TCS_NEWS).strong)
d = decide("TCS", answer(status="expected"), TCS_NEWS)
check("status 'expected': not strong", (not d.strong) and "expected" in d.failed[0], f"{d.failed}")
d = decide("TCS", answer(status="rumour_or_opinion"), TCS_NEWS)
check("status 'rumour_or_opinion': not strong", (not d.strong) and "rumour_or_opinion" in d.failed[0], f"{d.failed}")
d = decide("TCS", answer(bullish=False), TCS_NEWS)
check("not bullish: not strong", (not d.strong) and d.failed == ["the news is not bullish"], f"{d.failed}")
check("has_number False is still strong (the number is recorded, not required)", decide("TCS", answer(has_number=False), TCS_NEWS).strong)

d = decide("TCS", answer(), [hl("Markets rally on rate cut hopes")])
check("cited headline does not name the company: not strong", (not d.strong) and "names the company" in d.failed[0], f"{d.failed}")
d = decide("TCS", answer(source_numbers=()), TCS_NEWS)
check("nothing cited: not strong", (not d.strong) and "names the company" in d.failed[0], f"{d.failed}")
for bad in ([5], [0], [-1], [2, 99]):
    d = decide("TCS", answer(source_numbers=bad), TCS_NEWS)
    check(f"citation numbers {bad} point at no headline: not strong, no crash", not d.strong, f"{d.failed}")

print("== 3. freshness: the date comes from the headline, in India time ==")
def fresh_case(day, time="09:05:00+05:30"):
    return decide("TCS", answer(), [hl("TCS results: profit and revenue rise", day=day, time=time)])
check("published today: fresh", fresh_case("2026-10-09").strong)
check("3 days old: still fresh (the limit is inclusive)", fresh_case("2026-10-06").strong)
d = fresh_case("2026-10-05")
check("4 days old: not fresh", (not d.strong) and "older than 3 days" in d.failed[0], f"{d.failed}")
check("tomorrow's date (time-zone slack): accepted", fresh_case("2026-10-10").strong)
check("two days in the future: not trusted", not fresh_case("2026-10-11").strong)
check("late evening UTC on 5 Oct is already 6 Oct in India, so 3 days old: fresh", fresh_case("2026-10-05", "20:00:00+00:00").strong)
check("17:00 UTC on 5 Oct is 22:30 on 5 Oct in India, so 4 days old: not fresh", not fresh_case("2026-10-05", "17:00:00+00:00").strong)
check("a date with no time zone is read as India time", fresh_case("2026-10-06", "09:05:00").strong)
d = decide("TCS", answer(), [{"text": "TCS results: profit and revenue rise", "published_at": None}])
check("no date at all: not strong (fail closed)", (not d.strong) and "no date" in d.failed[0], f"{d.failed}")
check("a date nobody can read: not strong, no crash", not decide("TCS", answer(), [{"text": "TCS results", "published_at": "date unknown"}]).strong)
check("headline without a published_at key: not strong, no crash", not decide("TCS", answer(), [{"text": "TCS results"}]).strong)
two = [hl("TCS old story", day="2026-10-01"), hl("TCS results: profit and revenue rise")]
check("two cited, one stale and one fresh, both name the company: strong", decide("TCS", answer(source_numbers=(1, 2)), two).strong)
split = [hl("Markets rally on rate cut hopes"), hl("TCS old story", day="2026-10-01")]
d = decide("TCS", answer(source_numbers=(1, 2)), split)
check("one fresh headline that does not name the company + one naming but stale: NOT strong", not d.strong, f"{d.failed}")

print("== 4. every failed rule is reported, not just the first ==")
d = decide("VEDL", answer("dividend", status="expected", bullish=False), [hl("Vedanta announces interim dividend")])
check("three problems, three reasons", len(d.failed) == 3, f"{d.failed}")

print("== 4b. the two facts behind the reasons are reported too ==")
d = decide("TCS", answer(), TCS_NEWS)
check("good case: named and fresh", d.named_company and d.cited_fresh)
d = decide("TCS", answer(), [hl("Markets rally on rate cut hopes")])
check("headline does not name the company: neither named nor fresh", (not d.named_company) and (not d.cited_fresh))
d = decide("TCS", answer(), [hl("TCS results: profit and revenue rise", day="2026-10-01")])
check("names the company but is stale: named yes, fresh no", d.named_company and not d.cited_fresh)
d = decide("TCS", answer("dividend", status="expected"), TCS_NEWS)
check("a failed event type or status does not change those two facts", d.named_company and d.cited_fresh and not d.strong)

print("== 5. event types ==")
all_types = list(get_args(C.EventType))
check("11 event types, 5 of them can be strong", len(all_types) == 11 and len(C.STRONG_EVENT_TYPES) == 5)
check("the strong set only holds real event types", C.STRONG_EVENT_TYPES <= set(all_types))
wrong = [t for t in all_types if decide("TCS", answer(t), TCS_NEWS).strong != (t in C.STRONG_EVENT_TYPES)]
check("with everything else good, an event type is strong exactly when it is in the strong set", wrong == [], f"{wrong}")

print("== 6. the form itself rejects invented values ==")
for field, value in (("event_type", "rumour"), ("status", "maybe"), ("event_type", "")):
    try:
        C.Checklist(**{**dict(event_type="earnings", status="happened", bullish=True, has_number=True, reason="x", source_numbers=[1]), field: value})
        check(f"{field}={value!r} rejected", False)
    except ValidationError:
        check(f"{field}={value!r} rejected", True)

print("== 7. the sector rule ==")
kept, dropped = C.apply_sector_cap(["TCS", "LTM", "HCLTECH", "APOLLOHOSP"], SECTORS)
check("three IT stocks and one healthcare: first IT stock and healthcare kept", kept == ["TCS", "APOLLOHOSP"], f"{kept}")
check("the two later IT stocks are dropped, with the sector and who was kept instead",
      dropped == [("LTM", "Information Technology", "TCS"), ("HCLTECH", "Information Technology", "TCS")], f"{dropped}")
kept, _ = C.apply_sector_cap(["LTM", "TCS", "APOLLOHOSP"], SECTORS)
check("rank order decides, not the name", kept == ["LTM", "APOLLOHOSP"], f"{kept}")
kept, dropped = C.apply_sector_cap(["TCS", "LTM", "HCLTECH"], SECTORS, max_per_sector=2)
check("a limit of 2 keeps two IT stocks", kept == ["TCS", "LTM"] and len(dropped) == 1, f"{kept} {dropped}")
kept, dropped = C.apply_sector_cap(["NOSUCH1", "NOSUCH2", "TCS"], SECTORS)
check("stocks with an unknown sector share one group, so only the first is kept", kept == ["NOSUCH1", "TCS"] and dropped == [("NOSUCH2", "?", "NOSUCH1")], f"{kept} {dropped}")
check("empty list gives empty results", C.apply_sector_cap([], SECTORS) == ([], []))

print("== 8. the Nifty 100 file ==")
check("sectors loaded for all 100 stocks", len(SECTORS) == 100, f"{len(SECTORS)}")
check("no stock has an empty sector", all(SECTORS.values()))
check("TCS, WIPRO, HCLTECH, LTM, INFY are all Information Technology", all(SECTORS[s] == "Information Technology" for s in ("TCS", "WIPRO", "HCLTECH", "LTM", "INFY")))
check("VEDL is Metals & Mining, APOLLOHOSP is Healthcare", SECTORS["VEDL"] == "Metals & Mining" and SECTORS["APOLLOHOSP"] == "Healthcare")

print("== 9. mentions_company here is identical to the one in morning_run.py ==")
tree = ast.parse(open("morning_run.py", encoding="utf-8").read())
source = next(ast.get_source_segment(open("morning_run.py", encoding="utf-8").read(), n) for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "mentions_company")
live = {}
exec(source, live)
samples = [("TCS", "Tata Consultancy Services Ltd.", "TCS shares jump"), ("TCS", "Tata Consultancy Services Ltd.", "Tata Consultancy wins order"),
           ("SBILIFE", "SBI Life Insurance Company Ltd.", "SBI Life posts premium growth"), ("ITC", "ITC Ltd.", "The switch to a new pitch"),
           ("VEDL", "Vedanta Ltd.", "Vedanta announces dividend"), ("RELIANCE", "Reliance Industries Ltd.", "Markets rally"),
           ("M&M", "Mahindra & Mahindra Ltd.", "M&M launches SUV"), ("ABB", "ABB India Ltd.", ""), ("X", "Some Limited", "some limited news")]
check("same answer on every sample", all(live["mentions_company"](*s) == C.mentions_company(*s) for s in samples))

print("== 10. a whole morning ==")
ORDER = ["TCS", "MUTHOOTFIN", "VEDL", "LTM", "WIPRO", "APOLLOHOSP", "HCLTECH"]
NEWS = {"TCS": TCS_NEWS, "VEDL": [hl("Vedanta announces interim dividend")], "LTM": [hl("LTM expands partnership with Google Cloud")],
        "APOLLOHOSP": [hl("Apollo Hospitals target price raised by brokerage", day="2026-10-08")],
        "HCLTECH": [hl("HCL Technologies launches 20 AI solutions")]}
ANSWERS = {"TCS": answer("earnings"), "VEDL": answer("dividend"), "LTM": answer("product_or_partnership"),
           "APOLLOHOSP": answer("broker_target"), "HCLTECH": answer("product_or_partnership")}     # MUTHOOTFIN and WIPRO: no answer
watchlist, decisions, dropped = C.build_watchlist(ORDER, ANSWERS, NEWS, COMPANY, SECTORS, TODAY)
check("watchlist is TCS and APOLLOHOSP", watchlist == ["TCS", "APOLLOHOSP"], f"{watchlist}")
check("every ranked stock has a decision", list(decisions) == ORDER)
check("a stock with no answer is not strong and says so", (not decisions["MUTHOOTFIN"].strong) and "no checklist answer" in decisions["MUTHOOTFIN"].failed[0])
check("nothing dropped by the sector rule, because the IT stocks were already weak", dropped == [], f"{dropped}")

# if the model had called the partnership and the product launch "earnings", the sector rule is the safety net
ANSWERS_MISLABELLED = {**ANSWERS, "LTM": answer("earnings"), "HCLTECH": answer("earnings")}
watchlist, decisions, dropped = C.build_watchlist(ORDER, ANSWERS_MISLABELLED, NEWS, COMPANY, SECTORS, TODAY)
check("if the model mislabels two more IT stocks as earnings, all three are strong...", decisions["LTM"].strong and decisions["HCLTECH"].strong)
check("...but only TCS survives the sector rule, next to APOLLOHOSP", watchlist == ["TCS", "APOLLOHOSP"], f"{watchlist}")
check("and the two dropped ones are reported", [d[0] for d in dropped] == ["LTM", "HCLTECH"], f"{dropped}")
check("empty morning gives empty results", C.build_watchlist([], {}, {}, COMPANY, SECTORS, TODAY) == ([], {}, []))

print("\nALL CHECKS PASSED" if not failures else f"\n{len(failures)} CHECK(S) FAILED: {failures}")
sys.exit(1 if failures else 0)