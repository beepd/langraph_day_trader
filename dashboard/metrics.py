"""The calculations and sample data behind the dashboard. Plain functions: data in, numbers out."""
from datetime import date, timedelta

import numpy as np
import pandas as pd

NUMBER_COLUMNS = ["starting_balance", "ending_balance", "pnl", "trades", "benchmark_pct", "capital_used"]


def clean_equity(equity: pd.DataFrame) -> pd.DataFrame:
    equity = equity.copy()
    equity["market_date"] = pd.to_datetime(equity["market_date"])
    for column in NUMBER_COLUMNS:
        equity[column] = pd.to_numeric(equity[column], errors="coerce")
    return equity.sort_values("market_date").reset_index(drop=True)


def clean_trades(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return trades
    trades = trades.copy()
    trades["market_date"] = pd.to_datetime(trades["market_date"])
    for column in ["entry", "exit_price", "shares", "pnl"]:
        trades[column] = pd.to_numeric(trades[column], errors="coerce")
    return trades.sort_values("market_date", ascending=False).reset_index(drop=True)


def compute_metrics(equity: pd.DataFrame, trades: pd.DataFrame) -> dict:
    """Headline numbers. equity must be cleaned and non-empty."""
    start = float(equity["starting_balance"].iloc[0])
    balance = float(equity["ending_balance"].iloc[-1])
    path = pd.concat([pd.Series([start]), equity["ending_balance"]]).reset_index(drop=True)
    drawdown = ((path.cummax() - path) / path.cummax()).max() * 100
    settled = trades["pnl"].dropna() if not trades.empty else pd.Series(dtype=float)
    return {
        "start": start,
        "balance": balance,
        "total_pnl": balance - start,
        "return_pct": (balance / start - 1) * 100,
        "days": len(equity),
        "traded_days": int((equity["trades"] > 0).sum()),
        "trade_count": len(settled),
        "win_rate": float((settled > 0).mean() * 100) if len(settled) else None,
        "best_day": float(equity["pnl"].max()),
        "worst_day": float(equity["pnl"].min()),
        "max_drawdown_pct": float(drawdown),
    }


def comparison_frame(equity: pd.DataFrame) -> pd.DataFrame:
    """Cumulative return of the strategy and of the Nifty (same time window each day), in percent."""
    start = equity["starting_balance"].iloc[0]
    strategy = (equity["ending_balance"] / start - 1) * 100
    nifty = ((1 + equity["benchmark_pct"].fillna(0) / 100).cumprod() - 1) * 100     # a missing day counts as 0%
    return pd.DataFrame({"Strategy": strategy.values, "Nifty, same window": nifty.values},
                        index=equity["market_date"].values)


def demo_data(days: int = 40):
    """Made-up data so the layout can be previewed before real results exist."""
    rng = np.random.default_rng(7)
    symbols = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ITC", "BAJFINANCE", "WIPRO", "PNB", "ABB", "CGPOWER"]
    balance, equity_rows, trade_rows, run_rows = 100000.0, [], [], []
    for day in pd.bdate_range(end=date.today() - timedelta(days=1), periods=days):
        if rng.random() < 0.07:
            run_rows.append({"market_date": day, "status": "skipped", "note": "today is listed in NSE_HOLIDAYS", "passed_screen": None})
            continue
        day_pnl, used, count = 0.0, 0.0, int(rng.integers(0, 4))
        for _ in range(count):
            outcome = str(rng.choice(["target_hit", "stop_hit", "closed_at_end"], p=[0.4, 0.35, 0.25]))
            cost = float(rng.integers(20000, 30000))
            pct = {"target_hit": 0.012, "stop_hit": -0.008}.get(outcome, float(rng.normal(0, 0.004)))
            pnl = round(pct * cost, 2)
            day_pnl, used = day_pnl + pnl, used + cost
            trade_rows.append({"market_date": day, "symbol": str(rng.choice(symbols)),
                               "catalyst_type": str(rng.choice(["earnings", "broker_call", "sector_news", "other"])),
                               "entry": round(cost / 25, 2), "stop": None, "target": None, "shares": 25, "cost": cost,
                               "outcome": outcome, "exit_price": round(cost / 25 * (1 + pct), 2), "exit_time": None, "pnl": pnl})
        equity_rows.append({"market_date": day, "starting_balance": balance, "ending_balance": round(balance + day_pnl, 2),
                            "pnl": round(day_pnl, 2), "trades": count, "benchmark_pct": round(float(rng.normal(0.05, 0.5)), 2),
                            "capital_used": used})
        balance += day_pnl
        run_rows.append({"market_date": day, "status": "finished", "note": None, "passed_screen": int(rng.integers(0, 25))})
    return pd.DataFrame(equity_rows), pd.DataFrame(trade_rows), pd.DataFrame(run_rows)


def demo_day(day):
    """Made-up detail for one day (candidates, headlines, verdicts, plans), for previewing the 'Day by day' tab."""
    rng = np.random.default_rng(pd.Timestamp(day).toordinal())
    names = ["ENRIN", "INFY", "CGPOWER", "SBILIFE", "POWERINDIA", "MAXHEALTH", "ADANIENSOL", "ABB", "HDFCBANK", "CUMMINSIND"]
    chosen = [str(x) for x in rng.choice(names, size=6, replace=False)]
    cands, heads, verdicts, plans = [], [], [], []
    for rank, symbol in enumerate(chosen, start=1):
        price = float(rng.integers(300, 5000))
        cands.append({"market_date": day, "symbol": symbol, "rank": rank, "price": price,
                      "change_pct": round(float(rng.uniform(0.6, 4.5)), 2), "rel_volume": round(float(rng.uniform(1, 4)), 2),
                      "avg_range": round(price * 0.02, 2)})
        for position in (1, 2):
            heads.append({"market_date": day, "symbol": symbol, "position": position, "source": "Example News",
                          "title": f"[demo] {symbol} headline number {position}", "published_at": None, "url": "https://example.com/demo"})
        strong = rank <= 3
        verdicts.append({"market_date": day, "symbol": symbol, "has_catalyst": strong, "bullish": strong,
                         "strength": "strong" if strong else "weak", "catalyst_type": "earnings" if strong else "other",
                         "reason": "Made-up reason for the demo." if strong else "Headlines are generic.",
                         "cited_positions": [1] if strong else [], "overruled_by_code": False, "on_watchlist": strong})
        if strong:
            ok = rank <= 2
            plans.append({"market_date": day, "symbol": symbol, "status": "accepted" if ok else "skipped",
                          "rejection_reason": None if ok else "already have 2 positions", "entry": price,
                          "stop": round(price * 0.99, 2), "target": round(price * 1.015, 2), "shares": 20, "cost": price * 20,
                          "max_loss": round(price * 0.2, 2), "max_gain": round(price * 0.3, 2), "gemini_reason": "Demo plan.",
                          "outcome": "target_hit" if ok else None, "exit_price": round(price * 1.015, 2) if ok else None,
                          "exit_time": None, "pnl": round(price * 0.3, 2) if ok else None})
    return {"candidates": pd.DataFrame(cands), "headlines": pd.DataFrame(heads),
            "verdicts": pd.DataFrame(verdicts), "plans": pd.DataFrame(plans)}