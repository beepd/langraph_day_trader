-- Migration 005: one tidy "report card" view that joins everything we know about each candidate.
-- Run AFTER migration 004. Paste into the Supabase SQL Editor (test project first). Safe to run more than once.
--
-- One row per candidate of each day's OFFICIAL run (the latest finished run that used live data), with:
--   what the screener saw, what the analyst decided, what we did (bought or not, and the real result),
--   and what the stock actually did until the close (from candidate_outcomes).
-- It is a private view: the public roles cannot read it.

create or replace view candidate_report as
with official as (
    select distinct on (market_date) id as run_id, market_date
    from runs
    where status = 'finished' and data_is_live
    order by market_date, id desc
)
select
    o.market_date, c.run_id, c.symbol, c.rank,
    c.change_pct as morning_change_pct, c.rel_volume,
    v.has_catalyst, v.bullish, v.strength, v.catalyst_type, v.on_watchlist, v.overruled_by_code,
    coalesce(p.status, 'none') as plan_status,
    t.outcome as real_outcome, t.pnl as real_pnl,
    co.entry_price, co.close_price, co.return_pct, co.max_up_pct, co.max_down_pct,
    co.std_outcome, co.std_return_pct
from official o
join candidates c on c.run_id = o.run_id
left join verdicts v           on v.run_id = c.run_id and v.symbol = c.symbol
left join plans p              on p.run_id = c.run_id and p.symbol = c.symbol
left join trade_results t      on t.plan_id = p.id
left join candidate_outcomes co on co.run_id = c.run_id and co.symbol = c.symbol;

revoke all on candidate_report from anon, authenticated;
