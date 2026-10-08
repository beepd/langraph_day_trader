"""Tests the experiment script with stand-in internet (no network). Run:  python test_experiment_articles.py"""
import datetime, os, sys, tempfile
sys.path.insert(0, ".")
import experiment_articles as E

failures = []
def check(label, ok, detail=""):
    print(f"   {'ok ' if ok else 'BAD'} {label} {detail}")
    if not ok: failures.append(label)

LONG = "word " * 400            # 2,000 characters: readable
print("== 1. the funnel counts, with every kind of failure ==")
# 4 stocks, google gives 3 headlines each = 12; bing gives 2 for A, nothing for the rest
google_links = {s: [{"title": f"{s} news {i}", "link": f"G-{s}-{i}"} for i in range(3)] for s in "ABCD"}
bing_links = {"A": [{"title": "A bing 0", "link": "http://www.bing.com/news/apiclick.aspx?ref=x&url=https%3a%2f%2fsite-a.com%2fstory0&c=1"},
                    {"title": "A bing 1", "link": "https://direct-no-wrapper.com/story1"}]}
def resolve_google(link):
    if link.endswith("-2"): return None, "decode failed: signature missing"
    return f"https://{link.lower()}.example/story", ""
fetch_table = {   # url -> (status, body, content-type, error)
    "https://g-a-0.example/story": (200, b"<html>A0</html>", "text/html; charset=utf-8", ""),
    "https://g-a-1.example/story": (403, b"", "", "HTTP 403"),
    "https://g-b-0.example/story": (200, b"<html>short</html>", "text/html", ""),            # paywall: short text
    "https://g-b-1.example/story": (None, b"", "", "TimeoutError"),
    "https://g-c-0.example/story": (200, b"%PDF", "application/pdf", ""),
    "https://g-c-1.example/story": (200, b"<html>C1</html>", "text/html", ""),
    "https://g-d-0.example/story": (200, b"<html>D0</html>", "text/html", ""),
    "https://g-d-1.example/story": (200, b"<html>D1</html>", "text/html", ""),
    "https://site-a.com/story0": (200, b"<html>BING A0</html>", "text/html", ""),
    "https://direct-no-wrapper.com/story1": (200, b"<html>BING A1</html>", "text/html", ""),
}
texts = {b"<html>A0</html>": LONG, b"<html>short</html>": "too short", b"<html>C1</html>": LONG * 2, b"<html>D0</html>": LONG,
         b"<html>D1</html>": "", b"<html>BING A0</html>": LONG, b"<html>BING A1</html>": LONG * 3}
robots_rules = {"https://g-d-1.example": (200, b"User-agent: *\nDisallow: /", "", ""), "https://g-c-1.example": (404, b"", "", "HTTP 404"),
                "https://g-b-1.example": (403, b"", "", "HTTP 403")}
sleeps = []
robots = E.Robots(fetch=lambda url: robots_rules.get(url.replace("/robots.txt", ""), (404, b"", "", "HTTP 404")))
deps = {"items": {"google": lambda company, n: google_links[company.split()[0]], "bing": lambda company, n: bing_links.get(company.split()[0], [])},
        "resolve": {"google": resolve_google, "bing": E.bing_real_url}, "robots": robots,
        "fetch": lambda url: fetch_table[url], "extract": lambda body: texts[body], "sleep": sleeps.append, "pause": 0.5}
names = {s: f"{s} Ltd." for s in "ABCD"}
rows = E.run_experiment(list("ABCD"), names, ["google", "bing"], 3, deps)
g = [r for r in rows if r["source"] == "google" and not r.get("empty")]
b = [r for r in rows if r["source"] == "bing"]
check("google: 12 headlines", len(g) == 12)
check("google: 4 had no decodable address (one per stock)", sum(not r["real_url"] for r in g) == 4, f"{sum(r['real_url'] for r in g)} found")
check("google: pages opened = A0, B0, C1, D0 (not A1 403, B1 robots unreadable, C0 pdf, D1 robots no)",
      sorted(r["title"] for r in g if r["fetched"]) == ["A news 0", "B news 0", "C news 1", "D news 0"], f"{sorted(r['title'] for r in g if r['fetched'])}")
