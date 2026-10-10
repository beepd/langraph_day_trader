-- Migration 008: what the automatic blog job stores next to each draft.
-- Run once in the Supabase SQL editor. Safe to run twice.
alter table blog_posts add column if not exists meta_description text;                       -- the search-result description
alter table blog_posts add column if not exists passed_checks    boolean not null default false;   -- did the draft pass every automatic check?
alter table blog_posts add column if not exists problems         jsonb   not null default '[]'::jsonb;   -- what the checks complained about
alter table blog_posts add column if not exists tries            int;                        -- how many times the writer was asked
-- market_date stays unique: a daily post is dated its trading day, a weekly post the Saturday after its week.
