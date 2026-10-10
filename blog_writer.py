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

LENGTH = {"daily": (150, 520), "weekly": (400, 1150)}          # words in the writer's text (tables not counted)

BANNED = ["guarantee", "will rise", "will go up", "will surely", "sure to", "risk-free", "you should", "i recommend", "we recommend",
          "buy now", "must buy", "sure thing", "can't lose", "cannot lose"]
FEELINGS = ["felt", "excited", "nervous", "worried", "frustrated", "scared", "the bot thought", "the bot believed",
            "the bot wanted", "the bot hoped"]


class Post(BaseModel):
    title: str = Field(description="At most 70 characters. Plain, specific, includes the date or week and 'NSE paper trading'.")
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
        problems.append(f"the title must be 1 to 70 characters (it is {len(title)})")
    if not meta or len(meta) > 160:
        problems.append(f"the meta description must be 1 to 160 characters (it is {len(meta)})")
    low, (least, most) = body.lower(), LENGTH[kind]
    words = len(body.split())
    if not least <= words <= most:
        problems.append(f"the text has {words} words; a {kind} post should have {least} to {most}")
    if not any(w in low for w in ("simulat", "paper", "fake money")):
        problems.append("the text must say early that this is a simulation / paper trading with fake money")
    if "|" in body:
        problems.append("do not include tables: the tables are added by code")
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
    return "n/a" if x is None else (f"{x:+.2f}%" if sign else f"{x:.2f}%")


OUTCOME_WORDS = {"target_hit": "target hit", "stop_hit": "stop hit", "closed_at_end": "closed at the 3:15 PM square-off"}


def daily_tables(facts: dict) -> str:
    if not facts["trades"]:
        return ""
    rows = ["| Stock | Setup | Result | Exit (IST) | Gross P&L | R |", "|---|---|---|---|---:|---:|"]
    for t in facts["trades"]:
        r = t["result"]
        if r is None:
            rows.append(f"| {t['symbol']} | {(t['analyst'] or {}).get('event_type') or 'unknown'} | no result yet | | | |")
            continue
        rows.append(f"| {t['symbol']} | {(t['analyst'] or {}).get('event_type') or 'unknown'} | {OUTCOME_WORDS.get(r['outcome'], r['outcome'])} "
                    f"| {r['exit_time_ist'] or ''} | {_inr(r['pnl'], True)} | {'n/a' if r['r_multiple'] is None else format(r['r_multiple'], '+.2f')}R |")
    m = facts["money"]
    foot = ""
    if m:
        foot = (f"\n\n**Day total (gross):** {_inr(m['pnl'], True)} ({_pct(m['pnl_pct_of_start'])} of the starting balance). "
                f"Nifty over the same window: {_pct(m['nifty_move_pct'])}.")
    return "\n".join(rows) + foot


def weekly_tables(facts: dict) -> str:
    days = ["| Day | Trades | Won / lost | Gross P&L | Nifty (same window) |", "|---|---:|---:|---:|---:|"]
    for d in facts["days"]:
        label = f"{d['weekday'][:3]} {d['date'][5:]}"
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
    small = "\n\n*Small sample: treat these numbers as a first look, not a conclusion.*" if w["trades"]["small_sample"] else ""
    return "\n".join(days) + "\n\n" + "\n".join(stats) + small


def assemble(body: str, facts: dict, kind: str) -> str:
    """The writer's first paragraph, the code-built tables, the rest of the writer's text, then the fixed disclosure."""
    tables = daily_tables(facts) if kind == "daily" else weekly_tables(facts)
    first, _, rest = body.strip().partition("\n\n")
    parts = [first, tables, rest, "---", DISCLOSURE]
    return "\n\n".join(p for p in parts if p)


