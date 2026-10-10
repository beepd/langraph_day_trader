"""
Blog step B4b: turn a fact bundle (blog_facts.py / blog_weekly.py) into a draft post, and CHECK the draft.

The rule of the whole blog: code supplies every number, the model only supplies words. So this file:
  1. builds the prompt: the facts (JSON) plus plain rules for the writer,
  2. asks the model for a title, a search-result description and the body text,
  3. checks the text in code: every number must exist in the facts (or be a fixed app rule), no advice or predictions,
     no feelings attributed to the bot, a sensible length, the simulation stated up front. A failed draft gets one retry
     with the problems listed,
  4. assembles the final post: the writer's first paragraph, then the TABLES (built by code, so they cannot be wrong),
     then the rest of the writer's text, then a fixed disclosure footer (also code, never the model).

Nothing here touches the database. Saving drafts is the next step (B5). For now it writes a local file to read:
    python blog_writer.py daily  2026-10-09      -> blog_draft_daily_2026-10-09.md
    python blog_writer.py weekly 2026-10-10      -> blog_draft_weekly_2026-10-10.md
(it calls the model set in .env, so it costs a few paise; use it on the VM, which has the key)

What the number check can and cannot do: it catches numbers that are NOT in the facts (invented, added up, averaged).
It cannot catch a real number attached to the wrong thing, or a wrong sign, so you still read the draft before publishing.
"""
import json
import math
import re
import sys
from datetime import date

from pydantic import BaseModel, Field

# The app's fixed rules, from the README (keep in sync if you change them). The writer may mention these numbers.
APP_RULES = {
    "stocks_screened": 100, "candidates_per_day_at_most": 10, "min_rise_pct": 0.5, "min_volume_pace": 1.0,
    "max_positions_per_day": 3, "risk_per_trade_pct_of_balance": 1, "max_money_in_one_stock_pct": 30,
    "morning_run_time_ist": "09:35", "square_off_time_ist": "15:15", "quick_stop_minutes": 60,
    "starting_balance_rs": 100000, "news_window_days": 3,
}

DISCLOSURE = (
    "*Simulation notice: this is a paper-trading experiment with fake money. No real orders are placed. All results are gross, "
    "before brokerage, taxes and slippage, and a few days of results prove nothing. Nothing here is investment advice or a "
    "recommendation to buy or sell any security; stocks named are examples from the simulation. This post was written by an AI "
    "from the app's recorded data, and the tables are produced directly from the database.*")

# Changes to the bot's rules, with the date they start. The model must not describe a rule on a day before it existed.
RULE_CHANGES = [("2026-10-12", "From 12 October 2026 the bot keeps at most one strong stock per sector. Before that date the bot had NO limit per sector, so "
                               "several stocks from one sector could be held on the same day. "
                               "On the same date the AI's rating step also becomes stricter: it must answer a fixed list of factual questions about each headline and code "
                               "decides which stocks count as strong. So a before/after comparison cannot isolate the sector limit alone. Say so honestly, and NEVER claim that "
                               "all other rules or parameters stay unchanged.")]
UNCHANGED_CLAIMS = ["remain unchanged", "remains unchanged", "stay unchanged", "stays unchanged", "be unchanged", "all other rules", "all other risk",
                    "all other parameters", "everything else unchanged", "isolate the effect"]
LABEL_PLAIN = {"strong by the rules, dropped (not on the watchlist, for example the one-per-sector rule)": "rated strong, but dropped by the rules before trading"}

LENGTH = {"daily": (150, 520), "weekly": (400, 1150)}          # words in the writer's text (tables not counted)

BANNED = ["guarantee", "will rise", "will go up", "will surely", "sure to", "risk-free", "you should", "i recommend", "we recommend",
          "buy now", "must buy", "sure thing", "can't lose", "cannot lose"]
HEDGES = ["prove nothing", "proves nothing", "i want to be clear", "small sample", "sample is too small", "too small to", "statistically meaningless"]
JARGON = ["classic", "checklist", "analyst mode", "analyst's mode", "planner", "nudge", "watchlist", "watch list", "overruled", "overrule",
          "overruling", "the analyst", "watching closely", "worth watching", "event type", "event_type", "square-off", "square off"]          # app-internal words readers cannot know
FEELINGS = ["felt", "excited", "nervous", "worried", "frustrated", "scared", "the bot thought", "the bot believed",
            "the bot wanted", "the bot hoped"]


