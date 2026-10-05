"""
Public dashboard for the AI day-trader simulation.
Run it locally, from inside the dashboard folder (so the theme in .streamlit/config.toml is picked up):

    cd dashboard
    streamlit run app.py

It reads ONLY the public_* views, using the publishable key. It never needs (and must never get) the secret key.
Settings, in .env or the environment:
    SUPABASE_URL=...
    SUPABASE_PUBLISHABLE_KEY=...
    DASHBOARD_DEMO=1        optional: show made-up sample data, to preview the layout
"""
import logging
import os

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from metrics import clean_equity, clean_trades, comparison_frame, compute_metrics, demo_data, demo_day
from theme import CSS, NEON, card, md_escape, safe_link

load_dotenv()
log = logging.getLogger("dashboard")
st.set_page_config(page_title="AI day trader (simulation)", page_icon="📈", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)
DEMO = os.getenv("DASHBOARD_DEMO", "").strip().lower() in {"1", "true", "yes"}

OUTCOME_NAMES = {"target_hit": "target reached", "stop_hit": "stop-loss hit", "closed_at_end": "closed at end of day"}


# ---------------------------------------------------------------------------- data
def _client():
    from supabase import create_client
    return create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))


def _read(view, order, desc=False, limit=1000, **equals):
    query = _client().table(view).select("*")
    for column, value in equals.items():
        query = query.eq(column, value)
    return pd.DataFrame(query.order(order, desc=desc).limit(limit).execute().data)


@st.cache_data(ttl=300)                                   # refresh at most every 5 minutes
def load_overview():
    return (_read("public_daily_equity", "market_date"), _read("public_trades", "market_date", desc=True),
            _read("public_runs", "market_date", desc=True, limit=500))


@st.cache_data(ttl=300)
def load_day(day_iso: str) -> dict:
    return {"candidates": _read("public_candidates", "rank", market_date=day_iso),
            "headlines": _read("public_headlines", "position", market_date=day_iso),
            "verdicts": _read("public_verdicts", "symbol", market_date=day_iso),
            "plans": _read("public_plans", "symbol", market_date=day_iso)}


@st.cache_data(ttl=300)
def load_blog():
    return _read("public_blog_posts", "market_date", desc=True, limit=30)


def money(value: float) -> str:
    return f"{'−' if value < 0 else ''}₹{abs(value):,.0f}"


def tone_of(value: float) -> str:
    return "good" if value > 0 else "bad" if value < 0 else "neutral"


# ---------------------------------------------------------------------------- page header
st.title("📈 AI day trader: a paper-trading experiment")
st.warning("**This is a simulation with fake money, run by an AI.** It is **not investment advice**, and nothing here is "
           "a recommendation to buy or sell anything. Results ignore brokerage, taxes and slippage, so real trading "
           "would have done worse. Each trading day is published only after the market has closed.")
if DEMO:
    st.error("DEMO DATA: every number on this page is made up, to preview the layout.")

try:
    equity, trades, runs = demo_data() if DEMO else load_overview()
except Exception as error:                                 # never show raw errors to the public: they can hold internal details
    log.exception("Could not load the dashboard data: %s", type(error).__name__)
    st.error("The data could not be loaded right now. Please try again in a few minutes.")
    st.stop()

if equity.empty:
    st.info("No trading days have been settled yet. The first results appear after the market closes on the first trading day.")
    st.stop()

equity, trades = clean_equity(equity), clean_trades(trades)
if not runs.empty:
    runs = runs.copy()
    runs["market_date"] = pd.to_datetime(runs["market_date"])
m = compute_metrics(equity, trades)

tab_overview, tab_days, tab_trades, tab_blog, tab_about = st.tabs(
    ["📈 Overview", "🗓️ Day by day", "🧾 All trades", "📝 Blog", "ℹ️ About"])

