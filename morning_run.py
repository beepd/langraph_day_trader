import csv
import os
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from datetime import time as dtime
from email.utils import parsedate_to_datetime
from typing import Literal, TypedDict
from urllib.parse import quote_plus

import yfinance as yf
from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel, Field

from rules import (
    size_trade, STARTING_BALANCE, RISK_PER_TRADE, MAX_POSITION_FRACTION,
    MIN_REWARD_RISK, MIN_STOP_RANGE_FRACTION, MAX_TARGET_RANGE_FRACTION,
)
from storage import start_run, save_run_details, mark_run, get_available_balance
from llm_setup import build_llm, PROVIDER, MODEL
import messages as msg
from notify import send_telegram

load_dotenv()
llm = build_llm()                                  # which model? see llm_setup.py

# ----------------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------------
VERBOSE = True            # True = explain every step. False = only the final summary.
SHOW_PROMPTS = False      # True = also print the exact text sent to the model.

MIN_CHANGE = 0.5          # a stock must be up at least this % from yesterday's close
MIN_REL_VOLUME = 1.0      # and trade at least this multiple of its normal volume pace
MAX_CANDIDATES = 10       # how many movers go on to the news step
MAX_POSITIONS = 3         # buy at most this many stocks a day
IST = timezone(timedelta(hours=5, minutes=30))

# Market-closed guard (the app only starts a run inside this window, on a trading day)
RUN_FROM = dtime(9, 30)       # the market opens at 09:15; early prices are too noisy
RUN_UNTIL = dtime(14, 30)     # too little of the day is left to reach a target after this
FORCE_RUN = os.getenv("FORCE_RUN", "").strip().lower() in {"1", "true", "yes"}   # testing only: skip the guard
NSE_HOLIDAYS = {d.strip() for d in os.getenv("NSE_HOLIDAYS", "").split(",") if d.strip()}   # e.g. 2026-11-08,2026-11-24


def say(message: str = "") -> None:
    if VERBOSE:
        print(message)


def banner(title: str) -> None:
    say()
    say("=" * 72)
    say(title)
    say("=" * 72)


def load_universe() -> dict[str, str]:
    universe = {}
    with open("nifty100.csv", newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            universe[row["Symbol"].strip()] = row["Company Name"].strip()
    return universe


UNIVERSE = load_universe()


# ----------------------------------------------------------------------------
# Forms Gemini must fill in, and the shared state
# ----------------------------------------------------------------------------
class Verdict(BaseModel):
    has_catalyst: bool = Field(description="True only if the headlines show a fresh, specific reason for the stock to move")
    bullish: bool = Field(description="True only if that news points to upside today")
    strength: Literal["strong", "weak"] = Field(description="strong = specific news about this company (results, order win, upgrade with a target, deal); weak = sector-level, indirect or speculative")
    catalyst_type: Literal["earnings", "broker_call", "block_deal", "sector_news", "other"]
    reason: str = Field(description="One or two sentences, based only on the headlines")
    source_numbers: list[int] = Field(description="Numbers of the headlines that support the reason, [] if none")


class TradePlan(BaseModel):
    stop: float = Field(description="Stop-loss price, below the buy price")
    target: float = Field(description="Target price, above the buy price, to sell at for a profit")
    reason: str = Field(description="One sentence explaining the stop and target")


class State(TypedDict):
    stocks: list[str]
    changes: dict[str, float]
    rel_volumes: dict[str, float]
    prices: dict[str, float]
    avg_ranges: dict[str, float]
    headlines: dict[str, list[dict]]
    verdicts: dict[str, Verdict]
    watchlist: list[str]
    plans: list[dict]
    plan_log: list[dict]
    stats: dict[str, int]
    balance: float
    can_run: bool
    market_note: str


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def session_fraction(now=None) -> float:
    """How much of the 9:15-15:30 trading day has passed (0.05 to 1.0)."""
    now = now or datetime.now(IST)
    minutes = (now.hour * 60 + now.minute) - (9 * 60 + 15)
    return min(max(minutes / 375, 0.05), 1.0)


def round_to_tick(price: float) -> float:
    """NSE prices move in steps of 0.05."""
    return round(round(price / 0.05) * 0.05, 2)


def news_query(company: str) -> str:
    clean = company.replace(" Ltd.", "").replace(" Limited", "")
    return f'"{clean}" when:3d'


def get_headlines(company: str) -> list[dict]:
    url = "https://news.google.com/rss/search?q=" + quote_plus(news_query(company)) + "&hl=en-IN&gl=IN&ceid=IN:en"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=10) as response:
        xml_text = response.read().decode("utf-8")
    items = list(ET.fromstring(xml_text).iter("item"))[:5]
    headlines = []
    for item in items:
        title = item.findtext("title", default="").replace("₹", "Rs ")      # the rupee sign confused Gemini once
        try:
            published = parsedate_to_datetime(item.findtext("pubDate", default="")).astimezone(IST)
            date_text = published.strftime("%d %b")
            published_iso = published.isoformat()
        except (TypeError, ValueError):
            date_text, published_iso = "date unknown", None
        headlines.append({
            "text": f"({date_text}) {title}",          # what Gemini sees
            "title": title,
            "source": item.findtext("source", default=""),
            "published_at": published_iso,
            "url": item.findtext("link", default=""),
        })
    return headlines