class Post(BaseModel):
    title: str = Field(description="Aim for 55 to 60 characters and NEVER more than 70 (count them). Plain, specific, includes the date or week and 'NSE'.")
    meta_description: str = Field(description="One plain sentence of at most 155 characters, for search results. No hype.")
    body_markdown: str = Field(description="The post text in markdown with ## headings. No tables. No title line.")


# ------------------------------------------------------------------------------ the number check
MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"


def _strip_non_claims(text: str) -> str:
    """Remove things that look like numbers but are not claims: dates, times, list markers."""
    text = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", text)
    text = re.sub(r"\b\d{1,2}:\d{2}\b(\s*(?:am|pm|ist))?", " ", text, flags=re.I)
    text = re.sub(rf"\b\d{{1,2}}\s*[-–—]\s*\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{MONTHS})[a-z]*\.?(?:\s+\d{{4}})?", " ", text, flags=re.I)   # 5-9 October
    text = re.sub(rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{MONTHS})[a-z]*\.?(?:\s+\d{{4}})?", " ", text, flags=re.I)
    text = re.sub(rf"\b(?:{MONTHS})[a-z]*\.?\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?", " ", text, flags=re.I)
    text = re.sub(r"(?m)^\s*(?:[-*]\s+)?\d+[.)]\s+", " ", text)
    return text


def _numbers(text: str) -> list:
    """(original text, value) for every number in the text. Signs are ignored: only magnitudes are compared."""
    found = []
    for match in re.finditer(r"\d[\d,]*(?:\.\d+)?", _strip_non_claims(text)):
        token = match.group(0).rstrip(",")
        try:
            found.append((token, float(token.replace(",", ""))))
        except ValueError:
            pass
    return found


def _walk(data, out: list) -> None:
    if isinstance(data, bool) or data is None:
        return
    if isinstance(data, (int, float)):
        out.append(abs(float(data)))
    elif isinstance(data, str):
        out.extend(value for _, value in _numbers(data))
    elif isinstance(data, dict):
        for value in data.values():
            _walk(value, out)
    elif isinstance(data, (list, tuple)):
        for value in data:
            _walk(value, out)


def allowed_numbers(facts: dict) -> list:
    """Every number in the facts and the app rules, plus the ways a writer may round it (whole number, one decimal)."""
    base = []
    _walk(facts, base)
    _walk(APP_RULES, base)
    base.append(float(date.fromisoformat(facts["market_date"]).year))
    allowed = set()
    for a in base:
        allowed.update({a, float(round(a)), float(math.floor(a)), round(a, 1), round(a, 2)})
    return sorted(allowed)


def find_unsupported_numbers(text: str, facts: dict) -> list:
    """Numbers in the text that are not in the facts (in the order they appear, each once)."""
    allowed = allowed_numbers(facts)
    bad = []
    for token, value in _numbers(text):
        if not any(abs(value - a) < 0.0051 for a in allowed) and token not in bad:
            bad.append(token)
    return bad


