"""The text of every Telegram message, in one place. These are plain functions: data in, text out."""
from notify import esc


def money(value: float) -> str:
    return f"₹{value:,.0f}"


def signed_money(value: float) -> str:
    return f"{'+' if value >= 0 else '−'}₹{abs(value):,.0f}"


def _short(text: str, limit: int = 110) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


# ---- morning run ---------------------------------------------------------------------------
def market_closed(why: str) -> str:
    return f"🔴 <b>Market closed</b>\n{esc(why[:1].upper() + why[1:])}. No trades today."


def balance_problem(error) -> str:
    return f"⚠️ <b>Run stopped</b>\nCould not read the balance from Supabase: {esc(str(error)[:200])}"


def run_started(now, balance: float, source: str, model: str) -> str:
    return (f"🟢 <b>Run started</b> {now:%a %d %b, %H:%M} IST\n"
            f"Balance {money(balance)} ({esc(source)})\nModel {esc(model)}")


def screener(passed: int, universe: int, top: list, live: bool) -> str:
    """top = list of (symbol, price, change_pct, rel_volume), best first."""
    if not top:
        return f"📊 <b>Screener</b>: nothing is moving enough (0 of {universe}). No trades today."
    lines = [f"📊 <b>Screener</b>: {passed} of {universe} stocks are moving"]
    for symbol, price, change, rel_volume in top[:5]:
        lines.append(f"• <b>{esc(symbol)}</b> {change:+.1f}% · volume x{rel_volume:.1f} · {money(price)}")
    if len(top) > 5:
        lines.append(f"…and {len(top) - 5} more go on to the news step")
    if not live:
        lines.append("⚠️ Data is from the last completed session, not today (testing only)")
    return "\n".join(lines)


def news(with_news: int, total: int, without: list) -> str:
    text = f"📰 <b>News</b>: headlines found for {with_news} of {total} movers"
    if without:
        text += f"\nNo headlines: {esc(', '.join(without[:6]))}"
    return text


def analyst(on_watchlist: list, total: int) -> str:
    """on_watchlist = list of (symbol, reason)."""
    if not on_watchlist:
        return f"🧠 <b>Analyst</b>: no strong catalyst among {total} movers. No trades today."
    lines = [f"🧠 <b>Analyst</b>: {len(on_watchlist)} strong catalyst(s) among {total} movers"]
    for symbol, reason in on_watchlist[:6]:
        lines.append(f"✅ <b>{esc(symbol)}</b>: {esc(_short(reason))}")
    if len(on_watchlist) > 6:
        lines.append(f"…and {len(on_watchlist) - 6} more")
    return "\n".join(lines)


def plans(accepted: list, rejected: list, skipped: list, balance: float) -> str:
    """accepted = plan dicts, rejected = list of (symbol, reason), skipped = list of symbols."""
    lines = [f"📝 <b>Trade plans</b> (balance {money(balance)})"]
    for p in accepted:
        lines.append(f"🟢 <b>{esc(p['symbol'])}</b>: buy {p['shares']} @ {p['entry']:.2f}")
        lines.append(f"    stop {p['stop']:.2f} · target {p['target']:.2f} · risk {money(p['max_loss'])} / reward {money(p['max_gain'])}")
    for symbol, reason in rejected:
        lines.append(f"✖ <b>{esc(symbol)}</b> rejected: {esc(_short(reason, 90))}")
    if skipped:
        lines.append(f"Skipped (position limit): {esc(', '.join(skipped))}")
    if not accepted:
        lines.append("No trades today.")
    return "\n".join(lines)


def run_complete(accepted: list, balance: float, run_id, save_error) -> str:
    if accepted:
        cost = sum(p["cost"] for p in accepted)
        worst = sum(p["max_loss"] for p in accepted)
        text = (f"✅ <b>Run complete</b>: {len(accepted)} trade(s) planned\n"
                f"Cash used {money(cost)} of {money(balance)} · worst case −{money(worst)}")
    else:
        text = "✅ <b>Run complete</b>: no trades today"
    if save_error:
        text += f"\n⚠️ Could not save to Supabase: {esc(str(save_error)[:150])}"
    else:
        text += f"\nSaved as run #{run_id}"
    return text


# ---- end-of-day settlement -------------------------------------------------------------------
def settlement(market_date, rows: list, total: float, start: float, end: float,
               benchmark_pct=None, capital_used=None) -> str:
    """rows = list of (symbol, outcome, pnl)."""
    lines = [f"📈 <b>Day settled</b> {market_date}"]
    for symbol, outcome, pnl in rows:
        lines.append(f"• <b>{esc(symbol)}</b>: {esc(outcome.replace('_', ' '))} · {signed_money(pnl)}")
    if not rows:
        lines.append("No trades were made that day.")
    lines.append(f"Day P&amp;L <b>{signed_money(total)}</b> · balance {money(start)} → {money(end)}")
    extras = []
    if capital_used:
        extras.append(f"return on the money used {total / capital_used * 100:+.2f}%")
    if benchmark_pct is not None:
        extras.append(f"Nifty over the same window {benchmark_pct:+.2f}%")
    if extras:
        lines.append(" · ".join(extras))
    return "\n".join(lines)


def nothing_to_settle(market_date) -> str:
    return f"ℹ️ <b>Settlement</b> {market_date}: no live run to settle (market holiday?)"


def settlement_incomplete(problems: int) -> str:
    return f"⚠️ <b>Settlement incomplete</b>: {problems} plan(s) could not be settled, so the balance was NOT updated."


# ---- failures ------------------------------------------------------------------------------
def crash(job: str, error) -> str:
    return f"❌ <b>{esc(job)} crashed</b>\n<code>{esc(type(error).__name__)}: {esc(str(error)[:300])}</code>"


def gave_up(job: str, attempts: int, outcome: str) -> str:
    return f"❌ <b>{esc(job)}</b> gave up after {attempts} attempt(s): {esc(outcome)}. See the log files."