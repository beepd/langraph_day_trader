"""The automatic blog job (blog_job.py) with a fake database and a fake model (no network). Run:  python test_blog_job.py"""
import sys
sys.path.insert(0, ".")
from datetime import date

# reuse the made-up day and week from the writer test (everything before its first numbered section)
_src = open("test_blog_writer.py", encoding="utf-8").read().split("# ---------------------------------------------------------------- 1. the number check")[0]
_ns = {}
exec(compile(_src, "test_blog_writer_setup", "exec"), _ns)
check, BAD, DAY, WEEK = _ns["check"], _ns["BAD"], _ns["DAY"], _ns["WEEK"]
import blog_job as j
import blog_writer as w


class Query:
    def __init__(self, store, name):
        self.store, self.name, self.filters, self.mode, self.payload = store, name, [], "select", None
    def select(self, *_):
        return self
    def eq(self, column, value):
        self.filters.append((column, value)); return self
    def limit(self, _):
        return self
    def insert(self, row):
        self.mode, self.payload = "insert", row; return self
    def update(self, row):
        self.mode, self.payload = "update", row; return self
    def execute(self):
        rows = self.store.setdefault(self.name, [])
        match = [r for r in rows if all(r.get(c) == v for c, v in self.filters)]
        if self.mode == "insert":
            if any(r["market_date"] == self.payload["market_date"] for r in rows):
                raise RuntimeError("duplicate market_date")
            rows.append(dict(self.payload, id=len(rows) + 1)); return type("R", (), {"data": []})()
        if self.mode == "update":
            for r in match:
                r.update(self.payload)
            return type("R", (), {"data": []})()
        return type("R", (), {"data": [dict(r) for r in match]})()


class FakeClient:
    def __init__(self):
        self.store = {}
    def table(self, name):
        return Query(self.store, name)


def good_daily():
    words = " ".join(["The bot bought on recorded reasons and two stocks ended with a small gross gain."] * 6)
    return {"title": "NSE paper trading: 9 October 2026", "meta_description": "A paper-trading diary of one NSE day with fake money.",
            "body_markdown": "I built a trading bot that executes simulated trades with fake money, and the day ended with a gross result of ₹100.00.\n\n## The trades\n\n" + words + "\n\n## One idea to test next\n\n" + words}


calls = []
def generate_of(draft):
    def generate(prompt):
        calls.append(prompt)
        if isinstance(draft, Exception):
            raise draft
        return draft
    return generate


print("1. Saving a draft")
client = FakeClient()
res = j.run_post("daily", date(2026, 10, 9), client, generate_of(good_daily()), "test:model", facts_loader=lambda: DAY)
row = client.store["blog_posts"][0]
check("a good draft is saved", res["outcome"] == "saved" and len(client.store["blog_posts"]) == 1)
check("it is saved unpublished, dated its trading day, with the checks recorded", row["published"] is False and row["market_date"] == "2026-10-09"
      and row["passed_checks"] is True and row["problems"] == [] and row["model_name"] == "test:model" and row["tries"] == 1)
check("the title, description, text and facts are stored", row["title"].startswith("NSE") and row["meta_description"] and "gross result" in row["body_markdown"]
      and row["facts_used"]["market_date"] == "2026-10-09" and "Simulation notice" in row["body_markdown"])

print("2. Running twice, forcing, and published posts")
calls.clear()
again = j.run_post("daily", date(2026, 10, 9), client, generate_of(good_daily()), "test:model", facts_loader=lambda: DAY)
check("a second run leaves the saved draft alone and does not call the model", again["outcome"] == "exists" and calls == [] and len(client.store["blog_posts"]) == 1)
client.store["blog_posts"][0]["title"] = "My edited title"
forced = j.run_post("daily", date(2026, 10, 9), client, generate_of(good_daily()), "test:model", force=True, facts_loader=lambda: DAY)
check("--force replaces an unpublished draft", forced["outcome"] == "replaced" and client.store["blog_posts"][0]["title"].startswith("NSE") and len(client.store["blog_posts"]) == 1)
client.store["blog_posts"][0]["published"] = True
calls.clear()
locked = j.run_post("daily", date(2026, 10, 9), client, generate_of(good_daily()), "test:model", force=True, facts_loader=lambda: DAY)
check("a published post is never replaced, even with --force", locked["outcome"] == "locked" and calls == [] and client.store["blog_posts"][0]["published"] is True)

