"""
EXPERIMENT E2: how often can we get the real article text behind a news headline?

Nothing is saved to any database and no keys are needed. It looks up headlines for a few stocks from two sources
(Google News and Bing News), opens the article behind each headline, tries to extract the readable text, and prints
ONE summary table. It is polite: an honest User-Agent, robots.txt is checked, one request per page, a pause between
requests, and no attempt to get past paywalls or blocks. If a site says no, that is an answer too.

    python experiment_articles.py                    10 sample stocks, 3 headlines each, both sources
    python experiment_articles.py PFC VEDL TRENT     your own stocks (symbols from nifty100.csv)
    python experiment_articles.py --samples          also print the first words of a few readable articles

Needs:  pip install trafilatura googlenewsdecoder
Run it on your laptop AND on the VM: results can differ, and the VM is where the real run happens.
"""
import argparse
import csv
import statistics
import sys
import time
import types
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

USER_AGENT = "day-trader-research/0.1 (personal learning project; one request per page)"
DEFAULT_SYMBOLS = ["PFC", "BAJFINANCE", "VEDL", "TRENT", "KOTAKBANK", "GODREJCP", "ABB", "ADANIGREEN", "HINDUNILVR", "RELIANCE"]
MIN_READABLE_CHARS = 500          # less than this and we do not call it an article (a paywall or a blocked page)
PAGE_TIMEOUT = 15
MAX_PAGE_BYTES = 2_000_000


# ------------------------------------------------------------------------------ small helpers
def clean_name(company: str) -> str:
    return company.replace(" Ltd.", "").replace(" Limited", "").strip()


def load_names(path: str = "nifty100.csv") -> dict:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return {row["Symbol"].strip(): row["Company Name"].strip() for row in csv.DictReader(f)}


def domain_of(url: str) -> str:
    return urllib.parse.urlparse(url).netloc.lower().removeprefix("www.") or "?"


def http_get(url: str, timeout: float = PAGE_TIMEOUT):
    """Returns (status, body_bytes, content_type, error_text). Never raises."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xml;q=0.9,*/*;q=0.5"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(MAX_PAGE_BYTES), response.headers.get("Content-Type", ""), ""
    except urllib.error.HTTPError as error:
        return error.code, b"", "", f"HTTP {error.code}"
    except Exception as error:
        return None, b"", "", type(error).__name__


def rss_items(url: str, per_stock: int) -> list:
    status, body, _, error = http_get(url)
    if status != 200:
        return []
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []
    items = []
    for item in root.iter("item"):
        title, link = (item.findtext("title") or "").strip(), (item.findtext("link") or "").strip()
        if title and link:
            items.append({"title": title, "link": link})
    return items[:per_stock]


# ------------------------------------------------------------------------------ the two sources
def google_items(company: str, per_stock: int) -> list:
    query = urllib.parse.quote_plus(f'"{clean_name(company)}" when:3d')
    return rss_items(f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en", per_stock)


def bing_items(company: str, per_stock: int) -> list:
    query = urllib.parse.quote_plus(f'"{clean_name(company)}"')
    return rss_items(f"https://www.bing.com/news/search?q={query}&format=rss&setmkt=en-IN", per_stock)


def bing_real_url(link: str):
    """Bing's links usually carry the real address in a 'url=' part."""
    wrapped = urllib.parse.parse_qs(urllib.parse.urlparse(link).query).get("url")
    return (wrapped[0], "") if wrapped else (link, "")


def install_selectolax_shim():
    """The decoder library imports a parser that newer 'selectolax' versions removed. This stand-in lets it load.
    The library has a plain text-search fallback for the one place it uses the parser."""
    shim = types.ModuleType("selectolax.parser")
    try:
        from selectolax.lexbor import LexborHTMLParser as parser
    except Exception:
        class parser:
            def __init__(self, html): pass
            def css_first(self, selector): return None
    shim.HTMLParser = parser
    sys.modules["selectolax.parser"] = shim