# ------------------------------------------------------------------------------ the other checks
def check_draft(draft: dict, facts: dict, kind: str) -> list:
    """Plain-words problems with a draft (an empty list means it passed)."""
    problems = []
    title, meta, body = draft.get("title", "").strip(), draft.get("meta_description", "").strip(), draft.get("body_markdown", "").strip()
    if not title or len(title) > 70:
        problems.append(f"the title must be 1 to 70 characters (it is {len(title)}): make it shorter, for example drop the amount or a filler word")
    if not meta or len(meta) > 160:
        problems.append(f"the meta description must be 1 to 160 characters (it is {len(meta)})")
    low, (least, most) = body.lower(), LENGTH[kind]
    words = len(body.split())
    if not least <= words <= most:
        problems.append(f"the text has {words} words; a {kind} post should have {least} to {most}")
    if not any(w in body.split("\n\n")[0].lower() for w in ("simulat", "paper", "fake money")):
        problems.append("the first paragraph must say that the trades are simulated with fake money")
    if not re.match(r"\s*(I|My)\b", body):
        problems.append("the first paragraph must start with 'I' or 'My' (see rule 3)")
    if "|" in body:
        problems.append("do not include tables: the tables are added by code")
    for phrase in HEDGES:
        if phrase in low:
            problems.append(f"remove '{phrase}': no hedging or self-doubt in the text (the fixed notice at the bottom covers the disclaimer)")
    if any(facts["market_date"] < start for start, _ in RULE_CHANGES):
        for phrase in UNCHANGED_CLAIMS:
            if phrase in low:
                problems.append(f"remove '{phrase}': other things also change on the same date, so do not claim the sector limit is the only change (see RULE CHANGES)")
                break
    for phrase in JARGON:
        if phrase in low:
            problems.append(f"remove '{phrase}': it is an internal name of the app that readers cannot know; say it in plain everyday words (see rule 9)")
    for sentence in re.split(r"(?<=[.!?])\s+", body):
        sl = sentence.lower()
        if "reward" in sl and any(w in sl for w in ("lower", "loosen", "relax", "adjust", "reduc", "ease", "slightly")):
            problems.append("do not propose changing the reward-to-risk threshold: the facts do not show how the rejected trades would have done (rule 7); "
                            "pick another idea from the facts")
            break
    snake = sorted(set(re.findall(r"\b[a-z]+(?:_[a-z]+)+\b", body)))
    if snake:
        problems.append("replace these code-style names with plain words: " + ", ".join(snake))
    for phrase in BANNED:
        if phrase in low:
            problems.append(f"remove the phrase '{phrase}': no advice, predictions or guarantees")
    for phrase in FEELINGS:
        if phrase in low:
            problems.append(f"remove '{phrase}': the bot has no recorded feelings or intentions; describe rules and recorded reasons")
    bad = find_unsupported_numbers(" ".join([title, meta, body]), facts)
    if bad:
        problems.append("these numbers are not in the facts (use only numbers from the facts, never add, average or estimate): " + ", ".join(bad))
    return problems


def refusal_reason(facts: dict, kind: str):
    """Why there is nothing to write yet (or None)."""
    if kind == "daily":
        if facts["day_status"] not in ("traded", "no_trades"):
            return f"nothing to write: the day's status is '{facts['day_status']}'"
    elif not facts["complete"]:
        return "the week is incomplete, fix this first: " + "; ".join(facts["warnings"])
    return None


# ------------------------------------------------------------------------------ the tables (code, never the model)
def _inr(x, sign: bool = False) -> str:
    if x is None:
        return "n/a"
    text = f"{abs(x):,.2f}"
    return f"−₹{text}" if x < 0 else (f"+₹{text}" if sign else f"₹{text}")


def _pct(x, sign: bool = True) -> str:
    return "n/a" if x is None else (f"{x:+.2f}%" if sign else f"{x:.2f}%").replace("-", "−")


OUTCOME_WORDS = {"target_hit": "target hit", "stop_hit": "stop hit", "closed_at_end": "sold at the 3:15 PM close"}
SETUP_WORDS = {"earnings": "earnings", "broker_call": "broker target change", "broker_target": "broker target change", "order_win": "order win",
               "regulatory_approval": "regulatory approval", "deal_or_acquisition": "deal or acquisition", "block_deal": "block deal",
               "dividend": "dividend", "product_or_partnership": "product or partnership", "management_change": "management change",
               "sector_news": "sector news", "sector_or_market_move": "sector news", "other": "general news", "unknown": "general news"}


def setup_word(raw) -> str:
    return SETUP_WORDS.get(raw or "unknown", str(raw).replace("_", " "))


# Words of the app that must not reach the model: a reader of the blog cannot know them.
HIDDEN_KEYS = {"mode", "analyst_mode", "analyst_mode_by_day", "analyst_modes", "event_status", "on_watchlist"}


LABEL_AFTER = "rated strong, but dropped because another stock from the same sector was already chosen"


def writer_view(data, after_change: bool = False):
    """A copy of the facts for the model: app-internal fields removed, setup names in plain words."""
    if isinstance(data, dict):
        out = {}
        for key, value in data.items():
            if key in HIDDEN_KEYS:
                continue
            if key in ("event_type", "setup", "catalyst_type") and isinstance(value, str):
                value = setup_word(value)
            out[SETUP_WORDS.get(key, key)] = ((LABEL_AFTER if after_change else LABEL_PLAIN.get(value, value)) if key == "label" and value in LABEL_PLAIN else writer_view(value, after_change))
        return out
    if isinstance(data, list):
        return [writer_view(v, after_change) for v in data]
    return data