def mentions_company(symbol: str, company: str, headline: str) -> bool:
    name = company.replace(" Ltd.", "").replace(" Limited", "")
    short_name = " ".join(name.split()[:2]).lower()          # first two words, e.g. "sbi life"
    text = headline.lower()
    return short_name in text or symbol.lower() in text


def ask_verdict(analyst, prompt: str) -> Verdict:
    """Ask Gemini. If the answer looks garbled (text leaking into the reason), try once more."""
    for attempt in range(2):
        verdict = analyst.invoke(prompt)
        reason = verdict.reason
        garbled = len(reason) > 400 or "\n" in reason or "the user" in reason.lower()
        if not garbled:
            return verdict
        say(f"   (garbled answer from the model, attempt {attempt + 1} of 2)")
    first_line = verdict.reason.split("\n")[0].strip()
    if len(first_line) < 20 or "the user" in first_line.lower():
        verdict.has_catalyst = False
        verdict.reason = "REJECTED by code: the model's answer was garbled twice"
    else:
        verdict.reason = first_line[:300] + " [trimmed: answer was garbled]"
    return verdict


# ----------------------------------------------------------------------------
# Step 1: screener (plain code, no AI)
# ----------------------------------------------------------------------------
def screen_stocks(state: State) -> dict:
    started = time.time()
    banner("STEP 1: SCREENER - which Nifty 100 stocks are moving today?")
    now = datetime.now(IST)
    say(f"Time now (IST): {now:%A %d %b %Y, %H:%M}")
    say(f"Universe: {len(UNIVERSE)} stocks from nifty100.csv")
    say("Downloading one month of daily prices for all of them (one request)...")
    tickers = [symbol + ".NS" for symbol in UNIVERSE]
    data = yf.download(tickers, period="1mo", interval="1d", group_by="ticker", auto_adjust=False, progress=False)
    say(f"Download finished in {time.time() - started:.1f} seconds")

    available = set(data.columns.get_level_values(0))
    counts = {"no price data from Yahoo": 0, "too little history": 0, "not up enough": 0, "up, but volume too low": 0}
    found = []
    near_misses = []
    latest_candle = None
    for symbol in UNIVERSE:
        if symbol + ".NS" not in available:
            counts["no price data from Yahoo"] += 1
            continue
        frame = data[symbol + ".NS"].dropna(subset=["Close"])
        if len(frame) < 6:
            counts["too little history"] += 1
            continue
        closes = frame["Close"]
        volumes = frame["Volume"]
        last_date = frame.index[-1].date()
        latest_candle = last_date if latest_candle is None else max(latest_candle, last_date)
        live = last_date == now.date()                                   # is the last row today's unfinished day?
        fraction = session_fraction(now) if live else 1.0
        change = (closes.iloc[-1] / closes.iloc[-2] - 1) * 100
        rel_volume = volumes.iloc[-1] / (volumes.iloc[:-1].mean() * fraction)
        price = closes.iloc[-1]
        avg_range = (frame["High"] - frame["Low"]).tail(14).mean()       # typical daily range
        if change < MIN_CHANGE:
            counts["not up enough"] += 1
            continue
        if rel_volume < MIN_REL_VOLUME:
            counts["up, but volume too low"] += 1
            near_misses.append((symbol, change, rel_volume))
            continue
        found.append((symbol, change, rel_volume, change * min(rel_volume, 3), price, avg_range))

    if latest_candle == now.date():
        say(f"Latest price candle is TODAY's. Volume pace is scaled to {session_fraction(now):.0%} of the trading day.")
    else:
        say(f"Latest price candle is from {latest_candle}, not today, so these are completed-session numbers.")

    say()
    say("Funnel:")
    say(f"   {len(UNIVERSE)} stocks in the universe")
    for reason, n in counts.items():
        say(f"   - {n:>3} dropped: {reason}")
    say(f"   = {len(found)} passed both tests (up at least {MIN_CHANGE}% and volume pace at least {MIN_REL_VOLUME}x)")

    if near_misses:
        near_misses.sort(key=lambda m: m[1], reverse=True)
        say()
        say("Biggest gainers that failed only on volume:")
        for symbol, change, rel_volume in near_misses[:5]:
            say(f"   {symbol:<12} {change:+6.2f}%   volume only x{rel_volume:.1f}")

    found.sort(key=lambda m: m[3], reverse=True)
    top = found[:MAX_CANDIDATES]
    say()
    say(f"Keeping the top {len(top)} (ranked by % move x volume pace, volume capped at 3x):")
    for symbol, change, rel_volume, score, price, avg_range in top:
        say(f"   {symbol:<12} {price:>9.2f}  {change:+6.2f}%   volume x{rel_volume:.1f}   typical daily range {avg_range:.2f}")
    say(f"(step took {time.time() - started:.1f}s)")
    send_telegram(msg.screener(len(found), len(UNIVERSE), [(s, p, c, v) for s, c, v, _, p, _ in top],
                               latest_candle == now.date()))
    return {
        "stocks": [m[0] for m in top],
        "changes": {m[0]: m[1] for m in top},
        "rel_volumes": {m[0]: m[2] for m in top},
        "prices": {m[0]: float(m[4]) for m in top},
        "avg_ranges": {m[0]: float(m[5]) for m in top},
        "stats": {"universe": len(UNIVERSE), "passed_screen": len(found), "live": int(latest_candle == now.date())},
    }


