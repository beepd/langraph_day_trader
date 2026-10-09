-- Migration 007: show the checklist analyst's extra columns in the report-card view and the public verdicts view.
-- Run AFTER migration 006 (it reads the columns that migration adds). Test project first, then the real one.
-- Safe to run more than once. Only appends columns to the end of each view, so nothing that reads them breaks.

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
    co.std_outcome, co.std_return_pct,
    v.event_status, v.has_number, v.checklist_notes,
    (v.strength = 'strong' and not v.on_watchlist) as dropped_by_sector_rule     -- strong by the rules, removed by the sector rule
from official o
join candidates c on c.run_id = o.run_id
left join verdicts v           on v.run_id = c.run_id and v.symbol = c.symbol
left join plans p              on p.run_id = c.run_id and p.symbol = c.symbol
left join trade_results t      on t.plan_id = p.id
left join candidate_outcomes co on co.run_id = c.run_id and co.symbol = c.symbol;

revoke all on candidate_report from anon, authenticated;

create or replace view public_verdicts as
select r.market_date, v.run_id, v.symbol, v.has_catalyst, v.bullish, v.strength, v.catalyst_type, v.reason,
       v.cited_positions, v.overruled_by_code, v.on_watchlist,
       v.event_status, v.has_number, v.checklist_notes
from verdicts v join official_runs r on r.run_id = v.run_id;

-- keep the public roles read-only on the public view, as migration 003 set it up
grant select on public_verdicts to anon, authenticated;
