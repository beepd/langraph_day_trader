"""
7b, stage 1: the checklist analyst's decision logic. NOT used by the live run yet.

The idea, in plain words: today the language model fills in one field, "strength", and we trust it. Here the model
only answers plain factual questions (what kind of event is it? has it happened or is it only expected? ...), and
THIS file decides "strong" with fixed rules. LLM judges facts, code decides.

A stock is "strong" only if ALL of these are true:
    1. its event type is one that can be strong (earnings, order win, approval, deal, named-broker target)
    2. the event has already happened (not "expected", not a rumour or an opinion)
    3. the news is bullish
    4. a cited headline names the company, and that same headline is at most FRESH_DAYS old (code reads its date)

Then a sector rule: of the strong stocks, keep at most MAX_PER_SECTOR per sector, in screener-rank order.

Nothing here talks to a network, a database or a language model, so all of it can be tested offline.
"""
import csv
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field

IST = timezone(timedelta(hours=5, minutes=30))
FRESH_DAYS = 3             # a headline this many days old (or newer) counts as fresh; the same window as the prompt
MAX_PER_SECTOR = 1         # strong stocks kept per sector (a sector is our stand-in for "one story")

EventType = Literal[
    "earnings", "order_win", "regulatory_approval", "deal_or_acquisition", "broker_target",       # can be strong
    "block_deal", "dividend", "product_or_partnership", "management_change", "sector_or_market_move", "other",
]
Status = Literal["happened", "expected", "rumour_or_opinion"]

STRONG_EVENT_TYPES = {"earnings", "order_win", "regulatory_approval", "deal_or_acquisition", "broker_target"}


class Checklist(BaseModel):
    """The form the language model fills in for ONE stock. Only facts; the decision is made in code."""
    event_type: EventType = Field(description=(
        "What kind of event do the cited headlines report? Pick the closest one. "
        "If they show no specific event for this company, use 'other'."))
    status: Status = Field(description=(
        "happened = the event has already taken place or been officially announced (results published, order awarded, "
        "target raised). expected = scheduled or upcoming ('to announce', 'will report', 'ahead of results'). "
        "rumour_or_opinion = 'in talks', 'may', 'likely', or someone's view."))
    bullish: bool = Field(description="True only if the news points to upside for the share price today")
    has_number: bool = Field(description="True if a cited headline states a concrete figure (profit growth, order value, target price)")
    reason: str = Field(description="One or two sentences, based only on the headlines")
    source_numbers: list[int] = Field(description="Numbers of the headlines that support the answers, [] if none")


@dataclass
class Decision:
    strong: bool
    failed: list = field(default_factory=list)       # plain-words reasons, empty when strong


# ------------------------------------------------------------------------------ small helpers
def mentions_company(symbol: str, company: str, headline: str) -> bool:
    """Same logic as the function of the same name in morning_run.py (a test keeps the two identical)."""
    name = company.replace(" Ltd.", "").replace(" Limited", "")
    short_name = " ".join(name.split()[:2]).lower()          # first two words, e.g. "sbi life"
    text = headline.lower()
    return short_name in text or symbol.lower() in text


def headline_age_days(published_at, today: date):
    """Whole days (India time) between the headline's date and today. None when there is no usable date, or when it
    lies more than a day in the future (we do not trust it). One day of slack is allowed for time zones."""
    if not published_at:
        return None
    try:
        published = datetime.fromisoformat(published_at)
    except (TypeError, ValueError):
        return None
    if published.tzinfo is None:
        published = published.replace(tzinfo=IST)
    days = (today - published.astimezone(IST).date()).days
    return max(days, 0) if days >= -1 else None


def is_fresh(headline: dict, today: date) -> bool:
    age = headline_age_days(headline.get("published_at"), today)
    return age is not None and age <= FRESH_DAYS


def load_sectors(path: str = "nifty100.csv") -> dict:
    """symbol -> sector, from the Industry column of the Nifty 100 file."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        return {row["Symbol"].strip(): row["Industry"].strip() for row in csv.DictReader(f)}


# ------------------------------------------------------------------------------ the rules
def evaluate(symbol: str, company: str, answer: Checklist, headlines: list, today: date) -> Decision:
    """Is this stock strong? `headlines` is the numbered list the model saw (dicts with 'text' and 'published_at')."""
    failed = []
    if answer.event_type not in STRONG_EVENT_TYPES:
        failed.append(f"event type '{answer.event_type}' can never be strong")
    if answer.status != "happened":
        failed.append(f"status is '{answer.status}', not 'happened'")
    if not answer.bullish:
        failed.append("the news is not bullish")

    cited = [headlines[n - 1] for n in answer.source_numbers if 1 <= n <= len(headlines)]
    naming = [h for h in cited if mentions_company(symbol, company, h["text"])]
    if not naming:
        failed.append("no cited headline names the company")
    elif not any(is_fresh(h, today) for h in naming):
        failed.append(f"the cited headline is older than {FRESH_DAYS} days or has no date")
    return Decision(strong=not failed, failed=failed)


def apply_sector_cap(ranked_symbols: list, sectors: dict, max_per_sector: int = MAX_PER_SECTOR):
    """Keep at most `max_per_sector` stocks per sector, going down the list in rank order.
    Returns (kept, dropped). `dropped` holds (symbol, sector, the stock that was kept instead).
    A symbol with no known sector goes into one shared "?" group, so unknowns are capped too."""
    kept, dropped, counts, first_kept = [], [], {}, {}
    for symbol in ranked_symbols:
        sector = sectors.get(symbol, "?")
        if counts.get(sector, 0) < max_per_sector:
            kept.append(symbol)
            counts[sector] = counts.get(sector, 0) + 1
            first_kept.setdefault(sector, symbol)
        else:
            dropped.append((symbol, sector, first_kept[sector]))
    return kept, dropped


def build_watchlist(order: list, answers: dict, headlines_by_symbol: dict, universe: dict, sectors: dict, today: date):
    """The whole thing for one morning. `order` is the screener's rank order; `answers` maps symbol -> Checklist
    (a stock with no answer, for example no headlines, is simply not strong).
    Returns (watchlist, decisions, dropped_by_sector_rule)."""
    decisions = {}
    for symbol in order:
        answer = answers.get(symbol)
        if answer is None:
            decisions[symbol] = Decision(strong=False, failed=["no checklist answer (for example, no headlines)"])
        else:
            decisions[symbol] = evaluate(symbol, universe.get(symbol, symbol), answer,
                                         headlines_by_symbol.get(symbol, []), today)
    strong = [s for s in order if decisions[s].strong]
    watchlist, dropped = apply_sector_cap(strong, sectors)
    return watchlist, decisions, dropped
