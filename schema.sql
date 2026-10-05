-- Day-trader simulation: database schema for Supabase (Postgres)
-- Paste into Supabase: SQL Editor -> New query -> Run.  Run it ONCE.
--
-- To start over, uncomment and run these lines first (this DELETES all data):
-- drop table if exists blog_posts, daily_equity, trade_results, plans, verdicts, headlines, candidates, runs cascade;


-- 1. One row per execution of the app ------------------------------------------------
create table runs (
    id             bigint generated always as identity primary key,
    market_date    date        not null,
    started_at     timestamptz not null default now(),
    finished_at    timestamptz,
    data_is_live   boolean,                          -- true if the latest price candle was today's
    universe_size  int,                              -- stocks checked (about 100)
    passed_screen  int,                              -- stocks that passed the screener
    status         text        not null default 'running'
                   check (status in ('running', 'finished', 'failed')),
    error          text,
    settings       jsonb,                            -- thresholds used in this run
    model_name     text
);
create index runs_market_date_idx on runs (market_date);


-- 2. Movers found by the screener ----------------------------------------------------
create table candidates (
    id          bigint generated always as identity primary key,
    run_id      bigint not null references runs (id) on delete cascade,
    symbol      text   not null,
    rank        int,
    price       numeric(12, 2),
    change_pct  numeric(8, 2),                       -- % up vs yesterday's close
    rel_volume  numeric(8, 2),                       -- volume pace vs normal (1.0 = normal)
    avg_range   numeric(12, 2),                      -- typical daily high-low range, rupees
    unique (run_id, symbol)
);


-- 3. Headlines fetched for each mover ------------------------------------------------
create table headlines (
    id            bigint generated always as identity primary key,
    run_id        bigint not null references runs (id) on delete cascade,
    symbol        text   not null,
    position      int    not null,                   -- the [1], [2], ... number Gemini cites
    title         text   not null,
    source        text,
    published_at  timestamptz,
    url           text,
    unique (run_id, symbol, position)
);


-- 4. Gemini's judgement per stock ----------------------------------------------------
create table verdicts (
    id                 bigint generated always as identity primary key,
    run_id             bigint  not null references runs (id) on delete cascade,
    symbol             text    not null,
    has_catalyst       boolean not null,
    bullish            boolean not null,
    strength           text check (strength in ('strong', 'weak')),
    catalyst_type      text check (catalyst_type in ('earnings', 'broker_call', 'block_deal', 'sector_news', 'other')),
    reason             text,
    cited_positions    int[],                        -- which headline numbers it cited
    overruled_by_code  boolean not null default false,  -- true if our code rejected Gemini's catalyst
    on_watchlist       boolean not null default false,
    unique (run_id, symbol)
);


-- 5. Trade plans, including rejected and skipped ones --------------------------------
create table plans (
    id                bigint generated always as identity primary key,
    run_id            bigint not null references runs (id) on delete cascade,
    symbol            text   not null,
    status            text   not null check (status in ('accepted', 'rejected', 'skipped')),
    rejection_reason  text,                          -- why the rulebook said no, or why it was skipped
    entry             numeric(12, 2),
    stop              numeric(12, 2),
    target            numeric(12, 2),
    shares            int,
    cost              numeric(14, 2),
    max_loss          numeric(14, 2),
    max_gain          numeric(14, 2),
    gemini_reason     text,
    unique (run_id, symbol)
);


-- 6. What actually happened to each accepted plan (filled in later) ------------------
create table trade_results (
    id          bigint generated always as identity primary key,
    plan_id     bigint not null unique references plans (id) on delete cascade,
    outcome     text   not null check (outcome in ('target_hit', 'stop_hit', 'closed_at_end', 'not_filled')),
    exit_price  numeric(12, 2),
    exit_time   timestamptz,
    pnl         numeric(14, 2),                      -- profit (+) or loss (-), rupees
    settled_at  timestamptz not null default now()
);


-- 7. One row per day: the balance, for the equity curve ------------------------------
create table daily_equity (
    market_date       date primary key,
    starting_balance  numeric(14, 2) not null,
    ending_balance    numeric(14, 2) not null,
    pnl               numeric(14, 2) not null,
    trades            int not null default 0
);


-- 8. The daily blog -----------------------------------------------------------------
create table blog_posts (
    id             bigint generated always as identity primary key,
    market_date    date not null unique,
    run_id         bigint references runs (id) on delete set null,
    title          text not null,
    body_markdown  text not null,
    model_name     text,
    facts_used     jsonb,                            -- the exact facts the LLM was given (for audit)
    published      boolean not null default false,
    created_at     timestamptz not null default now()
);


-- Security: lock every table down -----------------------------------------------------
-- With row-level security ON and no policies, the public "anon" key can read and write NOTHING.
-- The app uses the secret "service_role" key, which is not blocked by these rules.
-- Later we will add read-only policies for just the tables the dashboard needs.
alter table runs          enable row level security;
alter table candidates    enable row level security;
alter table headlines     enable row level security;
alter table verdicts      enable row level security;
alter table plans         enable row level security;
alter table trade_results enable row level security;
alter table daily_equity  enable row level security;
alter table blog_posts    enable row level security;