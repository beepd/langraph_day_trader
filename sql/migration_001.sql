-- Migration 001: record skipped/failed runs, and give the dashboard a benchmark.
-- Paste into Supabase: SQL Editor -> New query -> Run.  Safe to run more than once.

-- 1. Runs can now be 'skipped' (market closed), and carry a note saying why.
--    (We drop whatever CHECK rule currently limits runs.status, whatever it is called, then add the new one.)
do $$
declare c record;
begin
    for c in
        select conname from pg_constraint
        where conrelid = 'public.runs'::regclass and contype = 'c' and pg_get_constraintdef(oid) like '%status%'
    loop
        execute format('alter table public.runs drop constraint %I', c.conname);
    end loop;
end $$;

alter table runs add constraint runs_status_check
    check (status in ('running', 'finished', 'failed', 'skipped'));
alter table runs add column if not exists note text;          -- why a run was skipped

-- 2. Daily benchmark and capital used, for the dashboard.
alter table daily_equity add column if not exists benchmark_pct numeric(8, 2);   -- how far the Nifty index moved in the same window
alter table daily_equity add column if not exists capital_used  numeric(14, 2);  -- rupees actually put into trades that day