# ----------------------------------------------------------------------------
# Step 2: news (plain code)
# ----------------------------------------------------------------------------
def fetch_news(state: State) -> dict:
    banner("STEP 2: NEWS - what is being said about each mover?")
    headlines = {}
    for symbol in state["stocks"]:
        company = UNIVERSE[symbol]
        say(f"{symbol} ({company}) - searching Google News for: {news_query(company)}")
        began = time.time()
        try:
            titles = get_headlines(company)
        except Exception as error:                                       # one failed search must not stop the run
            say(f"   FAILED: {error}")
            titles = []
        headlines[symbol] = titles
        say(f"   found {len(titles)} headlines in {time.time() - began:.1f}s")
        for h in titles:
            say(f"   - {h['text']}")
    send_telegram(msg.news(sum(1 for titles in headlines.values() if titles), len(headlines),
                           [s for s, titles in headlines.items() if not titles]))
    return {"headlines": headlines}


# ----------------------------------------------------------------------------
# Step 3: analyst (Gemini reads the headlines, code double-checks)
# ----------------------------------------------------------------------------
def analyze_news(state: State) -> dict:
    banner("STEP 3: ANALYST - is there a real reason behind each move?")
    analyst = llm.with_structured_output(Verdict)
    verdicts = {}
    watchlist = []
    for symbol in state["stocks"]:
        company = UNIVERSE[symbol]
        change = state["changes"][symbol]
        rel_volume = state["rel_volumes"][symbol]
        titles = state["headlines"][symbol]
        say(f"{symbol} ({company}): up {change:.1f}% on {rel_volume:.1f}x volume, {len(titles)} headlines")

        if not titles:
            say("   no headlines to judge, so no catalyst (model not asked)")
            verdicts[symbol] = Verdict(has_catalyst=False, bullish=False, strength="weak", catalyst_type="other",
                                       reason="No headlines found", source_numbers=[])
            continue

        numbered = ""
        for i, h in enumerate(titles, start=1):
            numbered += f"[{i}] {h['text']}\n"
        today = datetime.now(IST).strftime("%A, %d %B %Y")
        prompt = f"""You are a careful stock analyst. Today is {today}.
{company} is up {change:.1f}% today on {rel_volume:.1f}x its normal volume.
Using ONLY these headlines (each shows its date), decide whether there is a fresh, specific reason (a catalyst) for it to rise today.

Rules:
- News older than 3 days is not fresh.
- If the headlines are generic, old, or unrelated, there is no catalyst.
- The headline you cite must name this company. "Likely includes", "may include" or a mention of the sector is NOT enough.
- "Top stocks to buy" lists and single-analyst tips are weak at best.
- A block deal alone is neutral, because one party is selling while another is buying. Only call it bullish if the headline says more.
- strength: "strong" only for company results, an order win, a regulatory approval, a deal, or an upgrade/target from a named brokerage. Everything else is "weak".

{numbered}"""
        if SHOW_PROMPTS:
            say("   ---- prompt sent to the model ----")
            say(prompt)
            say("   -------------------------------")

        say("   asking the model...")
        began = time.time()
        verdict = ask_verdict(analyst, prompt)
        say(f"   model answered in {time.time() - began:.1f}s: catalyst={verdict.has_catalyst}, bullish={verdict.bullish}, "
            f"strength={verdict.strength}, type={verdict.catalyst_type}")
        say(f"   reason: {verdict.reason}")

        cited = [titles[n - 1]["text"] for n in verdict.source_numbers if 1 <= n <= len(titles)]
        for title in cited:
            say(f"   cited headline: {title}")
        named = any(mentions_company(symbol, company, t) for t in cited)
        if verdict.has_catalyst:
            say(f"   code check - does a cited headline name the company? {'yes' if named else 'NO'}")
        if verdict.has_catalyst and not named:
            verdict.has_catalyst = False
            verdict.reason = "REJECTED by code: no cited headline names the company. " + verdict.reason
        verdicts[symbol] = verdict

        if not verdict.has_catalyst:
            say("   -> NOT on watchlist: no real catalyst")
        elif not verdict.bullish:
            say("   -> NOT on watchlist: the news is not bullish")
        elif verdict.strength != "strong":
            say("   -> NOT on watchlist: catalyst is only weak")
        else:
            say("   -> ON WATCHLIST (strong, bullish catalyst)")
            watchlist.append(symbol)
    send_telegram(msg.analyst([(s, verdicts[s].reason) for s in watchlist], len(verdicts)))
    return {"verdicts": verdicts, "watchlist": watchlist}