reasons = {r["title"]: r["reason"] for r in g if r["reason"]}
check("reason: HTTP 403", reasons["A news 1"] == "HTTP 403", reasons["A news 1"])
check("reason: robots.txt unreadable is skipped politely", reasons["B news 1"].startswith("robots.txt not readable"), reasons["B news 1"])
check("reason: pdf is not a web page", reasons["C news 0"].startswith("not a web page"), reasons["C news 0"])
check("reason: robots.txt says no", reasons["D news 1"] == "robots.txt says no", reasons["D news 1"])
check("reason: paywall-short text", reasons["B news 0"].startswith("text too short"), reasons["B news 0"])
check("readable: A0, C1, D0", sorted(r["title"] for r in g if r["readable"]) == ["A news 0", "C news 1", "D news 0"])
check("bing: real address taken from the url= part, and a plain link left alone", [r["domain"] for r in b if r["real_url"]] == ["site-a.com", "direct-no-wrapper.com"])
check("bing: both readable", sum(r["readable"] for r in b) == 2)
check("bing: stocks B, C, D recorded as having no headlines", sorted(r["symbol"] for r in rows if r["source"] == "bing" and r.get("empty")) == ["B", "C", "D"])
check("a pause of 0.5 s before each of the 8 page requests that were actually made (none for robots-blocked pages)", sleeps == [0.5] * 8, f"{len(sleeps)} pauses")

print("== 2. the summary prints and the CSV is written, without article text ==")
import io, contextlib
buf = io.StringIO()
with contextlib.redirect_stdout(buf): E.summarize(rows, list("ABCD"), ["google", "bing"], show_samples=True)
out = buf.getvalue()
check("both sources reported", "SOURCE: GOOGLE" in out and "SOURCE: BING" in out)
check("coverage line for google: 3 of 4 stocks", "stocks with at least one readable:   3 of 4" in out, "")
check("a sample is shown when asked", "sample [" in out)
with tempfile.TemporaryDirectory() as d:
    path = E.save_csv(rows, os.path.join(d, "r.csv")); text = open(path, encoding="utf-8").read()
check("CSV has no article text", "word word" not in text and "source,symbol,title" in text)

print("== 3. the broken-dependency workaround: the decoder library loads, and reads a Google page's signature ==")
for name in [n for n in sys.modules if n.startswith("googlenewsdecoder") or n == "selectolax.parser"]: del sys.modules[name]
try:
    decoder = E.load_decoder()
    import googlenewsdecoder._parse as P
    page = '<html><c-wiz><div jscontroller="x" data-n-a-sg="SIG123" data-n-a-ts="1700000000"></div></c-wiz></html>'
    check("decoder function loaded", callable(decoder))
    check("page signature read", P.parse_signature(page) == ("SIG123", "1700000000"), f"{P.parse_signature(page)}")
    plain = '<html><body><script>"data-n-a-sg":"SIG999" ... </script></body></html>'
except Exception as e:
    check("decoder loads", False, f"{type(e).__name__}: {e}")
print("== 4. real helper behaviour ==")
check("company name cleaning", E.clean_name("Power Finance Corporation Ltd.") == "Power Finance Corporation" and E.clean_name("Bajaj Finance Limited") == "Bajaj Finance")
check("domain extraction", E.domain_of("https://www.economictimes.indiatimes.com/a/b") == "economictimes.indiatimes.com")
print("== 5. check 1: does the article body name the company? (whole words only) ==")
count = E.count_company_mentions
check("full name counts once, not twice (longest match wins)", count("PFC", "Power Finance Corporation Ltd.", "Power Finance Corporation raised funds.") == 1)
check("short name (first two words) counts", count("PFC", "Power Finance Corporation Ltd.", "Power Finance reported a profit.") == 1)
check("symbol counts", count("PFC", "Power Finance Corporation Ltd.", "Shares of PFC rose. PFC also paid a dividend.") == 2)
check("upper/lower case does not matter", count("TCS", "Tata Consultancy Services Ltd.", "tata consultancy services and TCS") == 2)
check("possessive form counts", count("RELIANCE", "Reliance Industries Ltd.", "Reliance's retail arm grew") == 1)
check("ITC is NOT found inside 'switch' or 'pitch'", count("ITC", "ITC Ltd.", "The switch to a new pitch failed.") == 0)
check("ABB is NOT found inside 'abbreviation'", count("ABB", "ABB India Ltd.", "An abbreviation was used.") == 0)
check("symbol with & works", count("M&M", "Mahindra & Mahindra Ltd.", "M&M launched a new SUV") == 1)
check("one-word company name works", count("VEDL", "Vedanta Ltd.", "Vedanta said output rose") == 1)
check("article about something else gives zero", count("PFC", "Power Finance Corporation Ltd.", "The monsoon arrived early this year.") == 0)
check("empty text gives zero", count("PFC", "Power Finance Corporation Ltd.", "") == 0)

