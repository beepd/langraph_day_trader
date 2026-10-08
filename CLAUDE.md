# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Paper-trading experiment (fake money, no real orders): each weekday it screens the Nifty 100, has an LLM judge news
for the movers, has an LLM propose stop/target which a code rulebook accepts or rejects, then settles the trades on
5-minute candles after the close. Everything goes to Supabase, Telegram, and a public Streamlit dashboard.
`README.md` is detailed and current. Read it for the full step-by-step flow, the config table, and the DB tables.

## Commands

Windows dev machine (PowerShell), venv in `.venv`. Production is a Debian GCP VM running `scheduler.py` under systemd.

```bash
pip install -r requirements.txt
python morning_run.py              # morning job; stops at preflight outside 9:30-14:30 IST unless FORCE_RUN=1
python settle_day.py [YYYY-MM-DD]  # settlement + report card; refuses before 15:35 IST unless FORCE_SETTLE=1
python scheduler.py --dry-run      # also: --now morning | --now settle
python backfill_report_cards.py    # grade past days missing a report card (--force redoes all)
python llm_test.py                 # check the configured model can fill structured output
python notify.py                   # send a test Telegram message
cd dashboard && streamlit run app.py   # must run from inside dashboard/; DASHBOARD_DEMO=1 for fake data
```

Tests are plain scripts, not pytest. Each one runs offline, prints `ok`/`BAD` lines, and ends with
`ALL CHECKS PASSED` or names the failing checks. Run one at a time from the repo root:

```bash
python test_nudge.py               # rulebook nudge, incl. a 200k random-plan property test
python test_candidate_outcome.py
python test_report_card.py         # full settle_day with a stand-in Supabase client and stand-in yfinance
python test_backfill.py
python test_experiment_articles.py
```

There is no linter or build step.

## Architecture

- **`morning_run.py`**: a LangGraph `StateGraph` over a `State` TypedDict with the nodes
  preflight → screen_stocks → fetch_news → analyze_news → plan_trades, plus conditional edges (`decide_*`) that stop
  early. The LLM fills two Pydantic models: `Verdict` (analyst) and `TradePlan` (planner). Screener/strategy
  thresholds are module-level constants at the top of this file.
- **`rules.py`**: deterministic money logic. `size_trade()` applies the risk rules and sizes the position.
  `nudge_plan()` snaps near-miss stops/targets to the limit before `size_trade` runs. Risk constants live here.
  **The LLM never decides numbers. Any model output goes through code checks** (e.g. a cited headline must name the
  company, or `has_catalyst` is overruled).
- **`settlement.py`**: pure functions with no I/O: `settle()` (stop is checked before target within a candle, the
  pessimistic choice), `benchmark_move()`, `candidate_outcome()` (fixed what-if trade for *every* candidate), and
  `group_summary()`. **`settle_day.py`** is the I/O wrapper. It writes `trade_results` and `daily_equity`, then
  runs the report card in a guarded block so a report-card failure can never block the balance update.
- **`storage.py`**: all Supabase access for the jobs (secret key). The dashboard reads only the `public_*` views with
  the publishable key.
- **`scheduler.py`**: launches each job as a subprocess with the env read at scheduler start, and forces `FORCE_*` off.
  A code change needs only `git pull` on the VM. An `.env` change needs a service restart.
- **`messages.py`** holds all Telegram text. **`notify.py`** sends it over plain HTTPS and must never raise.
- **`llm_setup.py`**: `build_llm()` from `LLM_PROVIDER`/`LLM_MODEL`. It omits temperature for reasoning models.
- **`experiment_articles.py`**: a standalone research script (article-text extraction). It is not part of the pipeline.

Key invariants:
- **Fail closed.** If the balance can't be read or the market looks closed, record a skipped/failed run and stop.
- Each day's **official run** is the latest run with `status='finished'` and `data_is_live=true`. Settlement, views
  and backfill all use only that run. A forced run on a trading day against the real DB replaces the official run.
- Next morning's balance comes from the latest `daily_equity.ending_balance` (₹1,00,000 if none exists).
- Prices are rounded to NSE's 0.05 tick.

## Database

The canonical SQL is in `sql/`: apply `schema.sql`, then `migration_001` … `migration_005` in order.
All tables have RLS with no policies, so the public sees only the `public_*`
views. Rollout order: run SQL on the test Supabase project, then on prod, then push the code that uses it.

## Working with the owner

From the README's contributor notes:
- The owner is an experienced Java/Spring Boot architect who is new to Python and to the stock market. Explain market
  concepts plainly, using software analogies where they help.
- Work in small steps: explain the idea, give one small piece of code, and let the owner run it. Don't dump whole files.
- Every behaviour change gets an offline test in the existing style: stand-in DB/prices and `check()`-style output.
  Never claim something was tested against a real API or site you couldn't reach.
- Keep output short. The owner pastes only summaries of long program output.
- The repo is public: no keys, chat IDs or server addresses in commits.
