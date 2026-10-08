"""Tests the experiment script with stand-in internet (no network). Run:  python test_experiment_articles.py"""
import os, sys, tempfile
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
print("\nALL CHECKS PASSED" if not failures else f"\n{len(failures)} CHECK(S) FAILED: {failures}")
sys.exit(1 if failures else 0)
