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
import blogger_publish as _bp0
_bp0.configured = lambda: False          # sections 1-6 never touch Blogger
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
res = j.run_post("daily", date(2026, 10, 9), client, generate_of(good_daily()), "test:model", push=False, facts_loader=lambda: DAY)
row = client.store["blog_posts"][0]
check("a good draft is saved", res["outcome"] == "saved" and len(client.store["blog_posts"]) == 1)
check("it is saved unpublished, dated its trading day, with the checks recorded", row["published"] is False and row["market_date"] == "2026-10-09"
      and row["passed_checks"] is True and row["problems"] == [] and row["model_name"] == "test:model" and row["tries"] == 1)
check("the title, description, text and facts are stored", row["title"].startswith("NSE") and row["meta_description"] and "gross result" in row["body_markdown"]
      and row["facts_used"]["market_date"] == "2026-10-09" and "Simulation notice" in row["body_markdown"])

print("2. Running twice, forcing, and published posts")
calls.clear()
again = j.run_post("daily", date(2026, 10, 9), client, generate_of(good_daily()), "test:model", push=False, facts_loader=lambda: DAY)
check("a second run leaves the saved draft alone and does not call the model", again["outcome"] == "exists" and calls == [] and len(client.store["blog_posts"]) == 1)
client.store["blog_posts"][0]["title"] = "My edited title"
forced = j.run_post("daily", date(2026, 10, 9), client, generate_of(good_daily()), "test:model", force=True, push=False, facts_loader=lambda: DAY)
check("--force replaces an unpublished draft", forced["outcome"] == "replaced" and client.store["blog_posts"][0]["title"].startswith("NSE") and len(client.store["blog_posts"]) == 1)
client.store["blog_posts"][0]["published"] = True
calls.clear()
locked = j.run_post("daily", date(2026, 10, 9), client, generate_of(good_daily()), "test:model", force=True, push=False, facts_loader=lambda: DAY)
check("a published post is never replaced, even with --force", locked["outcome"] == "locked" and calls == [] and client.store["blog_posts"][0]["published"] is True)

print("3. Drafts that fail their checks, and days with nothing to write")
client = FakeClient()
bad = good_daily(); bad["body_markdown"] += "\n\nThe analyst ran in classic mode."
res = j.run_post("daily", date(2026, 10, 9), client, generate_of(bad), "test:model", push=False, facts_loader=lambda: DAY)
row = client.store["blog_posts"][0]
check("a draft that fails its checks is still saved, flagged, with the problems listed", res["outcome"] == "saved" and row["passed_checks"] is False
      and row["problems"] and row["published"] is False and row["tries"] == 2)
client = FakeClient()
holiday = dict(DAY, day_status="skipped")
res = j.run_post("daily", date(2026, 10, 9), client, generate_of(good_daily()), "test:model", push=False, facts_loader=lambda: holiday)
check("a skipped day writes nothing and is not an error", res["outcome"] == "nothing_to_write" and not client.store.get("blog_posts"))
unsettled = dict(DAY, day_status="not_settled_yet")
res = j.run_post("daily", date(2026, 10, 9), client, generate_of(good_daily()), "test:model", push=False, facts_loader=lambda: unsettled)
check("a day that is not settled yet asks for a retry", res["outcome"] == j.RETRY and not client.store.get("blog_posts"))
res = j.run_post("daily", date(2026, 10, 9), client, generate_of(RuntimeError("model down")), "test:model", push=False, facts_loader=lambda: DAY)
check("a model failure saves nothing and asks for a retry", res["outcome"] == j.FAILED and not client.store.get("blog_posts"))

print("4. The weekly post")
weekly_text = " ".join(["The week was small and the bot stayed inside its rules."] * 15)
weekly = {"title": "NSE trading bot diary: 5-9 October 2026", "meta_description": "One week of a trading bot on the NSE, simulated with fake money.",
          "body_markdown": "My trading bot executes simulated trades with fake money, and this week it ended with a gross result of ₹550.00 over 5 trades.\n\n## What the numbers say\n\n"
                           + weekly_text + "\n\n## What I will test next week\n\n" + weekly_text + "\n\n" + weekly_text}
client = FakeClient()
res = j.run_post("weekly", date(2026, 10, 9), client, generate_of(weekly), "test:model", push=False, facts_loader=lambda: WEEK)
row = client.store["blog_posts"][0]
check("a weekly post is saved under the Saturday", res["outcome"] == "saved" and row["market_date"] == "2026-10-10" and row["passed_checks"] is True)
check("the Saturday is worked out from any day of the week", j.post_date("weekly", date(2026, 10, 7)) == "2026-10-10" and j.post_date("weekly", date(2026, 10, 10)) == "2026-10-10"
      and j.post_date("daily", date(2026, 10, 7)) == "2026-10-07")
incomplete = dict(WEEK, complete=False, warnings=["2026-10-09: the run exists but the day is not settled yet"])
res = j.run_post("weekly", date(2026, 10, 9), FakeClient(), generate_of(weekly), "test:model", push=False, facts_loader=lambda: incomplete)
check("an unsettled week asks for a retry", res["outcome"] == j.RETRY)
broken = dict(WEEK, complete=False, warnings=["2026-10-08: the run failed"])
res = j.run_post("weekly", date(2026, 10, 9), FakeClient(), generate_of(weekly), "test:model", push=False, facts_loader=lambda: broken)
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