print("== 6. check 1 inside the whole experiment ==")
filler = "The market moved sideways today as traders waited for fresh cues. " * 12      # about 800 characters
on_topic = b"<html>ON</html>"; off_topic = b"<html>OFF</html>"
deps6 = {"items": {"google": lambda company, n: [{"title": "on", "link": "L1"}, {"title": "off", "link": "L2"}], "bing": lambda c, n: []},
         "resolve": {"google": lambda link: (f"https://site-{link}.example/s", ""), "bing": E.bing_real_url},
         "robots": E.Robots(fetch=lambda url: (404, b"", "", "HTTP 404")),
         "fetch": lambda url: (200, on_topic if "L1" in url else off_topic, "text/html", ""),
         "extract": lambda body: ("Power Finance Corporation reported strong results. " + filler) if body == on_topic else ("Sector wrap. " + filler),
         "sleep": lambda s: None, "pause": 0}
rows6 = E.run_experiment(["PFC"], {"PFC": "Power Finance Corporation Ltd."}, ["google"], 2, deps6)
mentions = {r["title"]: r["mentions"] for r in rows6}
check("on-topic article counted 1 mention, off-topic 0", mentions == {"on": 1, "off": 0}, f"{mentions}")
buf6 = io.StringIO()
with contextlib.redirect_stdout(buf6): E.summarize(rows6, ["PFC"], ["google"])
check("summary shows readable AND names the company: 1 of 2", "readable AND names the company:      1 (50%)" in buf6.getvalue(), "")
with tempfile.TemporaryDirectory() as d:
    header = open(E.save_csv(rows6, os.path.join(d, "r6.csv")), encoding="utf-8").readline()
check("CSV has a mentions column", ",mentions," in header, header.strip())

print("== 7. check 2: how old is the article? ==")
D = datetime.date
today = D(2026, 10, 8)
check("2 days old", E.age_in_days(D(2026, 10, 6), today) == 2)
check("published today is 0", E.age_in_days(today, today) == 0)
check("30 days old", E.age_in_days(D(2026, 9, 8), today) == 30)
check("tomorrow (time-zone slack) is treated as 0", E.age_in_days(D(2026, 10, 9), today) == 0)
check("2 days in the future is not trusted (None)", E.age_in_days(D(2026, 10, 10), today) is None)
check("no date gives None", E.age_in_days(None, today) is None)
page_meta = b'<html><head><meta property="article:published_time" content="2026-10-07T03:37:00+05:30"><title>x</title></head><body><p>Hello</p></body></html>'
page_json = b'<html><head><script type="application/ld+json">{"@type":"NewsArticle","datePublished":"2026-10-06T10:00:00Z"}</script></head><body><p>hi</p></body></html>'
check("date read from a meta tag", E.article_date(page_meta) == D(2026, 10, 7), f"{E.article_date(page_meta)}")
check("date read from JSON-LD", E.article_date(page_json) == D(2026, 10, 6), f"{E.article_date(page_json)}")
check("page without a date gives None", E.article_date(b"<html><body><p>no date here</p></body></html>") is None)
check("garbage bytes give None, no crash", E.article_date(b"\xff\xfe\x00 not html") is None)
check("empty page gives None", E.article_date(b"") is None)

print("== 8. check 2 inside the whole experiment ==")
bodies = {"L1": b"<fresh-named>", "L2": b"<stale-named>", "L3": b"<nodate-named>", "L4": b"<fresh-offtopic>"}
dates8 = {b"<fresh-named>": D(2026, 10, 7), b"<stale-named>": D(2026, 9, 28), b"<nodate-named>": None, b"<fresh-offtopic>": D(2026, 10, 6)}
named_text = "Power Finance Corporation reported strong results. " + filler
deps8 = {"items": {"google": lambda company, n: [{"title": k, "link": k} for k in bodies], "bing": lambda c, n: []},
         "resolve": {"google": lambda link: (f"https://site-{link}.example/s", ""), "bing": E.bing_real_url},
         "robots": E.Robots(fetch=lambda url: (404, b"", "", "HTTP 404")),
         "fetch": lambda url: (200, bodies[url.split("site-")[1].split(".")[0]], "text/html", ""),
         "extract": lambda body: ("Sector wrap. " + filler) if body == b"<fresh-offtopic>" else named_text,
         "date_of": lambda body: dates8[body], "today": lambda: today, "sleep": lambda s: None, "pause": 0}
