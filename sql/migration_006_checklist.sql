-- Migration 006: the checklist analyst (7b).
-- Run it in the Supabase SQL Editor: first on the TEST project, then on the REAL one, and only THEN set
-- ANALYST_MODE=checklist in that machine's .env. It is safe to run twice.
--
-- What changes:
--   * verdicts.catalyst_type may now also hold the checklist's event types (the old five are still allowed)
--   * three new answer columns on verdicts, empty for runs made by the classic analyst

alter table verdicts drop constraint if exists verdicts_catalyst_type_check;
alter table verdicts add constraint verdicts_catalyst_type_check check (catalyst_type in (
    -- the classic analyst
    'earnings', 'broker_call', 'block_deal', 'sector_news', 'other',
    -- the checklist analyst (earnings, block_deal and other are shared)
    'order_win', 'regulatory_approval', 'deal_or_acquisition', 'broker_target',
    'dividend', 'product_or_partnership', 'management_change', 'sector_or_market_move'));

alter table verdicts add column if not exists event_status text;
alter table verdicts drop constraint if exists verdicts_event_status_check;
alter table verdicts add constraint verdicts_event_status_check
    check (event_status in ('happened', 'expected', 'rumour_or_opinion'));

alter table verdicts add column if not exists has_number boolean;      -- does a cited headline state a concrete figure?
alter table verdicts add column if not exists checklist_notes text;    -- why a stock was NOT strong, or was dropped by the sector rule

-- Check afterwards (you should see the long list of event types in the first row):
--   select conname, pg_get_constraintdef(oid) from pg_constraint where conrelid = 'verdicts'::regclass and contype = 'c';
