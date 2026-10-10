-- Migration 009: remember where each post lives on Blogger.
-- Run once in the Supabase SQL editor. Safe to run twice.
alter table blog_posts add column if not exists blogger_post_id    text;          -- Blogger's id for the post (set when the draft is created there)
alter table blog_posts add column if not exists blogger_url        text;          -- the post's address on Blogger (a draft has no public address yet)
alter table blog_posts add column if not exists blogger_status     text;          -- 'DRAFT' or 'LIVE', as last seen on Blogger
alter table blog_posts add column if not exists sent_to_blogger_at timestamptz;   -- when the draft was created there
alter table blog_posts add column if not exists published_at       timestamptz;   -- when it was seen live on Blogger
