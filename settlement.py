import math
from datetime import time as dtime
from datetime import timedelta

SQUARE_OFF = dtime(15, 15)       # brokers close intraday positions around here


def _result(outcome, exit_price, exit_time, entry, shares):
    return {"outcome": outcome, "exit_price": round(exit_price, 2), "exit_time": exit_time,
            "pnl": round((exit_price - entry) * shares, 2)}


def settle(entry, stop, target, shares, candles):
    """candles = list of (time, high, low, close), in time order, starting after we bought."""
    if not candles:
        return {"outcome": "not_filled", "exit_price": None, "exit_time": None, "pnl": 0}

    for time, high, low, close in candles:
        if low <= stop:                       # the stop was touched (also covers "both in one candle": stop first)
            return _result("stop_hit", stop, time, entry, shares)
        if high >= target:                    # the target was touched
            return _result("target_hit", target, time, entry, shares)

    last_time, _, _, last_close = candles[-1]  # neither happened: close the position at the end of the day
    return _result("closed_at_end", last_close, last_time, entry, shares)


def candles_after(history, start_time):
    """From a yfinance 5-minute table, keep the candles that start at or after start_time and before the square-off."""
    rows = []
    for stamp, row in history.iterrows():
        if stamp >= start_time and stamp.time() < SQUARE_OFF:
            rows.append((stamp, float(row["High"]), float(row["Low"]), float(row["Close"])))
    return rows


def benchmark_move(history, started_at):
    """
    How far an index moved over the window our trades were open, in percent. It starts from the price when the
    run began (the close of the last 5-minute candle that had already finished) and ends at the last close before
    the square-off. Returns None if there is not enough data.
    """
    at_start, at_end = None, None
    for stamp, row in history.iterrows():
        if stamp + timedelta(minutes=5) <= started_at:
            at_start = float(row["Close"])
        if stamp.time() < SQUARE_OFF:
            at_end = float(row["Close"])
    if at_start is None or at_end is None or at_start <= 0:
        return None
    return (at_end / at_start - 1) * 100


def _floor_tick(price):
    """Round a price DOWN to NSE's 0.05 steps."""
    return round(math.floor(round(price / 0.05, 6)) * 0.05, 2)


def candidate_outcome(entry, avg_range, candles, stop_fraction=0.40, target_fraction=1.0):
    """
    How a stock did from the moment of the run until the close, whether or not we bought it.

    candles = list of (time, high, low, close), in time order, starting after the run began
              (exactly what candles_after() returns).
    It reports three simple facts (return to the close, the highest and the lowest point reached) and
    one "what if" trade with a FIXED rule, so every stock can be compared on equal terms:
    stop = stop_fraction of the daily range below the buy price, target = target_fraction of the range above,
    both rounded to price steps, judged with the same settle() rule as the real trades.
    Returns None if there are no candles.
    """
    if not candles or entry <= 0:
        return None
    highs = [c[1] for c in candles]
    lows = [c[2] for c in candles]
    close = candles[-1][3]
    result = {
        "close_price": round(close, 2),
        "return_pct": round((close / entry - 1) * 100, 4),
        "max_up_pct": round((max(highs) / entry - 1) * 100, 4),
        "max_down_pct": round((min(lows) / entry - 1) * 100, 4),
        "candles_used": len(candles),
        "std_stop": None, "std_target": None, "std_outcome": None,
        "std_exit_price": None, "std_exit_time": None, "std_return_pct": None,
    }
    stop = _floor_tick(entry - stop_fraction * avg_range)
    target = _floor_tick(entry + target_fraction * avg_range)
    if stop < entry < target:                                  # tiny ranges can round to nothing: then no "what if" trade
        trade = settle(entry, stop, target, 1, candles)
        result.update(
            std_stop=stop, std_target=target, std_outcome=trade["outcome"],
            std_exit_price=trade["exit_price"], std_exit_time=trade["exit_time"],
            std_return_pct=round((trade["exit_price"] / entry - 1) * 100, 4),
        )
    return result


def outcomes_for_candidates(candidates, candles_by_symbol):
    """
    candidates: rows from the candidates table, each with symbol, price and avg_range.
    candles_by_symbol: {symbol: list of (time, high, low, close)}, as returned by candles_after().
    Returns {symbol: report}: candidate_outcome()'s report plus entry_price.
    A candidate with no candles, or without a price or range, is left out; the caller can see who is missing.
    """
    reports = {}
    for row in candidates:
        price, avg_range = row.get("price"), row.get("avg_range")
        if price is None or avg_range is None:
            continue
        report = candidate_outcome(float(price), float(avg_range), candles_by_symbol.get(row["symbol"]) or [])
        if report is not None:
            report["entry_price"] = round(float(price), 2)
            reports[row["symbol"]] = report
    return reports


def group_summary(reports, watchlist_symbols):
    """Average return to the close of the stocks on the watchlist versus the other candidates."""
    on = [r["return_pct"] for symbol, r in reports.items() if symbol in watchlist_symbols]
    off = [r["return_pct"] for symbol, r in reports.items() if symbol not in watchlist_symbols]
    average = lambda values: sum(values) / len(values) if values else None
    return {"watchlist_avg": average(on), "watchlist_n": len(on), "others_avg": average(off), "others_n": len(off)}