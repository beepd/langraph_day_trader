"""
EXPERIMENT E2: how often can we get the real article text behind a news headline?

Nothing is saved to any database and no keys are needed. It looks up headlines for a few stocks from two sources
(Google News and Bing News), opens the article behind each headline, tries to extract the readable text, and prints
ONE summary table. It is polite: an honest User-Agent, robots.txt is checked, one request per page, a pause between
requests, and no attempt to get past paywalls or blocks. If a site says no, that is an answer too.

    python experiment_articles.py                    10 sample stocks, 3 headlines each, both sources
    python experiment_articles.py PFC VEDL TRENT     your own stocks (symbols from nifty100.csv)
    python experiment_articles.py --samples          also print the first words of a few readable articles
    python experiment_articles.py --sites            also print every website: tried / readable / usable

Needs:  pip install trafilatura googlenewsdecoder
Run it on your laptop AND on the VM: results can differ, and the VM is where the real run happens.
"""
import argparse
import csv
import datetime
import re
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
# Who we trust. PLAIN DATA: edit freely, no logic here. A site not listed is "?" and is named in the summary, so new ones get noticed.
# A subdomain counts too (m.livemint.com is livemint.com). This is our judgment, not a measurement: report cards will tell.
SOURCE_TIERS = {
    "A": [   # established news and business outlets
        "business-standard.com", "livemint.com", "thehindubusinessline.com", "ndtvprofit.com", "businesstoday.in",
        "financialexpress.com", "moneycontrol.com", "news18.com", "thehindu.com", "telegraphindia.com",
        "indiatvnews.com", "zeebiz.com", "businessworld.in", "marketwatch.com",
    ],
    "B": [   # finance sites, aggregators, brokers, data vendors
        "tradingview.com", "scanx.trade", "investmentguruindia.com", "goodreturns.in", "kalkine.co.in",
        "equitymaster.com", "marketsmojo.com", "digitalterminal.in", "mediabrief.com", "sahi.com",
        "univest.in", "upstox.com", "pluang.com",
    ],
}
TIER_ORDER = ["A", "B", "?"]
FRESH_DAYS = 3                   # an article this many days old or newer counts as fresh (the same window as Google's when:3d)
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


def count_company_mentions(symbol: str, company: str, text: str) -> int:
    """How many times the article body names the company (full name, first two words, or the symbol).
    Same idea as mentions_company() in morning_run.py, but whole words only: inside a long article a bare
    substring match would make 'ITC' match 'switch' and 'ABB' match 'abbreviation'."""
    name = clean_name(company)
    names = {name.lower(), " ".join(name.split()[:2]).lower(), symbol.lower()}
    names.discard("")
    pattern = "|".join(rf"(?<!\w){re.escape(n)}(?!\w)" for n in sorted(names, key=len, reverse=True))
    return len(re.findall(pattern, text.lower()))


def article_date(body: bytes):
    """The publish date (a datetime.date) read from the page's own metadata, or None if there is no date we can read."""
    try:
        import trafilatura
        found = trafilatura.extract_metadata(body.decode("utf-8", "replace")).date
        return datetime.date.fromisoformat(found) if found else None
    except Exception:
        return None


def age_in_days(published, today):
    """Whole days between publication and today. None if there is no date, or if it lies in the future (we do not trust
    it). One day of slack is allowed for time zones."""
    if published is None:
        return None
    days = (today - published).days
    return max(days, 0) if days >= -1 else None


def is_fresh(row) -> bool:
    return bool(row["readable"] and row["age_days"] is not None and row["age_days"] <= FRESH_DAYS)


def is_usable(row) -> bool:
    """Readable, names the company, and fresh. (A source-quality test will join these later.)"""
    return bool(is_fresh(row) and row["mentions"] > 0)


# ------------------------------------------------------------------------------ the experiment
def run_one(source, item, symbol, deps, company=""):
    started = time.time()
    row = {"source": source, "symbol": symbol, "title": item["title"][:100], "domain": "?", "real_url": False,
           "fetched": False, "readable": False, "chars": 0, "mentions": 0, "age_days": None, "reason": "", "seconds": 0.0, "text": ""}
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
        published = deps.get("date_of", article_date)(body)
        row.update(readable=True, text=text, mentions=count_company_mentions(symbol, company or symbol, text),
                   age_days=age_in_days(published, deps.get("today", datetime.date.today)()))
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
                             "readable": False, "chars": 0, "mentions": 0, "age_days": None, "reason": "no headlines found", "seconds": 0.0, "text": "", "empty": True})
            for item in items:
                rows.append(run_one(source, item, symbol, deps, company))
    return rows


def tier_of(domain: str) -> str:
    """'A', 'B' or '?' (not listed). A subdomain of a listed site counts as that site."""
    for tier, sites in SOURCE_TIERS.items():
        if any(domain == site or domain.endswith("." + site) for site in sites):
            return tier
    return "?"