print("7. Sending drafts to Blogger (fake Blogger, nothing leaves this computer)")
import os
import blogger_publish as bp
os.environ["BLOGGER_BLOG_ID"] = "B123"
api_calls, live_ids = [], set()
def fake_api(method, path, body=None, params=None):
    api_calls.append((method, path, body, params))
    if method == "POST":
        return {"id": "P1", "url": "https://x.blogspot.com/draft"}
    if method == "GET":
        pid = path.rsplit("/", 1)[-1]
        return {"id": pid, "status": "LIVE" if pid in live_ids else "DRAFT", "url": "https://x.blogspot.com/live", "published": "2026-10-12T11:00:00+05:30"}
    return {}
bp._api = fake_api
bp.configured = lambda: True

check("a weekly post is labelled Weekly, any other Daily", bp.labels_for("2026-10-10") == ["Weekly"] and bp.labels_for("2026-10-09") == ["Daily"])
client = FakeClient()
res = j.run_post("daily", date(2026, 10, 9), client, generate_of(good_daily()), "test:model", facts_loader=lambda: DAY)
row = client.store["blog_posts"][0]
post_call = [c for c in api_calls if c[0] == "POST"][0]
check("a saved draft is created on Blogger as a DRAFT with the HTML body and a label", res["blogger"]["action"] == "created" and post_call[3] == {"isDraft": "true"}
      and post_call[2]["labels"] == ["Daily"] and "<table" in post_call[2]["content"] and post_call[2]["title"] == row["title"])
check("Blogger's id and status are remembered, and the post stays unpublished", row["blogger_post_id"] == "P1" and row["blogger_status"] == "DRAFT" and row["published"] is False
      and row["sent_to_blogger_at"] and "B123/P1" in res["blogger"]["edit_url"])
api_calls.clear()
again = j.run_post("daily", date(2026, 10, 9), client, generate_of(good_daily()), "test:model", facts_loader=lambda: DAY)
check("a second run creates no second Blogger draft and makes no Blogger call", again["outcome"] == "exists" and again["blogger"]["action"] == "already_sent" and api_calls == [])

client.store["blog_posts"][0]["title"] = "Edited in the database"
res = j.run_post("daily", date(2026, 10, 9), client, generate_of(good_daily()), "test:model", force=True, facts_loader=lambda: DAY)
patch = [c for c in api_calls if c[0] == "PATCH"]
check("--force refreshes the existing Blogger draft (PATCH) instead of creating another", res["blogger"]["action"] == "updated" and len(patch) == 1
      and patch[0][1].endswith("/posts/P1") and not [c for c in api_calls if c[0] == "POST"])
live_ids.add("P1"); api_calls.clear()
res = j.run_post("daily", date(2026, 10, 9), client, generate_of(good_daily()), "test:model", force=True, facts_loader=lambda: DAY)
row = client.store["blog_posts"][0]
check("a post that is already LIVE on Blogger is never overwritten, and is marked published here", res["blogger"]["action"] == "live"
      and not [c for c in api_calls if c[0] in ("PATCH", "POST")] and row["published"] is True and row["blogger_status"] == "LIVE")

print("8. Checking what you published, and Blogger failures")
client = FakeClient()
for n, (d, pid) in enumerate([("2026-10-06", "A"), ("2026-10-07", "B"), ("2026-10-08", None)], start=1):
    client.store.setdefault("blog_posts", []).append({"id": n, "market_date": d, "published": False, "blogger_post_id": pid, "published_at": None})
live_ids.clear(); live_ids.add("A")
check("sync marks only posts that are LIVE on Blogger as published", bp.sync_status(client) == 1 and client.store["blog_posts"][0]["published"] is True
      and client.store["blog_posts"][1]["published"] is False and client.store["blog_posts"][2]["published"] is False)
def broken_api(*a, **k):
    raise bp.BloggerError("HTTP 403 forbidden")
bp._api = broken_api
client = FakeClient()
res = j.run_post("daily", date(2026, 10, 9), client, generate_of(good_daily()), "test:model", facts_loader=lambda: DAY)
check("a Blogger failure keeps the saved draft and is reported (so the scheduler retries)", res["outcome"] == "saved" and client.store["blog_posts"][0]["title"]
      and res["blogger"]["action"] == "failed" and "403" in res["blogger"]["detail"])
bp._api = fake_api; api_calls.clear()
res = j.run_post("daily", date(2026, 10, 9), client, generate_of(good_daily()), "test:model", facts_loader=lambda: DAY)
check("the retry creates the missing Blogger draft without rewriting the post", res["outcome"] == "exists" and res["blogger"]["action"] == "created"
      and client.store["blog_posts"][0]["blogger_post_id"] == "P1")
note = m.blog_draft("daily", "2026-10-12", "T", True, [], False, "https://www.blogger.com/blog/post/edit/B123/P1", "A <meta> & text")
check("the Telegram note has the Blogger link and the search description to paste", "blog/post/edit/B123/P1" in note and "&lt;meta&gt; &amp; text" in note and "Search description" in note
      and "Could not create" in m.blog_draft("daily", "d", "T", True, [], False, None, None, "HTTP 403"))

print()
print("ALL CHECKS PASSED" if not BAD else "FAILED: " + "; ".join(BAD))
sys.exit(1 if BAD else 0)