# ----------------------------------------------------------------------------
# Step 4: trade planner (Gemini proposes, the rulebook decides)
# ----------------------------------------------------------------------------
def plan_trades(state: State) -> dict:
    banner("STEP 4: TRADE PLANNER - the model suggests, the rulebook decides")
    balance = state["balance"]
    say(f"Rules: balance {balance:,.0f} | risk {RISK_PER_TRADE:.0%} of balance per trade | "
        f"max {MAX_POSITION_FRACTION:.0%} in one stock | min reward/risk {MIN_REWARD_RISK} | max {MAX_POSITIONS} positions")
    planner = llm.with_structured_output(TradePlan)
    plans = []
    plan_log = []                                              # every outcome: accepted, rejected or skipped
    for symbol in state["watchlist"]:
        if len(plans) >= MAX_POSITIONS:
            say(f"{symbol}: skipped, already have {MAX_POSITIONS} positions")
            plan_log.append({"symbol": symbol, "status": "skipped",
                             "rejection_reason": f"already have {MAX_POSITIONS} positions", "entry": state["prices"][symbol]})
            continue
        company = UNIVERSE[symbol]
        entry = state["prices"][symbol]
        avg_range = state["avg_ranges"][symbol]
        verdict = state["verdicts"][symbol]
        say()
        say(f"{symbol} ({company})")
        say(f"   buy at {entry:.2f}; typical daily range {avg_range:.2f} ({avg_range / entry * 100:.1f}% of price)")
        say(f"   rulebook wants: stop at least {MIN_STOP_RANGE_FRACTION * avg_range:.2f} below "
            f"(so {entry - MIN_STOP_RANGE_FRACTION * avg_range:.2f} or lower), "
            f"target at most {MAX_TARGET_RANGE_FRACTION * avg_range:.2f} above (so {entry + MAX_TARGET_RANGE_FRACTION * avg_range:.2f} or lower)")
        prompt = f"""You are a day trader planning ONE trade that must be closed before the market closes today.
Stock: {company}, currently at {entry:.2f} (you buy at this price).
Its typical daily range is {avg_range:.2f} rupees ({avg_range / entry * 100:.1f}% of the price).
Why it is on the watchlist ({verdict.strength}): {verdict.reason}

Suggest a stop-loss and a target.
Rules:
- The stop-loss goes below {entry:.2f}, at least about a third of the typical daily range away, so normal wobble does not trigger it.
- The target goes above {entry:.2f}, no more than about one typical daily range away.
- The target must be at least 1.7 times as far above the buy price as the stop-loss is below it.
- Explain in one plain sentence."""
        if SHOW_PROMPTS:
            say("   ---- prompt sent to the model ----")
            say(prompt)
            say("   -------------------------------")
        say("   asking the model for a stop and a target...")
        plan = planner.invoke(prompt)
        stop = round_to_tick(plan.stop)
        target = round_to_tick(plan.target)
        say(f"   model proposed: stop {plan.stop:.2f}, target {plan.target:.2f}  (rounded to NSE steps: {stop:.2f} / {target:.2f})")
        reason = plan.reason.split("\n")[0][:200]
        say(f"   model's reason: {reason}")

        result = size_trade(balance, entry, stop, target, avg_range)
        if not result["ok"]:
            say(f"   rulebook says NO: {result['reason']}")
            plan_log.append({"symbol": symbol, "status": "rejected", "rejection_reason": result["reason"],
                             "entry": entry, "stop": stop, "target": target, "gemini_reason": reason})
            continue
        say(f"   rulebook says YES: buy {result['shares']} shares, cost {result['cost']:,.0f} "
            f"({result['cost'] / balance:.0%} of balance)")
        say(f"   if the stop hits you lose about {result['max_loss']:,.0f}; if the target hits you gain about {result['max_gain']:,.0f} "
            f"(reward/risk {result['reward_risk']:.2f})")
        plans.append({"symbol": symbol, "entry": entry, "stop": stop, "target": target, "reason": reason, **result})
        plan_log.append({"symbol": symbol, "status": "accepted", "entry": entry, "stop": stop, "target": target,
                         "shares": result["shares"], "cost": result["cost"], "max_loss": result["max_loss"],
                         "max_gain": result["max_gain"], "gemini_reason": reason})
    rejected = [(p["symbol"], p["rejection_reason"]) for p in plan_log if p["status"] == "rejected"]
    skipped = [p["symbol"] for p in plan_log if p["status"] == "skipped"]
    send_telegram(msg.plans(plans, rejected, skipped, balance))
    return {"plans": plans, "plan_log": plan_log}