def daily_tables(facts: dict) -> str:
    if not facts["trades"]:
        return ""
    rows = ["| Stock | News catalyst | Result | Exit (IST) | Gross P&L | R |", "|---|---|---|---|---:|---:|"]
    for t in facts["trades"]:
        r = t["result"]
        if r is None:
            rows.append(f"| {t['symbol']} | {setup_word((t['analyst'] or {}).get('event_type'))} | no result yet | | | |")
            continue
        rows.append(f"| {t['symbol']} | {setup_word((t['analyst'] or {}).get('event_type'))} | {OUTCOME_WORDS.get(r['outcome'], r['outcome'])} "
                    f"| {'15:15' if r['outcome'] == 'closed_at_end' else (r['exit_time_ist'] or '')} | {_inr(r['pnl'], True)} | {'n/a' if r['r_multiple'] is None else format(r['r_multiple'], '+.2f').replace('-', '−')}R |")
    m = facts["money"]
    foot = ""
    if m:
        foot = (f"\n\n**Day total (gross):** {_inr(m['pnl'], True)} ({_pct(m['pnl_pct_of_start'])} of the starting balance). "
                f"Nifty 50 over the same window: {_pct(m['nifty_move_pct'])}.")
    return "\n".join(rows) + foot


def weekly_tables(facts: dict) -> str:
    days = ["| Day | Trades | Won / lost | Gross P&L | Nifty (same window) |", "|---|---:|---:|---:|---:|"]
    for d in facts["days"]:
        label = f"{d['weekday'][:3]} {int(d['date'][8:])} {date.fromisoformat(d['date']).strftime('%b')}"
        if d["pnl_gross"] is None:
            days.append(f"| {label} | – | – | {d['status'].replace('_', ' ')}{' (' + d['note'] + ')' if d['note'] else ''} | – |")
        else:
            days.append(f"| {label} | {d['trades']} | {d['winners']} / {d['losers']} | {_inr(d['pnl_gross'], True)} | {_pct(d['nifty_move_pct'])} |")
    w, c = facts["week"], facts["cumulative"]
    def col(p):
        e, t = p["equity"], p["trades"]
        if e is None:
            return ["n/a"] * 9
        return [_inr(e["starting_balance"]), _inr(e["ending_balance"]), _inr(e["pnl_gross"], True), _pct(e["return_pct"]),
                str(t["trades"]), "n/a" if t["win_rate_pct"] is None else f"{t['win_rate_pct']:.1f}%",
                "n/a" if t["profit_factor"] is None else f"{t['profit_factor']:.2f}",
                _inr(t["expectancy_per_trade"], True) if t["expectancy_per_trade"] is not None else "n/a",
                f"{e['max_drawdown_pct']:.2f}% ({_inr(e['max_drawdown_rs'])})"]
    names = ["Starting balance", "Ending balance", "Gross P&L", "Return on starting balance", "Completed trades", "Win rate",
             "Profit factor", "Average gross P&L per trade", "Maximum drawdown (end-of-day balances)"]
    stats = ["| Measure | This week | Since the start |", "|---|---:|---:|"]
    stats += [f"| {n} | {a} | {b} |" for n, a, b in zip(names, col(w), col(c))]
    return "\n".join(days) + "\n\n" + "\n".join(stats)


MEASURED_DAILY = ["**Gross:** before brokerage, taxes and slippage, which are not modelled yet.",
                  "**R:** profit or loss divided by the amount risked at the stop-loss (a stop-loss hit is −1.00R).",
                  "**Exit time:** the 5-minute candle in which the stop-loss or target was touched; trades that touched neither are sold at the 3:15 PM close.",
                  "**Nifty 50:** price index, from the moment the bot starts (about 09:35 IST) to 15:15 IST. The bot's percentage is on its whole starting balance, "
                  "so the two are not like-for-like."]
MEASURED_WEEKLY = [MEASURED_DAILY[0],
                   "**Win rate:** the share of trades that ended in a profit; a trade that ended flat does not count as a win.",
                   "**Profit factor:** total gross profit divided by total gross loss.",
                   MEASURED_DAILY[1],
                   "**Maximum drawdown:** the biggest fall from a peak, using end-of-day balances only. It does not capture swings inside a day.",
                   "**Nifty 50:** price index, from the moment the bot starts (about 09:35 IST) to 15:15 IST each day. The bot's percentage is on its whole starting "
                   "balance, so the two are not like-for-like.",
                   "**Return to the close** (used for stocks the bot did not buy): the price move from the bot's start to the last close before 15:15, "
                   "as if the stock had been bought then and held."]


