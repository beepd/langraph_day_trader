-- Were the analyst's favourites better than the rest?   Run in the Supabase SQL Editor any time.
-- Groups every graded candidate by what the analyst said and what we did, then compares how they did until the close.
--   avg_return_to_close_pct : plain % change from the run's start to the 3:15 PM close
--   avg_whatif_trade_pct    : the fixed "what if" trade (stop 40% of the daily range below, target one range above)
--   pct_hit_target / pct_hit_stop : how often that "what if" trade reached its target / its stop
-- Needs migration 007 (the dropped_by_sector_rule column).
-- Remember: a few days of data is noise. Look at the 'stocks' column before you read anything into the averages.

select
    case
        when on_watchlist and plan_status = 'accepted' then '1. strong catalyst, bought'
        when on_watchlist                              then '2. strong catalyst, not bought'
        when dropped_by_sector_rule                    then '3. strong, dropped by the sector rule (checklist analyst)'
        when has_catalyst                              then '4. catalyst judged weak or not bullish'
        else                                                '5. no catalyst'
    end                                                          as stock_group,
    count(*)                                                     as stocks,
    count(distinct market_date)                                  as days,
    round(avg(return_pct)::numeric, 2)                           as avg_return_to_close_pct,
    round(avg(std_return_pct)::numeric, 2)                       as avg_whatif_trade_pct,
    round(100.0 * avg((std_outcome = 'target_hit')::int), 0)     as pct_hit_target,
    round(100.0 * avg((std_outcome = 'stop_hit')::int), 0)       as pct_hit_stop
from candidate_report
where return_pct is not null
group by 1
order by 1;