def decide(state: State) -> Literal["continue", "stop"]:
    if len(state["stocks"]) == 0:
        say("\nNothing is moving enough today: stopping here, no trades.")
        return "stop"
    return "continue"


def decide_after_analysis(state: State) -> Literal["plan", "stop"]:
    if len(state["watchlist"]) == 0:
        say("\nNo strong catalyst on any mover: stopping here, no trades.")
        return "stop"
    return "plan"


# ----------------------------------------------------------------------------
# The graph
# ----------------------------------------------------------------------------
# ----------------------------------------------------------------------------
# Step 0: preflight (is the market open? how much money is available?)
# ----------------------------------------------------------------------------
def check_market_open(now: datetime, nifty_has_today_candle) -> tuple[bool, str]:
    """Plain rules, no network. nifty_has_today_candle is True, False, or None (could not check)."""
    if now.weekday() >= 5:
        return False, "it is the weekend"
    if now.date().isoformat() in NSE_HOLIDAYS:
        return False, "today is listed in NSE_HOLIDAYS"
    if now.time() < RUN_FROM:
        return False, f"too early (the app runs from {RUN_FROM:%H:%M} IST; the market opens at 09:15)"
    if now.time() > RUN_UNTIL:
        return False, f"too late (no new trades after {RUN_UNTIL:%H:%M} IST)"
    if nifty_has_today_candle is False:
        return False, "no Nifty price candle for today, so the market looks closed (a holiday?)"
    return True, "market is open"