def measured_notes(kind: str) -> str:
    return "**How these numbers are measured**\n\n" + "\n".join(f"- {n}" for n in (MEASURED_DAILY if kind == "daily" else MEASURED_WEEKLY))


def assemble(body: str, facts: dict, kind: str) -> str:
    """The writer's first paragraph, the code-built tables, the rest of the writer's text, then the fixed disclosure."""
    tables = daily_tables(facts) if kind == "daily" else weekly_tables(facts)
    first, _, rest = body.strip().partition("\n\n")
    parts = [first, tables, rest, measured_notes(kind), "---", DISCLOSURE]
    return "\n\n".join(p for p in parts if p)


# ------------------------------------------------------------------------------ the prompt
COMMON_RULES = """RULES
1. NUMBERS. Use only numbers that appear in the FACTS or in APP RULES. Never add, subtract, average, convert, or estimate one. Copy numbers exactly
   (rounding to a whole number is fine). If you want a number that is not there, say it in words or leave it out. Write money as ₹ with thousands
   separators and two decimals (₹1,039.35) and percentages as in the tables (0.63%). Tables with the main figures are added by code after your
   first paragraph, so do NOT write tables and do not repeat every figure; bring the figures to life.
2. P&L is GROSS (before brokerage, taxes and slippage). Say "gross" the first time you mention profit or loss.
3. OPENING. The first paragraph must start with "I" or "My" and announce, with confidence and flair, that you built a trading bot that executes simulated
   trades with fake money on the NSE (vary the wording from post to post; for example "I built an AI-powered trading bot that executes simulated trades on the NSE with fake money, and this
   week it ..."), then give the gross result in a sentence or two. Do not hedge in the opening, and never say that results "prove nothing"
   or that you "want to be clear" about anything: the fixed notice at the bottom of the page already covers that.
4. VOICE: A confident, polished builder proud of the engineering: risk rules enforced by code, an AI model that only reads and suggests while code decides, every
   decision recorded and auditable, a post-mortem after every session. Write vividly, with strong verbs, good rhythm and engaging (but factual) section
   headings. No hype words (amazing, incredible, game-changing), no emojis, no self-deprecation. You are "I", the person who built it. Do not mention any
   job, employer, city, age or background. Call the program "my bot" or "the bot".
5. FACTS VS STORY. You may explain why the bot bought a stock ONLY from the analyst's recorded reason and the cited headlines. Why a stock moved, or what any
   person or the bot "thought" or "felt", is not recorded: do not invent it. Describe rules and recorded reasons.
6. NO ADVICE, NO CLAIMS. No predictions, no "you should", no recommendations. Never claim that the results show skill, prove the strategy works, or beat the
   market; state what happened and what the numbers are. Losses and stops are part of the story, told matter-of-factly: a stop-loss that fired is the risk
   rules doing their job.
7. IMPROVEMENT. The last section proposes exactly ONE change to test, framed as an experiment the builder will run (never as a fix that will work). Choose the
   issue with the largest effect shown in the facts: for example stocks from one sector held together and stopped out together (use same_sector_days / same_sector_pnl,
   which give the rupee impact), or a pattern in app_behaviour, ahead of small threshold tweaks. Do NOT suggest changing the reward-to-risk threshold or any other risk rule unless the facts show how the
   rejected trades actually did. If there is no sector overlap, pick a different measurable idea that the facts support (for example stops that hit
   within an hour, trades sold at the 3:15 PM close, or which kind of news produced the winners) and say what would be measured. Where the facts give a
   count, copy it; never work out a count yourself (for example "others that were not traded") and never round a total to "over ₹1,000". Name the number that motivates the idea and say how it would be measured. Obey RULE CHANGES: never describe a rule as existing before its start date.
   Do not say why candidates were dropped or skipped unless the facts give the reason.
8. OUTPUT. A title (aim for 55 to 60 characters, never more than 70: short beats clever, specific and engaging, with the date written in words such as "9 October 2026" and the words "NSE" and "trading bot"; a weekly title names the whole week, such as "week of 5 to 9 October 2026", never a single day),
   a meta_description (one plain sentence, at most 155 characters, no hype), and the body in markdown with ## headings. No title line inside the body.
9. PLAIN WORDS. Readers know nothing about the app's insides. Never use its internal names: no "classic" or "checklist" mode, "analyst mode", "planner", "watchlist",
   "nudged", "overruled", "event type", "square-off", and no code-style names with underscores. Say what happens in everyday words instead: an AI model reads the morning
   headlines and rates each candidate stock; code then checks the rating and decides which trades are allowed. Never say which version or mode of the AI step ran.
   Say "stop-loss" and "target" (explain once: the price at which the bot gives up on a trade, and the price at which it takes profit), and "closed at the 3:15 PM
   close" for trades sold at the end of the session.
10. NO CONCLUSIONS FROM TINY DATA. Report the numbers; do not say they show that the bot's rules or the AI "work", "predict" or "add value".
11. NEWS, NOT CHART SIGNALS. The labels like "earnings" or "broker target change" are the kind of NEWS that made the AI rate a stock strong; call them "news catalysts",
   never "setups" or "strategies". The bot has no chart-based entry signal: it buys at a fixed time after the news check, with a stop-loss and target set by rules.
   Say that if you explain why a trade was made, and never invent a technical reason. If a reason is not in the facts, say it was not recorded.
12. KEEP COUNTS SIMPLE. The only funnel to describe is: stocks screened, how many passed the screen, the top candidates read by the AI (at most 10 a day), how many it rated
   strong, then how many trades the rules allowed or turned down. Use only the counts that explain a decision; skip the rest. Do not call a stock "watched" or "considered".
13. CAUSE AND SAMPLE. Do not say that something caused the result (for example that sector overlap "caused" the losses): say it coincided with them and that you will test
   it. The experiment is a hypothesis with what will be compared against what, and what stays unchanged. Say once, in the numbers section, that this is one week of data.
"""

