-- Migration 002: the public face of the database.
-- The public dashboard (and anyone holding the publishable key) can read ONLY these three views.
-- Every base table stays locked (row-level security on, no policies), so nothing else is reachable.
-- Paste into Supabase: SQL Editor -> New query -> Run.  Safe to run more than once.

-- Is this trading day finished? Today's results become visible only after 3:35 PM India time, so the public
-- never sees anything about trades while the market is still open.
create or replace function day_is_over(d date) returns boolean
language sql stable as $$
    select d < (now() at time zone 'Asia/Kolkata')::date
        or (d = (now() at time zone 'Asia/Kolkata')::date
            and (now() at time zone 'Asia/Kolkata')::time >= time '15:35')
$$;
-- (Anyone may call this function: it only answers yes or no for a date. Postgres checks function permissions as the
--  person reading a view, so the public role must be allowed to run it for the views to work.)

-- 1. The balance, day by day
create or replace view public_daily_equity as
select market_date, starting_balance, ending_balance, pnl, trades, benchmark_pct, capital_used
from daily_equity
where day_is_over(market_date);

-- 2. Settled trades only (a plan with no result yet is never shown)
create or replace view public_trades as
select r.market_date, p.symbol, v.catalyst_type, p.entry, p.stop, p.target, p.shares, p.cost,
       t.outcome, t.exit_price, t.exit_time, t.pnl
from trade_results t
join plans p on p.id = t.plan_id
join runs  r on r.id = p.run_id
left join verdicts v on v.run_id = p.run_id and v.symbol = p.symbol
where day_is_over(r.market_date);

-- 3. Which days the app traded and which it skipped (and why), without any stock names
create or replace view public_runs as
select market_date, status, note, passed_screen
from runs
where status in ('finished', 'skipped') and day_is_over(market_date);

-- Read-only for the public roles, nothing else
revoke all on public_daily_equity, public_trades, public_runs from anon, authenticated;
grant select on public_daily_equity, public_trades, public_runs to anon, authenticated;