# ------------------------------------------------------------------------------ the prompt
COMMON_RULES = """RULES
1. NUMBERS. Use only numbers that appear in the FACTS or in APP RULES. Never add, subtract, average, convert, or estimate one. Copy numbers exactly
   (rounding to a whole number is fine). If you want a number that is not there, say it in words or leave it out. Tables with the main figures are
   added by code after your first paragraph, so do NOT write tables and do not repeat every figure; explain what the figures mean.
2. P&L is GROSS (before brokerage, taxes and slippage). Say "gross" the first time you mention profit or loss.
3. SIMULATION. This is paper trading with fake money. Say so in your first paragraph.
4. FACTS VS STORY. You may explain why the bot bought a stock ONLY from the analyst's recorded reason and the cited headlines. Why a stock moved,
   or what any person or the bot "thought" or "felt", is not recorded: do not invent it. Where something is not recorded, say "not recorded".
5. NO ADVICE. No predictions, no "you should", no recommendations, no promises. A few days of results prove nothing: say so plainly where it matters.
6. HONESTY. Cover losses and mistakes as fully as wins. Do not call a good result skill or a bad one bad luck unless the facts support it.
7. VOICE. You are "I", the person running the experiment. Do not mention any job, employer, city or background. Call the program "the bot".
   Plain, friendly English for a general reader, short paragraphs, no hype, no emojis, no jargon without a half-sentence explanation.
8. IMPROVEMENT. The section about what to test must propose exactly ONE change, based on a number in "app_behaviour" or in the results, and must call it
   an idea to test, never a fix that will work. Ground it in known_limitations where that fits. Do not invent problems the facts do not show.
9. OUTPUT. A title (at most 70 characters, plain and specific, with the date or week and "NSE paper trading"), a meta_description (one plain sentence,
   at most 155 characters), and the body in markdown with ## headings. No title line inside the body."""

STRUCTURES = {
    "daily": """STRUCTURE (about 250 to 400 words)
First paragraph: the day in one short paragraph, saying it is a simulation with fake money, and the gross result. (The table follows it automatically.)
## How the market moved: only the Nifty move given in the facts, compared plainly with the bot's own result. The bot's day is measured on its whole balance
   and the Nifty over the same time window, so say they are not like-for-like. No other market commentary: Bank Nifty and breadth are not recorded.
## The trades: each trade in a sentence or two: why the bot bought (the analyst's recorded reason and cited headline), and how it ended (target, stop or 3:15 close).
## How the app behaved: what worked and what looked weak, from "app_behaviour" (headlines, analyst strong/overruled counts, planner rejections and nudges,
   quick stops, stocks from one sector held together). Say which analyst mode ran.
## One idea to test next: exactly one, as described in rule 8.""",
    "weekly": """STRUCTURE (about 550 to 800 words)
First paragraph: the week in one short paragraph, saying it is a simulation with fake money, and the gross result. (The tables follow it automatically.)
## The market backdrop: the days' Nifty moves from the facts, compared plainly with the bot's results (not like-for-like: the bot is measured on its whole balance).
## Best and toughest trade: the best and the worst trade of the week, using best_trade / worst_trade and their recorded reasons. If the worst was still a win, say so.
## What the numbers say: win rate, profit factor, average R, drawdown, exits, setups, and the report card (did stocks with a catalyst do better than those without?).
   Where small_sample is true, say the sample is too small to conclude anything. Never mix "this week" with "since the start".
## How the app behaved: from "app_behaviour" (headlines, analyst strong/overruled counts, planner rejections and nudges, quick stops, sector overlaps, analyst mode by day).
## What I will test next week: one hypothesis. Give the observed issue (with its number), the proposed change, how it would be measured, and what must stay unchanged.""",
}


def build_prompt(facts: dict, kind: str) -> str:
    return (f"You write a {kind} post for a public blog that follows a paper-trading experiment: a program (\"the bot\") that screens Indian (NSE) stocks, "
            f"reads news headlines with an AI model, and trades with FAKE money under strict code-enforced risk rules.\n\n"
            f"APP RULES (fixed; you may mention these numbers):\n{json.dumps(APP_RULES)}\n\n"
            f"FACTS (JSON; the only source of truth. Field notes: pnl and pnl_gross are gross; r_multiple = P&L divided by the loss risked at the stop; "
            f"'others' are candidates the bot did not buy; report_card compares groups of candidates until the close; not_recorded lists what the app does not record):\n"
            f"{json.dumps(facts, ensure_ascii=False)}\n\n{COMMON_RULES}\n\n{STRUCTURES[kind]}")


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
                f"<!-- meta description: {post['meta_description']} -->\n\n# {post['title']}\n\n{post['body_markdown']}\n")
    print(f"Draft saved to {path}  ({len(post['writer_text'].split())} words of text, {post['tries']} attempt(s))")
    print("PASSED all checks" if post["ok"] else "NEEDS A CLOSE LOOK. Problems:\n- " + "\n- ".join(post["problems"]))


if __name__ == "__main__":
    main()
