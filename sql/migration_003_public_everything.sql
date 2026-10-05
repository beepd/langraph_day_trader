-- Migration 003: make the whole story public, read-only, one finished day at a time.
-- Run AFTER migration 002. Paste into Supabase: SQL Editor -> New query -> Run.  Safe to run more than once.
--
-- What changes:
--   * Candidates, headlines, Gemini's verdicts, ALL plans (accepted, rejected, skipped), results and published
--     blog posts become readable through public_* views.
--   * One "official" run per day is used everywhere: the latest finished run that used live data (the same run
--     the settlement job settles). Test runs on stale data never show up.
--   * Still hidden: error messages (they can contain internal details), the base tables, and ANY day that is not
--     over yet. To change when a day becomes visible, change the function day_is_over() from migration 002.

-- The one official run per day (an internal helper: the public cannot read this view directly)
create or replace view official_runs as
select distinct on (market_date)
       id as run_id, market_date, status, note, passed_screen, data_is_live,
       model_name, universe_size, started_at, finished_at, settings
from runs
where day_is_over(market_date)
  and ((status = 'finished' and data_is_live) or status in ('skipped', 'failed'))
order by market_date,
         case when status = 'finished' then 0 when status = 'skipped' then 1 else 2 end,   -- a real run beats a skip beats a failure
         id desc;

-- The days: same four columns as before, plus a few more at the end (the error text is NOT included)
create or replace view public_runs as
select market_date, status, note, passed_screen,
       run_id, data_is_live, model_name, universe_size, started_at, finished_at, settings
from official_runs;

-- Settled trades (now limited to the official run of each day)
create or replace view public_trades as
select r.market_date, p.symbol, v.catalyst_type, p.entry, p.stop, p.target, p.shares, p.cost,
       t.outcome, t.exit_price, t.exit_time, t.pnl
from trade_results t
join plans p on p.id = t.plan_id
join official_runs r on r.run_id = p.run_id
left join verdicts v on v.run_id = p.run_id and v.symbol = p.symbol;

-- Every mover the screener found
create or replace view public_candidates as
select r.market_date, c.run_id, c.symbol, c.rank, c.price, c.change_pct, c.rel_volume, c.avg_range
from candidates c join official_runs r on r.run_id = c.run_id;

-- Every headline the model was shown
create or replace view public_headlines as
select r.market_date, h.run_id, h.symbol, h.position, h.title, h.source, h.published_at, h.url
from headlines h join official_runs r on r.run_id = h.run_id;

-- Every verdict, including the ones that were rejected
create or replace view public_verdicts as
select r.market_date, v.run_id, v.symbol, v.has_catalyst, v.bullish, v.strength, v.catalyst_type, v.reason,
       v.cited_positions, v.overruled_by_code, v.on_watchlist
from verdicts v join official_runs r on r.run_id = v.run_id;

-- Every plan (accepted, rejected, skipped) with its result once settled
create or replace view public_plans as
select r.market_date, p.run_id, p.symbol, p.status, p.rejection_reason, p.entry, p.stop, p.target, p.shares,
       p.cost, p.max_loss, p.max_gain, p.gemini_reason,
       t.outcome, t.exit_price, t.exit_time, t.pnl
from plans p
join official_runs r on r.run_id = p.run_id
left join trade_results t on t.plan_id = p.id;

-- Blog posts you have marked as published
create or replace view public_blog_posts as
select market_date, title, body_markdown, model_name, created_at
from blog_posts
where published and day_is_over(market_date);

-- Read-only for the public roles. The helper view and the base tables stay closed.
revoke all on official_runs from anon, authenticated;
revoke all on public_daily_equity, public_runs, public_trades, public_candidates, public_headlines,
              public_verdicts, public_plans, public_blog_posts from anon, authenticated;
grant select on public_daily_equity, public_runs, public_trades, public_candidates, public_headlines,
                public_verdicts, public_plans, public_blog_posts to anon, authenticated;