def nifty_traded_today(now: datetime):
    """Does Yahoo have a Nifty candle dated today? Returns None if we could not check."""
    try:
        history = yf.Ticker("^NSEI").history(period="5d")
        return len(history) > 0 and history.index[-1].date() == now.date()
    except Exception:
        return None


def preflight(state: State) -> dict:
    banner("STEP 0: PREFLIGHT - is the market open, and how much money is available?")
    now = datetime.now(IST)
    say(f"Time now (IST): {now:%A %d %b %Y, %H:%M}")

    if FORCE_RUN:
        say("FORCE_RUN is on: skipping the market-open check (testing only)")
        is_open, why = True, "forced"
    else:
        is_open, why = check_market_open(now, None)          # cheap checks first, no network
        if is_open:
            candle = nifty_traded_today(now)
            if candle is None:
                say("   (could not check Yahoo for today's Nifty candle; carrying on)")
            is_open, why = check_market_open(now, candle)
    if not is_open:
        say(f"MARKET CLOSED: {why}. Stopping, no trades.")
        send_telegram(msg.market_closed(why))
        return {"can_run": False, "market_note": why, "balance": 0.0}
    say(f"Market check passed: {why}")

    try:
        balance, source = get_available_balance(STARTING_BALANCE)
    except Exception as error:
        say(f"Could not read the balance from Supabase: {error}")
        say("Stopping: the app will not guess how much money is available.")
        send_telegram(msg.balance_problem(error))
        return {"can_run": False, "market_note": "balance unavailable", "balance": 0.0}
    say(f"Available balance: {balance:,.2f} ({source})")
    send_telegram(msg.run_started(now, balance, source, f"{PROVIDER} / {MODEL}"))
    return {"can_run": True, "market_note": why, "balance": balance}


def decide_after_preflight(state: State) -> Literal["go", "stop"]:
    return "go" if state["can_run"] else "stop"


graph = StateGraph(State)
graph.add_node("preflight_node", preflight)
graph.add_node("screen_stocks_node", screen_stocks)
graph.add_node("fetch_news_node", fetch_news)
graph.add_node("analyze_news_node", analyze_news)
graph.add_node("plan_trades_node", plan_trades)
graph.add_edge(START, "preflight_node")
graph.add_conditional_edges("preflight_node", decide_after_preflight, {"go": "screen_stocks_node", "stop": END})
graph.add_conditional_edges("screen_stocks_node", decide, {"continue": "fetch_news_node", "stop": END})
graph.add_edge("fetch_news_node", "analyze_news_node")
graph.add_conditional_edges("analyze_news_node", decide_after_analysis, {"plan": "plan_trades_node", "stop": END})
graph.add_edge("plan_trades_node", END)
app = graph.compile()


