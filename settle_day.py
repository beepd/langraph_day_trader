"""
End-of-day settlement. For the day's accepted plans, find out whether the stop or the target was hit,
save the results, and update the balance.

Run it after 3:30 PM IST:        python settle_day.py
Or for an earlier trading day:   python settle_day.py 2026-10-05
It is safe to run twice: plans that already have a result are not settled again.
"""
import os
import sys
from datetime import date, datetime, timedelta, timezone

import yfinance as yf
from dotenv import load_dotenv

import messages as msg
from notify import send_telegram
from rules import STARTING_BALANCE
from settlement import (benchmark_move, candles_after, group_summary, outcomes_for_candidates, settle)
from storage import get_candidates, get_client, get_watchlist_symbols, save_candidate_outcomes

load_dotenv()
IST = timezone(timedelta(hours=5, minutes=30))
FORCE_SETTLE = os.getenv("FORCE_SETTLE", "").strip().lower() in {"1", "true", "yes"}   # testing: allow before 3:35 PM


def next_candle_start(moment: datetime) -> datetime:
    """The first full 5-minute candle after we bought. A buy at 09:36 is first affected by the 09:40 candle."""
    minutes = (moment.hour * 60 + moment.minute) // 5 * 5
    boundary = moment.replace(hour=minutes // 60, minute=minutes % 60, second=0, microsecond=0)
    return boundary if boundary == moment else boundary + timedelta(minutes=5)


def nifty_benchmark(started_at: datetime, market_date: date):
    """How far the Nifty index moved over the same window our trades were open (None if Yahoo has no data)."""
    try:
        history = yf.Ticker("^NSEI").history(period="5d", interval="5m")
        history = history[history.index.date == market_date]
        return benchmark_move(history, started_at)
    except Exception as error:
        print(f"   (could not work out the Nifty benchmark: {error})")
        return None


def record_report_card(run_id: int, market_date: date, started_at: datetime, period: str = "5d"):
    """
    Grade EVERY candidate of the run, not only the stocks we bought: fetch their 5-minute candles, work out how each
    did until the close, save it, and return a one-line summary for Telegram (or None).
    """
    candidates = get_candidates(run_id)
    if not candidates:
        print("Report card: this run has no candidates.")
        return None
    symbols = [c["symbol"] for c in candidates]
    data = yf.download([s + ".NS" for s in symbols], period=period, interval="5m",
                       group_by="ticker", auto_adjust=False, progress=False)
    available = set(data.columns.get_level_values(0)) if not data.empty else set()
    start = next_candle_start(started_at)
    candles_by_symbol = {}
    for symbol in symbols:
        if symbol + ".NS" in available:
            frame = data[symbol + ".NS"].dropna(subset=["Close"])
            candles_by_symbol[symbol] = candles_after(frame[frame.index.date == market_date], start)
    reports = outcomes_for_candidates(candidates, candles_by_symbol)
    saved = save_candidate_outcomes(run_id, reports)
    missing = [s for s in symbols if s not in reports]
    print(f"Report card: saved {saved} of {len(symbols)} candidates" + (f" (no data for: {', '.join(missing)})" if missing else ""))
    return msg.report_card(group_summary(reports, get_watchlist_symbols(run_id)))


def main() -> None:
    now = datetime.now(IST)
    market_date = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else now.date()
    print(f"Settling {market_date} (time now {now:%H:%M} IST)")

    if market_date == now.date() and now.time() < datetime(2000, 1, 1, 15, 35).time() and not FORCE_SETTLE:
        raise SystemExit("The market is still open, so the day is not finished. Run this after 3:35 PM IST "
                         "(or set FORCE_SETTLE=1 to test).")

    client = get_client()

    # 1. The day's run: the latest finished run that used live data
    runs = (client.table("runs").select("id, started_at, settings")
            .eq("market_date", market_date.isoformat()).eq("status", "finished").eq("data_is_live", True)
            .order("id", desc=True).limit(1).execute().data)
    if not runs:
        print("No finished run with live data for that date (market holiday?), so there is nothing to settle.")
        send_telegram(msg.nothing_to_settle(market_date))
        return
    run = runs[0]
    started_at = datetime.fromisoformat(run["started_at"]).astimezone(IST)
    start_balance = float((run["settings"] or {}).get("balance_at_start", STARTING_BALANCE))
    print(f"Run #{run['id']}, started {started_at:%H:%M}, balance at start {start_balance:,.2f}")

    # 2. Its accepted plans, and which of them already have a result
    plans = (client.table("plans").select("*").eq("run_id", run["id"]).eq("status", "accepted")
             .execute().data)
    plan_ids = [p["id"] for p in plans]
    done = set()
    if plan_ids:
        done = {r["plan_id"] for r in
                client.table("trade_results").select("plan_id").in_("plan_id", plan_ids).execute().data}
    todo = [p for p in plans if p["id"] not in done]
    print(f"{len(plans)} accepted plan(s), {len(done)} already settled, {len(todo)} to settle")

    # 3. Settle each remaining plan on the day's 5-minute candles
    problems = 0
    if todo:
        symbols = [p["symbol"] for p in todo]
        data = yf.download([s + ".NS" for s in symbols], period="5d", interval="5m",
                           group_by="ticker", auto_adjust=False, progress=False)
        available = set(data.columns.get_level_values(0)) if not data.empty else set()
        start = next_candle_start(started_at)
        print(f"Checking candles from {start:%H:%M} to the 3:15 PM square-off")
        for plan in todo:
            symbol = plan["symbol"]
            if symbol + ".NS" not in available:
                print(f"   {symbol}: no candle data from Yahoo, cannot settle")
                problems += 1
                continue
            frame = data[symbol + ".NS"].dropna(subset=["Close"])
            frame = frame[frame.index.date == market_date]
            candles = candles_after(frame, start)
            if not candles:
                print(f"   {symbol}: no candles for {market_date} after {start:%H:%M}, cannot settle")
                problems += 1
                continue
            result = settle(float(plan["entry"]), float(plan["stop"]), float(plan["target"]), plan["shares"], candles)
            client.table("trade_results").insert({
                "plan_id": plan["id"], "outcome": result["outcome"], "exit_price": result["exit_price"],
                "exit_time": result["exit_time"].isoformat(), "pnl": result["pnl"],
            }).execute()
            print(f"   {symbol}: bought {plan['shares']} @ {float(plan['entry']):.2f} (stop {float(plan['stop']):.2f}, "
                  f"target {float(plan['target']):.2f}) -> {result['outcome']} at {result['exit_price']:.2f} "
                  f"({result['exit_time']:%H:%M}), P&L {result['pnl']:+,.2f}")

    if problems:
        send_telegram(msg.settlement_incomplete(problems))
        raise SystemExit(f"\n{problems} plan(s) could not be settled, so the day's balance was NOT updated. "
                         "Fix the problem and run this again.")

    # 4. The day's totals, from every saved result (so running twice gives the same answer)
    results = []
    if plan_ids:
        results = client.table("trade_results").select("plan_id, outcome, pnl").in_("plan_id", plan_ids).execute().data
    total = round(sum(float(r["pnl"]) for r in results), 2)
    benchmark = nifty_benchmark(started_at, market_date)
    capital_used = round(sum(float(p.get("cost") or 0) for p in plans), 2)
    row = {"market_date": market_date.isoformat(), "starting_balance": round(start_balance, 2),
           "ending_balance": round(start_balance + total, 2), "pnl": total, "trades": len(results),
           "benchmark_pct": None if benchmark is None else round(benchmark, 2), "capital_used": capital_used}
    client.table("daily_equity").upsert(row, on_conflict="market_date").execute()
    print(f"\nDay result: {len(results)} trade(s), P&L {total:+,.2f}")
    print(f"Balance: {start_balance:,.2f} -> {row['ending_balance']:,.2f}  (saved to daily_equity)")
    print(f"Money used: {capital_used:,.0f}; Nifty over the same window: "
          f"{'unknown' if benchmark is None else f'{benchmark:+.2f}%'}")
    report_line = None
    try:                                  # the balance is already saved: a problem here must never undo or block it
        report_line = record_report_card(run["id"], market_date, started_at)
    except Exception as error:
        print(f"   (could not record the report card: {error})")
    symbol_of = {p["id"]: p["symbol"] for p in plans}
    rows = [(symbol_of.get(r["plan_id"], "?"), r["outcome"], float(r["pnl"])) for r in results]
    send_telegram(msg.settlement(market_date, rows, total, start_balance, row["ending_balance"], benchmark, capital_used, report_line))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:                                 # SystemExit (planned stops) is not caught here
        send_telegram(msg.crash("Settlement", error))
        raise