STRUCTURES = {
    "daily": """STRUCTURE (about 250 to 400 words)
First paragraph: the opening described in rule 3, with the day's gross result. (The table follows it automatically.)
## How the market moved: the Nifty move given in the facts next to the bot's own result; say in half a sentence that they are measured differently (the bot on its whole
   balance, the Nifty over the same time window). No other market commentary: Bank Nifty and breadth are not recorded.
## The trades: each trade in a sentence or two: why the bot bought (the recorded reason and cited headline), and how it ended (target, stop or the 3:15 PM close).
## How the bot behaved: from "app_behaviour" (headlines, how many candidates the AI rated strong, how many trades the rules allowed or turned down and why, stops that hit within an hour, stocks from one sector held
   together). Use plain words only (rule 9).
## An idea to test: exactly one candidate idea, as a hypothesis (rule 7 and 13). The weekly post picks the one experiment that is actually run.""",
    "weekly": """STRUCTURE (about 550 to 800 words)
First paragraph: the opening described in rule 3, with the week's gross result. (The tables follow it automatically.)
## The market backdrop: the days' Nifty moves from the facts next to the bot's results (measured differently: the bot on its whole balance).
## Best and toughest trade: the best and the worst trade of the week, using best_trade / worst_trade and their recorded reasons. If the worst was still a win, say so.
## What the numbers say: win rate, profit factor, average R, drawdown, exits, setups, and the report card (for the report card, mention only three groups: bought, strong but not bought, and no catalyst; give their average move from the bot's start to the close as plain numbers,
   in one short paragraph, and say it is a comparison of price moves, not of the bot's trades. Skip the other groups). Present the news catalysts as "by kind of news".
   Never mix "this week" with "since the start".
## How the bot behaved: from "app_behaviour" (headlines, how many candidates the AI rated strong, how many trades the rules allowed or turned down and why, stops that hit within an hour, sector overlaps).
## The experiment for next week: one hypothesis, as described in rule 7: the observed issue with its number, the proposed change, how it will be measured, and what stays unchanged.""",
}


def rule_notes(facts: dict) -> str:
    when = facts["market_date"]
    lines = []
    for start, text in RULE_CHANGES:
        lines.append(text + (" This post is about a period BEFORE that date: never say the limit exists or applied. If you propose it, say it starts on that date and "
                             "that the experiment is to compare results afterwards." if when < start else
                             " This post is dated on or after that date: the limit is ALREADY in force, so never propose it as a future experiment. "
                                                  "Report how it behaved (for example stocks dropped because of it) and propose a different idea."))
    return "\n".join(lines)