# ---------------------------------------------------------------------------- overview
with tab_overview:
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(card("Balance", money(m["balance"]), f"{money(m['total_pnl'])} since the start", tone_of(m["total_pnl"])), unsafe_allow_html=True)
    c2.markdown(card("Total return", f"{m['return_pct']:+.2f}%", f"{m['days']} trading days settled", tone_of(m["return_pct"])), unsafe_allow_html=True)
    c3.markdown(card("Win rate", "n/a" if m["win_rate"] is None else f"{m['win_rate']:.0f}%",
                     f"{m['trade_count']} settled trades", "neutral"), unsafe_allow_html=True)
    c4.markdown(card("Worst drop from a peak", f"{m['max_drawdown_pct']:.2f}%", f"best day {money(m['best_day'])}, worst {money(m['worst_day'])}", "warn"),
                unsafe_allow_html=True)

    st.subheader("Strategy vs the market")
    st.line_chart(comparison_frame(equity), color=[NEON["green"], NEON["pink"]])
    st.caption("Cumulative return in %. The Nifty line covers the same time window as the trades each day "
               "(from when the app bought until the 3:15 PM close). A day without a benchmark counts as 0%.")

    left, right = st.columns(2)
    with left:
        st.subheader("Profit and loss per day (₹)")
        pnl = equity.set_index("market_date")["pnl"]
        st.bar_chart(pd.DataFrame({"Profit": pnl.clip(lower=0), "Loss": pnl.clip(upper=0)}), color=[NEON["green"], NEON["red"]])
    with right:
        st.subheader("How the trades ended")
        if trades.empty:
            st.write("No settled trades yet.")
        else:
            counts = trades["outcome"].value_counts()
            wide = pd.DataFrame({OUTCOME_NAMES[k]: [int(counts.get(k, 0))] for k in OUTCOME_NAMES}, index=["trades"])
            st.bar_chart(wide, color=[NEON["green"], NEON["red"], NEON["yellow"]])

# ---------------------------------------------------------------------------- day by day
with tab_days:
    if runs.empty:
        st.write("No days to show yet.")
    else:
        days = sorted(runs["market_date"].dt.date.unique(), reverse=True)
        day = st.selectbox("Pick a day", days, format_func=lambda d: d.strftime("%A %d %b %Y"))
        run = runs[runs["market_date"].dt.date == day].iloc[0]
        day_pnl = equity.loc[equity["market_date"].dt.date == day, "pnl"]

        if run["status"] == "skipped":
            st.info(f"The app did not trade on this day: {run.get('note') or 'the market was closed'}.")
        elif run["status"] == "failed":
            st.warning("The run failed on this day, so there were no trades.")
        else:
            detail = demo_day(day) if DEMO else load_day(day.isoformat())
            cands, heads, verdicts, plans = (detail[k] for k in ("candidates", "headlines", "verdicts", "plans"))
            accepted = plans[plans["status"] == "accepted"] if not plans.empty else plans
            strong = int(verdicts["on_watchlist"].sum()) if not verdicts.empty else 0

            d1, d2, d3, d4, d5 = st.columns(5)
            d1.markdown(card("Stocks checked", str(int(run["universe_size"])) if pd.notna(run.get("universe_size")) else "100", "the Nifty 100", "neutral"), unsafe_allow_html=True)
            d2.markdown(card("Moving", str(int(run["passed_screen"])) if pd.notna(run.get("passed_screen")) else str(len(cands)), "passed the screener", "neutral"), unsafe_allow_html=True)
            d3.markdown(card("Strong catalysts", str(strong), "news worth acting on", "neutral"), unsafe_allow_html=True)
            d4.markdown(card("Trades", str(len(accepted)), "accepted plans", "neutral"), unsafe_allow_html=True)
            pnl_value = float(day_pnl.iloc[0]) if len(day_pnl) else None
            d5.markdown(card("Day profit/loss", "pending" if pnl_value is None else money(pnl_value),
                             "after settlement", "neutral" if pnl_value is None else tone_of(pnl_value)), unsafe_allow_html=True)

            if cands.empty:
                st.info("Nothing was moving enough that day, so the app stopped before looking at any news.")
            else:
                st.subheader("What the app looked at, and why it did or did not act")
                for _, cand in cands.sort_values("rank").iterrows():
                    symbol = cand["symbol"]
                    verdict = verdicts[verdicts["symbol"] == symbol] if not verdicts.empty else verdicts
                    verdict = verdict.iloc[0] if len(verdict) else None
                    if verdict is None:
                        label = "no verdict"
                    elif verdict["on_watchlist"]:
                        label = "✅ strong catalyst, on the watchlist"
                    elif verdict["has_catalyst"]:
                        label = f"➖ catalyst judged {verdict['strength']}, not selected"
                    else:
                        label = "❌ no real catalyst"
                    with st.expander(f"#{int(cand['rank'])}  {symbol}   {cand['change_pct']:+.1f}%   volume x{cand['rel_volume']:.1f}   {label}"):
                        st.markdown(f"**Price** ₹{cand['price']:,.2f} · **typical daily range** ₹{cand['avg_range']:,.2f}")
                        if verdict is not None:
                            st.markdown(f"**The model's verdict** ({md_escape(verdict['catalyst_type'])}, {md_escape(verdict['strength'])}): "
                                        f"{md_escape(verdict['reason'])}")
                            if verdict["overruled_by_code"]:
                                st.markdown("_The model's answer was overruled by a safety check in the code._")
                        stock_heads = heads[heads["symbol"] == symbol].sort_values("position") if not heads.empty else heads
                        if len(stock_heads):
                            st.markdown("**Headlines it was shown**")
                            for _, h in stock_heads.iterrows():
                                st.markdown(f"{int(h['position'])}. {safe_link(h['title'], h['url'])}")
                        else:
                            st.markdown("_No headlines were found._")
                        stock_plan = plans[plans["symbol"] == symbol] if not plans.empty else plans
                        if len(stock_plan):
                            p = stock_plan.iloc[0]
                            if p["status"] == "accepted":
                                result = ("settlement pending" if pd.isna(p["outcome"]) else
                                          f"{OUTCOME_NAMES.get(p['outcome'], p['outcome'])}, profit/loss {money(float(p['pnl']))}")
                                st.markdown(f"**Plan:** buy {int(p['shares'])} at ₹{p['entry']:,.2f}, stop ₹{p['stop']:,.2f}, "
                                            f"target ₹{p['target']:,.2f}. **Result:** {md_escape(result)}")
                            else:
                                st.markdown(f"**Plan {md_escape(p['status'])}:** {md_escape(p['rejection_reason'] or '')}")