def load_decoder():
    try:
        from googlenewsdecoder import gnewsdecoder
    except ImportError:
        for name in [n for n in sys.modules if n.startswith("googlenewsdecoder")]:
            del sys.modules[name]
        install_selectolax_shim()
        from googlenewsdecoder import gnewsdecoder
    return gnewsdecoder


def google_real_url(link: str):
    """Returns (url or None, reason)."""
    try:
        result = load_decoder()(link, interval=1)
    except Exception as error:
        return None, f"decoder crashed: {type(error).__name__}"
    if result.get("success"):
        return result["decoded_url"], ""
    return None, "decode failed: " + str(result.get("message", ""))[:60]


# ------------------------------------------------------------------------------ politeness and reading
class Robots:
    """Checks robots.txt once per website. If it cannot be read properly, we skip that site (polite default)."""
    def __init__(self, fetch=http_get):
        self.fetch, self.cache = fetch, {}

    def allowed(self, url: str):
        parts = urllib.parse.urlparse(url)
        site = f"{parts.scheme}://{parts.netloc}"
        if site not in self.cache:
            status, body, _, error = self.fetch(site + "/robots.txt")
            if status == 200:
                parser = urllib.robotparser.RobotFileParser()
                parser.parse(body.decode("utf-8", "replace").splitlines())
                self.cache[site] = (parser, "")
            elif status in (404, 410):
                self.cache[site] = (None, "")
            else:
                self.cache[site] = (False, f"robots.txt not readable ({error or status})")
        parser, why = self.cache[site]
        if parser is False:
            return False, why
        if parser is not None and not parser.can_fetch(USER_AGENT, url):
            return False, "robots.txt says no"
        return True, ""


def extract_text(body: bytes) -> str:
    import trafilatura
    html = body.decode("utf-8", "replace")
    return trafilatura.extract(html, include_comments=False, include_tables=False) or ""


# ------------------------------------------------------------------------------ the experiment
def run_one(source, item, symbol, deps):
    started = time.time()
    row = {"source": source, "symbol": symbol, "title": item["title"][:100], "domain": "?", "real_url": False,
           "fetched": False, "readable": False, "chars": 0, "reason": "", "seconds": 0.0, "text": ""}
    url, reason = deps["resolve"][source](item["link"])
    if not url:
        row.update(reason=reason or "no real address", seconds=round(time.time() - started, 1)); return row
    row.update(real_url=True, domain=domain_of(url))
    allowed, why = deps["robots"].allowed(url)
    if not allowed:
        row.update(reason=why, seconds=round(time.time() - started, 1)); return row
    deps["sleep"](deps["pause"])
    status, body, ctype, error = deps["fetch"](url)
    if status != 200:
        row.update(reason=error or f"HTTP {status}", seconds=round(time.time() - started, 1)); return row
    if "html" not in ctype.lower() and ctype:
        row.update(reason=f"not a web page ({ctype.split(';')[0]})", seconds=round(time.time() - started, 1)); return row
    row["fetched"] = True
    text = deps["extract"](body)
    row.update(chars=len(text), seconds=round(time.time() - started, 1))
    if len(text) >= MIN_READABLE_CHARS:
        row.update(readable=True, text=text)
    else:
        row["reason"] = f"text too short ({len(text)} characters: paywall or blocked?)"
    return row


def run_experiment(symbols, names, sources, per_stock, deps):
    rows = []
    for symbol in symbols:
        company = names.get(symbol, symbol)
        for source in sources:
            items = deps["items"][source](company, per_stock)
            if not items:
                rows.append({"source": source, "symbol": symbol, "title": "", "domain": "?", "real_url": False, "fetched": False,
                             "readable": False, "chars": 0, "reason": "no headlines found", "seconds": 0.0, "text": "", "empty": True})
            for item in items:
                rows.append(run_one(source, item, symbol, deps))
    return rows


