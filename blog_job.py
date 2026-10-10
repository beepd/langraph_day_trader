"""
The blog job: after the day is settled, write the day's blog post and save it as a DRAFT in the blog_posts table.

    python blog_job.py                        today's daily post (and, on a Friday, the weekly post dated Saturday)
    python blog_job.py daily 2026-10-12       one daily post for that trading day
    python blog_job.py weekly 2026-10-17      the weekly post for the week holding that date (dated its Saturday)
    python blog_job.py both 2026-10-16        daily and weekly
    add --force to replace a draft that is already saved (a published post is never replaced)

The scheduler starts this at BLOG_TIME (16:10 IST by default), after settlement. Rules of the job:
  * Safe to run twice: a post that is already saved is left alone (so your edits are never lost).
  * Nothing is ever published here. Every row is saved with published = false; you read it and flip it.
  * A draft that failed its checks is still saved (so you can see it), marked passed_checks = false, with the problems listed.
  * No post is written for a holiday, a skipped or failed day, or an incomplete week. The job stops quietly (weekly: tells you why).
  * If the day is not settled yet, the job exits with an error code so the scheduler tries again in a few minutes.
"""
import argparse
import logging
import sys
from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
log = logging.getLogger("blog_job")

RETRY, FAILED = "retry", "failed"                      # outcomes that make the job exit with an error, so the scheduler tries again


def existing_row(client, market_date: str):
    rows = client.table("blog_posts").select("id, published").eq("market_date", market_date).limit(1).execute().data
    return rows[0] if rows else None


def draft_row(post: dict, facts: dict, model_name: str) -> dict:
    """What is stored for a draft. published is always false here."""
    return {"market_date": facts["market_date"], "title": post["title"], "meta_description": post["meta_description"],
            "body_markdown": post["body_markdown"], "model_name": model_name, "facts_used": facts,
            "passed_checks": bool(post["ok"]), "problems": list(post["problems"]), "tries": post["tries"], "published": False}


def save_draft(client, post: dict, facts: dict, model_name: str, force: bool = False) -> str:
    """'saved', 'replaced', 'exists' (left alone) or 'locked' (published, never touched)."""
    row = existing_row(client, facts["market_date"])
    if row is None:
        client.table("blog_posts").insert(draft_row(post, facts, model_name)).execute()
        return "saved"
    if row["published"]:
        return "locked"
    if not force:
        return "exists"
    client.table("blog_posts").update(draft_row(post, facts, model_name)).eq("id", row["id"]).execute()
    return "replaced"


def post_date(kind: str, market_date: date) -> str:
    """The date a post is stored under: the trading day itself, or the Saturday after the week."""
    if kind == "daily":
        return market_date.isoformat()
    from blog_weekly import week_dates
    return week_dates(market_date)[1].isoformat()


def run_post(kind: str, market_date: date, client, generate, model_name: str, force: bool = False, facts_loader=None) -> dict:
    """Write and save one post. Returns {'outcome', 'detail', 'post'}; 'retry' and 'failed' are the outcomes worth trying again."""
    import blog_writer
    stored_under = post_date(kind, market_date)
    row = existing_row(client, stored_under)
    if row is not None and (row["published"] or not force):
        return {"outcome": "locked" if row["published"] else "exists", "detail": f"{kind} post {stored_under} is already saved", "post": None}
    if facts_loader is None:
        if kind == "daily":
            from blog_facts import collect_day_facts
            facts_loader = lambda: collect_day_facts(market_date, client)
        else:
            from blog_weekly import collect_week_facts
            facts_loader = lambda: collect_week_facts(market_date, client)
    facts = facts_loader()
    refused = blog_writer.refusal_reason(facts, kind)
    if refused:
        waiting = facts.get("day_status") == "not_settled_yet" or "not settled" in refused
        return {"outcome": RETRY if waiting else "nothing_to_write", "detail": refused, "post": None}
    post = blog_writer.write_post(facts, generate, kind)
    if not post.get("title") or not post.get("body_markdown"):
        return {"outcome": FAILED, "detail": "the writer produced nothing: " + "; ".join(post["problems"]), "post": post}
    result = save_draft(client, post, facts, model_name, force)
    return {"outcome": result, "detail": f"{kind} post {facts['market_date']}: " + ("passed all checks" if post["ok"] else "needs a close look"), "post": post}


def tell(kind: str, market_date: date, result: dict) -> None:
    """A short Telegram note. Never raises."""
    try:
        import messages as msg
        from notify import send_telegram
        post, outcome = result["post"], result["outcome"]
        if outcome in ("saved", "replaced") and post:
            send_telegram(msg.blog_draft(kind, post_date(kind, market_date), post["title"], post["ok"], post["problems"], outcome == "replaced"))
        elif outcome == "nothing_to_write" and kind == "weekly":
            send_telegram(msg.blog_nothing(kind, post_date(kind, market_date), result["detail"]))
    except Exception as error:
        log.warning("Could not send the blog note: %s", error)


def kinds_for(arg: str, today: date) -> list:
    if arg == "auto":
        return ["daily"] + (["weekly"] if today.weekday() == 4 else [])      # the week is complete after Friday's settlement
    return ["daily", "weekly"] if arg == "both" else [arg]


def main() -> None:
    parser = argparse.ArgumentParser(description="Writes the blog draft(s) for a settled day and saves them (never published).")
    parser.add_argument("kind", nargs="?", default="auto", choices=["auto", "daily", "weekly", "both"])
    parser.add_argument("day", nargs="?", help="YYYY-MM-DD (default: today, India time)")
    parser.add_argument("--force", action="store_true", help="replace an existing unpublished draft")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    day = date.fromisoformat(args.day) if args.day else datetime.now(IST).date()

    from blog_writer import make_generate
    from llm_setup import MODEL, PROVIDER, build_llm
    from storage import get_client
    client, generate, model_name = get_client(), make_generate(build_llm()), f"{PROVIDER}:{MODEL}"
    trouble = False
    for kind in kinds_for(args.kind, day):
        result = run_post(kind, day, client, generate, model_name, args.force)
        print(f"{kind}: {result['outcome']}. {result['detail']}")
        if result["post"] and result["post"]["problems"]:
            print("   problems: " + "; ".join(result["post"]["problems"]))
        tell(kind, day, result)
        trouble = trouble or result["outcome"] in (RETRY, FAILED)
    sys.exit(1 if trouble else 0)


if __name__ == "__main__":
    main()