# ---------------------------------------------------------------------------- all trades
with tab_trades:
    if trades.empty:
        st.write("No settled trades yet.")
    else:
        pick = st.multiselect("Outcome", list(OUTCOME_NAMES), default=list(OUTCOME_NAMES), format_func=OUTCOME_NAMES.get)
        shown = trades[trades["outcome"].isin(pick)].copy()
        table = shown[["market_date", "symbol", "catalyst_type", "entry", "stop", "target", "exit_price", "shares", "outcome", "pnl"]].copy()
        table["market_date"] = table["market_date"].dt.strftime("%Y-%m-%d")
        table["outcome"] = table["outcome"].map(OUTCOME_NAMES).fillna(table["outcome"])
        table.columns = ["Date", "Stock", "News type", "Bought at", "Stop", "Target", "Sold at", "Shares", "Outcome", "Profit/loss (₹)"]
        st.dataframe(table, hide_index=True)
        st.download_button("Download as CSV", table.to_csv(index=False).encode("utf-8"), "ai_day_trader_trades.csv", "text/csv")

# ---------------------------------------------------------------------------- blog
with tab_blog:
    try:
        posts = pd.DataFrame() if DEMO else load_blog()
    except Exception:
        posts = pd.DataFrame()
    if posts.empty:
        st.write("The daily blog is coming soon. It will be written by an AI from each day's results.")
    else:
        st.caption("These posts are written by an AI from the day's recorded data. The numbers come from the database, not from the AI.")
        for _, post in posts.iterrows():
            st.subheader(md_escape(post["title"]))
            st.caption(str(post["market_date"]))
            st.markdown(post["body_markdown"])
            st.divider()

# ---------------------------------------------------------------------------- about
with tab_about:
    st.markdown("""
### What is this?
An experiment: an AI agent tries to trade Indian stocks **with fake money**, every trading day, with no human in the loop.
Everything it does is recorded and shown here.

### How a day works
1. **Check the market.** The app only runs on a trading day, at about 9:35 AM India time.
2. **Screen.** Out of the Nifty 100, it keeps stocks that are up at least 0.5% with higher than normal volume.
3. **Read the news.** For the top movers it collects recent headlines.
4. **Judge.** An AI model decides whether each headline shows a real, fresh reason for the move. Plain code double-checks its answers.
5. **Plan.** For stocks with a strong reason, the AI proposes a stop-loss and a target. A rulebook in code rejects plans that are too risky.
6. **Settle.** After the close, 5-minute prices show whether each trade hit its target, its stop-loss, or neither.

### Limits you should know about
- It is a **simulation**. No real orders are placed and no real money is involved.
- **Costs are ignored.** Brokerage, taxes and slippage would reduce real results.
- Prices and news come from free, unofficial sources that can be late or wrong.
- A few weeks of results prove nothing. Luck can look like skill.
- Nothing here is investment advice. Please do not trade based on this page.
""")