def usable_by_tier(rows) -> dict:
    counts = {tier: 0 for tier in TIER_ORDER}
    for r in rows:
        if is_usable(r):
            counts[tier_of(r["domain"])] += 1
    return counts


def unrated_sites(rows) -> list:
    """Websites we reached that are in no tier, alphabetical."""
    return sorted({r["domain"] for r in rows if r["real_url"] and tier_of(r["domain"]) == "?"})


def site_stats(rows):
    """Per website: (domain, tried, readable, usable), most-tried first, ties in alphabetical order."""
    stats = defaultdict(lambda: [0, 0, 0])
    for r in rows:
        if r["real_url"]:
            counts = stats[r["domain"]]
            counts[0] += 1
            counts[1] += bool(r["readable"])
            counts[2] += is_usable(r)
    return sorted(((domain, *counts) for domain, counts in stats.items()), key=lambda row: (-row[1], row[0]))


def summarize(rows, symbols, sources, show_samples=False, show_sites=False):
    for source in sources:
        mine = [r for r in rows if r["source"] == source and not r.get("empty")]
        total = len(mine)
        pct = lambda n: f"{n} ({100 * n / total:.0f}%)" if total else "0"
        real, fetched, readable = (sum(r[k] for r in mine) for k in ("real_url", "fetched", "readable"))
        covered = len({r["symbol"] for r in mine if r["readable"]})
        names_company = sum(r["readable"] and r["mentions"] > 0 for r in mine)
        fresh, usable = sum(is_fresh(r) for r in mine), sum(is_usable(r) for r in mine)
        no_date = sum(r["readable"] and r["age_days"] is None for r in mine)
        no_headlines = [r["symbol"] for r in rows if r["source"] == source and r.get("empty")]
        print(f"\n=== SOURCE: {source.upper()} " + "=" * 50)
        print(f"  headlines found:                     {total}" + (f"   (no headlines at all for: {', '.join(no_headlines)})" if no_headlines else ""))
        print(f"  real article address found:          {pct(real)}")
        print(f"  page opened (allowed, HTTP 200):     {pct(fetched)}")
        print(f"  readable article text (>= {MIN_READABLE_CHARS}):    {pct(readable)}")
        print(f"  readable AND names the company:      {pct(names_company)}")
        print(f"  readable AND fresh (<= {FRESH_DAYS} days old):      {pct(fresh)}   (no readable date on the page: {no_date})")
        print(f"  USABLE = readable + names it + fresh: {pct(usable)}")
        print("  usable, by source tier:              " + ", ".join(f"{tier} {n}" for tier, n in usable_by_tier(mine).items()))
        if unrated_sites(mine):
            print("  unrated websites (tier ?):           " + ", ".join(unrated_sites(mine)))
        print(f"  stocks with at least one readable:   {covered} of {len(symbols)}")
        lengths = [r["chars"] for r in mine if r["readable"]]
        if lengths:
            print(f"  typical readable length:             {int(statistics.median(lengths)):,} characters (median)")
        reasons = Counter(r["reason"].split(" (")[0] for r in mine if r["reason"])
        if reasons:
            print("  why the rest failed:                 " + "; ".join(f"{why} x{n}" for why, n in reasons.most_common(5)))
        sites = site_stats(mine)
        if sites:
            print("  by website (usable / tried):         " + ", ".join(f"{d} {u}/{t}" for d, t, g, u in sites[:8]))
            if show_sites:
                print(f"  {'ALL WEBSITES':30}{'tier':>4} {'tried':>5} {'readable':>8} {'usable':>6}")
                for d, t, g, u in sites:
                    print(f"    {d:28}{tier_of(d):>4} {t:>5} {g:>8} {u:>6}")
        if show_samples:
            for r in [r for r in mine if r["readable"]][:3]:
                print(f"  sample [{r['domain']}]: {' '.join(r['text'].split())[:160]}...")
        print(f"  time spent:                          {sum(r['seconds'] for r in mine):.0f} seconds")


def save_csv(rows, path="experiment_articles_results.csv"):
    fields = ["source", "symbol", "title", "domain", "real_url", "fetched", "readable", "tier", "chars", "mentions", "age_days", "reason", "seconds"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({**r, "tier": tier_of(r["domain"]) if r["real_url"] else ""} for r in rows)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("symbols", nargs="*", help="stock symbols from nifty100.csv (default: 10 samples)")
    parser.add_argument("--sources", nargs="+", default=["google", "bing"], choices=["google", "bing"])
    parser.add_argument("--per-stock", type=int, default=3, help="headlines per stock and source")
    parser.add_argument("--pause", type=float, default=1.5, help="seconds to wait before each page request")
    parser.add_argument("--samples", action="store_true", help="print the first words of a few readable articles")
    parser.add_argument("--sites", action="store_true", help="print the full table of websites (tried / readable / usable)")
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
    summarize(rows, symbols, args.sources, args.samples, args.sites)
    print(f"\nDetails (titles, websites, reasons; no article text) saved to {save_csv(rows)}")


if __name__ == "__main__":
    main()