rows8 = E.run_experiment(["PFC"], {"PFC": "Power Finance Corporation Ltd."}, ["google"], 4, deps8)
ages = {r["title"]: r["age_days"] for r in rows8}
check("ages: 1, 10, None, 2 days", ages == {"L1": 1, "L2": 10, "L3": None, "L4": 2}, f"{ages}")
check("fresh = L1 and L4", sorted(r["title"] for r in rows8 if E.is_fresh(r)) == ["L1", "L4"])
check("usable = only L1 (fresh AND names the company)", [r["title"] for r in rows8 if E.is_usable(r)] == ["L1"])
buf8 = io.StringIO()
with contextlib.redirect_stdout(buf8): E.summarize(rows8, ["PFC"], ["google"])
out8 = buf8.getvalue()
check("summary: fresh 2 (50%)", "readable AND fresh (<= 3 days old):      2 (50%)" in out8)
check("summary: 1 page with no readable date", "no readable date on the page: 1)" in out8)
check("summary: usable 1 (25%)", "USABLE = readable + names it + fresh: 1 (25%)" in out8)
with tempfile.TemporaryDirectory() as d:
    lines8 = open(E.save_csv(rows8, os.path.join(d, "r8.csv")), encoding="utf-8").read().splitlines()
check("CSV has an age_days column", ",age_days," in lines8[0], lines8[0])

print("== 9. check 3a: which websites give usable articles? ==")
def make_row(domain, readable=True, fresh=True, named=True, real_url=True, symbol="PFC"):
    return {"source": "google", "symbol": symbol, "title": "t", "domain": domain, "real_url": real_url, "fetched": readable,
            "readable": readable, "chars": 900 if readable else 0, "mentions": 1 if named else 0,
            "age_days": (1 if fresh else 9) if readable else None, "reason": "" if readable else "text too short", "seconds": 1.0, "text": "x" * 900 if readable else ""}
rows9 = [make_row("a.com"), make_row("a.com", fresh=False), make_row("a.com", readable=False),     # a.com: 3 tried, 2 readable, 1 usable
         make_row("b.com"),                                                                          # b.com: 1 tried, 1 readable, 1 usable
         make_row("c.com", readable=False), make_row("c.com", readable=False),                      # c.com: 2 tried, none readable
         make_row("d.com", named=False),                                                             # d.com: readable and fresh but off topic: not usable
         make_row("?", real_url=False)]                                                              # no real address: left out of the table
stats = E.site_stats(rows9)
check("most-tried first, ties alphabetical", [row[0] for row in stats] == ["a.com", "c.com", "b.com", "d.com"], f"{[row[0] for row in stats]}")
check("a.com: 3 tried, 2 readable, 1 usable", stats[0] == ("a.com", 3, 2, 1), f"{stats[0]}")
check("c.com: 2 tried, 0 readable, 0 usable", stats[1] == ("c.com", 2, 0, 0), f"{stats[1]}")
check("d.com: readable and fresh but does not name the company, so not usable", stats[3] == ("d.com", 1, 1, 0), f"{stats[3]}")
check("rows without a real address are left out", all(row[0] != "?" for row in stats))
buf9 = io.StringIO()
with contextlib.redirect_stdout(buf9): E.summarize(rows9, ["PFC"], ["google"])
short = buf9.getvalue()
check("short line shows usable / tried", "by website (usable / tried):         a.com 1/3, c.com 0/2, b.com 1/1, d.com 0/1" in short, "")
check("full table is not printed unless asked", "ALL WEBSITES" not in short)
buf9b = io.StringIO()
with contextlib.redirect_stdout(buf9b): E.summarize(rows9, ["PFC"], ["google"], show_sites=True)
full = buf9b.getvalue()
check("full table printed when asked, with a.com's numbers", "ALL WEBSITES" in full and any(l.split() == ["a.com", "3", "2", "1"] for l in full.splitlines()))
many = [make_row(f"site{i}.com") for i in range(12)]
buf9c = io.StringIO()
with contextlib.redirect_stdout(buf9c): E.summarize(many, ["PFC"], ["google"])
line = [l for l in buf9c.getvalue().splitlines() if "by website" in l][0]
check("short line is capped at 8 websites", line.count(".com") == 8, line)

print("\nALL CHECKS PASSED" if not failures else f"\n{len(failures)} CHECK(S) FAILED: {failures}")
sys.exit(1 if failures else 0)
