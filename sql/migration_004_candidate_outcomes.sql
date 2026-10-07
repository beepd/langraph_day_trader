-- Migration 004: a report card for EVERY candidate the analyst looked at, not only the stocks we bought.
-- Paste into the Supabase SQL Editor (run it on the TEST project first).  Safe to run more than once.
--
-- One row per candidate per run. It is filled in by the end-of-day settlement job, once the day's prices are known.

create table if not exists candidate_outcomes (
    id              bigint generated always as identity primary key,
    run_id          bigint not null references runs (id) on delete cascade,
    symbol          text   not null,
    entry_price     numeric(12, 2),       -- the price at the start of the run (the same as candidates.price)
    close_price     numeric(12, 2),       -- the last price before the 3:15 PM square-off
    return_pct      numeric(8, 4),        -- % change from entry_price to close_price
    max_up_pct      numeric(8, 4),        -- the highest point reached, as % above entry_price
    max_down_pct    numeric(8, 4),        -- the lowest point reached, as % below entry_price (negative)
    candles_used    int,                  -- how many 5-minute candles the numbers are based on
    std_stop        numeric(12, 2),       -- the fixed "what if" trade: stop (40% of the daily range below)
    std_target      numeric(12, 2),       --                           target (one daily range above)
    std_outcome     text check (std_outcome in ('target_hit', 'stop_hit', 'closed_at_end')),
    std_exit_price  numeric(12, 2),
    std_exit_time   timestamptz,
    std_return_pct  numeric(8, 4),        -- what that "what if" trade would have earned, in %
    computed_at     timestamptz not null default now(),
    unique (run_id, symbol)
);

-- Private for now, like the other base tables: row-level security on, and no access for the public roles.
alter table candidate_outcomes enable row level security;
revoke all on candidate_outcomes from anon, authenticated;