current = {"run_id": None}                                   # lets the crash handler below find the run


def main() -> None:
    started = time.time()
    started_at = datetime.now(IST)
    print(f"Model: {PROVIDER} / {MODEL}")
    run_id = start_run(started_at, f"{PROVIDER}:{MODEL}")        # the run is on record from the very start
    current["run_id"] = run_id
    result = app.invoke({"stocks": [], "changes": {}, "rel_volumes": {}, "prices": {}, "avg_ranges": {},
                         "headlines": {}, "verdicts": {}, "watchlist": [], "plans": [], "plan_log": [], "stats": {},
                         "balance": 0.0, "can_run": False, "market_note": ""})

    if not result["can_run"]:
        mark_run(run_id, "skipped", note=result["market_note"])
        print(f"\nRun stopped at preflight: {result['market_note']}. Recorded as a skipped run.")
        return

    stats = result.get("stats", {})
    plans = result["plans"]
    print()
    print("=" * 72)
    print("SUMMARY")
    print("=" * 72)
    print(f"Funnel: {stats.get('universe', len(UNIVERSE))} stocks checked -> {stats.get('passed_screen', 0)} moving -> "
          f"{len(result['stocks'])} examined for news -> {len(result['watchlist'])} strong catalysts -> {len(plans)} trade plans")
    for symbol, v in result["verdicts"].items():
        mark = "ON WATCHLIST" if symbol in result["watchlist"] else "no"
        print(f"   {symbol:<12} catalyst={str(v.has_catalyst):<5} strength={v.strength:<6} watchlist={mark}")

    print()
    print("TRADE PLANS:")
    if not plans:
        print("   No trades today.")
    for p in plans:
        print(f"   {p['symbol']}: buy {p['shares']} @ {p['entry']:.2f}   stop {p['stop']:.2f}   target {p['target']:.2f}   "
              f"(risk {p['max_loss']:.0f}, reward {p['max_gain']:.0f})")
        print(f"      {p['reason']}")
    if plans:
        cost = sum(p["cost"] for p in plans)
        print(f"   Cash used {cost:,.0f} of {result['balance']:,.0f} (left {result['balance'] - cost:,.0f}); "
              f"worst case if every stop hits: -{sum(p['max_loss'] for p in plans):,.0f}")

    settings = {"min_change": MIN_CHANGE, "min_rel_volume": MIN_REL_VOLUME, "max_candidates": MAX_CANDIDATES,
                "max_positions": MAX_POSITIONS, "balance_at_start": result["balance"],
                "risk_per_trade": RISK_PER_TRADE, "max_position_fraction": MAX_POSITION_FRACTION}
    save_error = None
    try:                                                       # a saving problem must never lose the run's output
        if run_id is None:                                     # Supabase was unreachable at the start: try once more
            run_id = start_run(started_at, f"{PROVIDER}:{MODEL}")
            current["run_id"] = run_id
        if run_id is None:
            raise RuntimeError("could not create the run record")
        save_run_details(run_id, result, settings)
        print(f"\nSaved to Supabase as run #{run_id}")
    except Exception as error:
        save_error = error
        print(f"\nCould not save to Supabase: {error}")
    send_telegram(msg.run_complete(plans, result["balance"], run_id, save_error))
    print(f"\nTotal run time: {time.time() - started:.0f} seconds")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:                                 # record it, tell me on Telegram, then fail loudly as before
        mark_run(current["run_id"], "failed", error=f"{type(error).__name__}: {error}")
        send_telegram(msg.crash("Morning run", error))
        raise