def build_prompt(facts: dict, kind: str) -> str:
    return (f"You write a {kind} post for a public blog that follows a paper-trading experiment: a program (\"the bot\") that screens Indian (NSE) stocks, "
            f"reads news headlines with an AI model, and trades with FAKE money under strict code-enforced risk rules.\n\n"
            f"APP RULES (fixed; you may mention these numbers):\n{json.dumps(APP_RULES)}\nRULE CHANGES:\n{rule_notes(facts)}\n\n"
            f"FACTS (JSON; the only source of truth. Field notes: pnl and pnl_gross are gross; r_multiple = P&L divided by the loss risked at the stop; "
            f"'others' are candidates the bot did not buy; report_card compares groups of candidates until the close; not_recorded lists what the app does not record):\n"
            f"{json.dumps(writer_view(facts, facts["market_date"] >= RULE_CHANGES[0][0]), ensure_ascii=False)}\n\n{COMMON_RULES}\n\n{STRUCTURES[kind]}")


# ------------------------------------------------------------------------------ writing
def write_post(facts: dict, generate, kind: str, max_tries: int = 2) -> dict:
    """generate(prompt) -> {'title', 'meta_description', 'body_markdown'}. Returns the assembled post and any remaining problems."""
    result = {"kind": kind, "market_date": facts["market_date"], "title": None, "meta_description": None, "body_markdown": None,
              "writer_text": None, "problems": [], "tries": 0, "refused": None, "ok": False}
    refused = refusal_reason(facts, kind)
    if refused:
        result["refused"] = refused
        return result
    prompt = build_prompt(facts, kind)
    draft, problems = None, []
    for attempt in range(1, max_tries + 1):
        result["tries"] = attempt
        full_prompt = prompt if attempt == 1 else (prompt + "\n\nYOUR PREVIOUS DRAFT HAD THESE PROBLEMS. Write the whole post again and fix every one:\n- "
                                                   + "\n- ".join(problems))
        try:
            draft = generate(full_prompt)
        except Exception as error:                            # a model or network failure must not crash the job
            problems = [f"the model call failed: {error}"]
            break
        problems = check_draft(draft, facts, kind)
        if not problems:
            break
    result["problems"] = problems
    result["ok"] = not problems
    if draft:
        result.update({"title": draft["title"].strip(), "meta_description": draft["meta_description"].strip(),
                       "writer_text": draft["body_markdown"].strip(), "body_markdown": assemble(draft["body_markdown"], facts, kind)})
    return result


def make_generate(llm):
    """Wrap a LangChain chat model: prompt in, {'title', 'meta_description', 'body_markdown'} out."""
    writer = llm.with_structured_output(Post)

    def generate(prompt: str) -> dict:
        answer = writer.invoke(prompt)
        return {"title": answer.title, "meta_description": answer.meta_description, "body_markdown": answer.body_markdown}
    return generate


# ------------------------------------------------------------------------------ command line
def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in ("daily", "weekly"):
        raise SystemExit("Usage: python blog_writer.py daily|weekly YYYY-MM-DD   (weekly: any date inside the week)")
    kind, when = sys.argv[1], date.fromisoformat(sys.argv[2])
    if kind == "daily":
        from blog_facts import collect_day_facts
        facts = collect_day_facts(when)
    else:
        from blog_weekly import collect_week_facts
        facts = collect_week_facts(when)
    from llm_setup import MODEL, PROVIDER, build_llm
    post = write_post(facts, make_generate(build_llm()), kind)
    if post["refused"]:
        raise SystemExit("Not written: " + post["refused"])
    path = f"blog_draft_{kind}_{post['market_date']}.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"<!-- model: {PROVIDER}:{MODEL}; tries: {post['tries']}; passed all checks: {post['ok']} -->\n"
                + "".join(f"<!-- PROBLEM: {q} -->\n" for q in post["problems"]) +
                f"<!-- meta description: {post['meta_description']} -->\n\n# {post['title']}\n\n{post['body_markdown']}\n")
    print(f"Draft saved to {path}  ({len(post['writer_text'].split())} words of text, {post['tries']} attempt(s))")
    print("PASSED all checks" if post["ok"] else "NEEDS A CLOSE LOOK. Problems:\n- " + "\n- ".join(post["problems"]))


if __name__ == "__main__":
    main()