def summarize(rows, symbols, sources, show_samples=False):
    for source in sources:
        mine = [r for r in rows if r["source"] == source and not r.get("empty")]
        total = len(mine)
        pct = lambda n: f"{n} ({100 * n / total:.0f}%)" if total else "0"
        real, fetched, readable = (sum(r[k] for r in mine) for k in ("real_url", "fetched", "readable"))
        covered = len({r["symbol"] for r in mine if r["readable"]})
        no_headlines = [r["symbol"] for r in rows if r["source"] == source and r.get("empty")]
        print(f"\n=== SOURCE: {source.upper()} " + "=" * 50)
        print(f"  headlines found:                     {total}" + (f"   (no headlines at all for: {', '.join(no_headlines)})" if no_headlines else ""))
        print(f"  real article address found:          {pct(real)}")
        print(f"  page opened (allowed, HTTP 200):     {pct(fetched)}")
        print(f"  readable article text (>= {MIN_READABLE_CHARS}):    {pct(readable)}")
        print(f"  stocks with at least one readable:   {covered} of {len(symbols)}")
        lengths = [r["chars"] for r in mine if r["readable"]]
        if lengths:
            print(f"  typical readable length:             {int(statistics.median(lengths)):,} characters (median)")
        reasons = Counter(r["reason"].split(" (")[0] for r in mine if r["reason"])
        if reasons:
            print("  why the rest failed:                 " + "; ".join(f"{why} x{n}" for why, n in reasons.most_common(5)))
        by_site = defaultdict(lambda: [0, 0])
        for r in mine:
            if r["real_url"]:
                by_site[r["domain"]][0] += 1
                by_site[r["domain"]][1] += r["readable"]
        if by_site:
            print("  by website (readable / tried):       " + ", ".join(f"{d} {g}/{t}" for d, (t, g) in sorted(by_site.items(), key=lambda kv: -kv[1][0])[:8]))
        if show_samples:
            for r in [r for r in mine if r["readable"]][:3]:
                print(f"  sample [{r['domain']}]: {' '.join(r['text'].split())[:160]}...")
        print(f"  time spent:                          {sum(r['seconds'] for r in mine):.0f} seconds")


def save_csv(rows, path="experiment_articles_results.csv"):
    fields = ["source", "symbol", "title", "domain", "real_url", "fetched", "readable", "chars", "reason", "seconds"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("symbols", nargs="*", help="stock symbols from nifty100.csv (default: 10 samples)")
    parser.add_argument("--sources", nargs="+", default=["google", "bing"], choices=["google", "bing"])
    parser.add_argument("--per-stock", type=int, default=3, help="headlines per stock and source")
    parser.add_argument("--pause", type=float, default=1.5, help="seconds to wait before each page request")
    parser.add_argument("--samples", action="store_true", help="print the first words of a few readable articles")
    args = parser.parse_args()
    symbols = [s.upper() for s in args.symbols] or DEFAULT_SYMBOLS
    names = load_names()
    deps = {
        "items": {"google": google_items, "bing": bing_items},
        "resolve": {"google": google_real_url, "bing": bing_real_url},
        "robots": Robots(), "fetch": http_get, "extract": extract_text, "sleep": time.sleep, "pause": args.pause,
    }
    pages = len(symbols) * len(args.sources) * args.per_stock
    print(f"Testing {len(symbols)} stocks x {len(args.sources)} source(s) x up to {args.per_stock} headlines = up to {pages} pages "
          f"(about {int(pages * (args.pause + 2) / 60) + 1} minutes). Press Ctrl+C to stop.")
    rows = run_experiment(symbols, names, args.sources, args.per_stock, deps)
    summarize(rows, symbols, args.sources, args.samples)
    print(f"\nDetails (titles, websites, reasons; no article text) saved to {save_csv(rows)}")


if __name__ == "__main__":
    main()