print("3. Drafts that fail their checks, and days with nothing to write")
client = FakeClient()
bad = good_daily(); bad["body_markdown"] += "\n\nThe analyst ran in classic mode."
res = j.run_post("daily", date(2026, 10, 9), client, generate_of(bad), "test:model", facts_loader=lambda: DAY)
row = client.store["blog_posts"][0]
check("a draft that fails its checks is still saved, flagged, with the problems listed", res["outcome"] == "saved" and row["passed_checks"] is False
      and row["problems"] and row["published"] is False and row["tries"] == 2)
client = FakeClient()
holiday = dict(DAY, day_status="skipped")
res = j.run_post("daily", date(2026, 10, 9), client, generate_of(good_daily()), "test:model", facts_loader=lambda: holiday)
check("a skipped day writes nothing and is not an error", res["outcome"] == "nothing_to_write" and not client.store.get("blog_posts"))
unsettled = dict(DAY, day_status="not_settled_yet")
res = j.run_post("daily", date(2026, 10, 9), client, generate_of(good_daily()), "test:model", facts_loader=lambda: unsettled)
check("a day that is not settled yet asks for a retry", res["outcome"] == j.RETRY and not client.store.get("blog_posts"))
res = j.run_post("daily", date(2026, 10, 9), client, generate_of(RuntimeError("model down")), "test:model", facts_loader=lambda: DAY)
check("a model failure saves nothing and asks for a retry", res["outcome"] == j.FAILED and not client.store.get("blog_posts"))

print("4. The weekly post")
weekly_text = " ".join(["The week was small and the bot stayed inside its rules."] * 15)
weekly = {"title": "NSE trading bot diary: 5-9 October 2026", "meta_description": "One week of a trading bot on the NSE, simulated with fake money.",
          "body_markdown": "My trading bot executes simulated trades with fake money, and this week it ended with a gross result of ₹550.00 over 5 trades.\n\n## What the numbers say\n\n"
                           + weekly_text + "\n\n## What I will test next week\n\n" + weekly_text + "\n\n" + weekly_text}
client = FakeClient()
res = j.run_post("weekly", date(2026, 10, 9), client, generate_of(weekly), "test:model", facts_loader=lambda: WEEK)
row = client.store["blog_posts"][0]
check("a weekly post is saved under the Saturday", res["outcome"] == "saved" and row["market_date"] == "2026-10-10" and row["passed_checks"] is True)
check("the Saturday is worked out from any day of the week", j.post_date("weekly", date(2026, 10, 7)) == "2026-10-10" and j.post_date("weekly", date(2026, 10, 10)) == "2026-10-10"
      and j.post_date("daily", date(2026, 10, 7)) == "2026-10-07")
incomplete = dict(WEEK, complete=False, warnings=["2026-10-09: the run exists but the day is not settled yet"])
res = j.run_post("weekly", date(2026, 10, 9), FakeClient(), generate_of(weekly), "test:model", facts_loader=lambda: incomplete)
check("an unsettled week asks for a retry", res["outcome"] == j.RETRY)
broken = dict(WEEK, complete=False, warnings=["2026-10-08: the run failed"])
res = j.run_post("weekly", date(2026, 10, 9), FakeClient(), generate_of(weekly), "test:model", facts_loader=lambda: broken)
check("a week with a failed day writes nothing and says why", res["outcome"] == "nothing_to_write" and "incomplete" in res["detail"])

print("5. Which posts a normal run writes")
check("Monday to Thursday: daily only", all(j.kinds_for("auto", date(2026, 10, d)) == ["daily"] for d in (5, 6, 7, 8)))
check("Friday: daily and weekly", j.kinds_for("auto", date(2026, 10, 9)) == ["daily", "weekly"])
check("a kind can be asked for by name", j.kinds_for("weekly", date(2026, 10, 9)) == ["weekly"] and j.kinds_for("both", date(2026, 10, 9)) == ["daily", "weekly"])

print("6. The Telegram texts")
import messages as m
ok_text = m.blog_draft("daily", "2026-10-12", "A <b> title", True, [])
bad_text = m.blog_draft("weekly", "2026-10-17", "T", False, ["too short", "a & b"])
check("the messages are safe and say what to do", "&lt;b&gt;" in ok_text and "Passed" in ok_text and "NEEDS A CLOSE LOOK" in bad_text and "a &amp; b" in bad_text
      and "not published" in ok_text and "No weekly blog post" in m.blog_nothing("weekly", "2026-10-17", "the week is incomplete"))

print()
print("ALL CHECKS PASSED" if not BAD else "FAILED: " + "; ".join(BAD))
sys.exit(1 if BAD else 0)
