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