"""
The blog job: after the day is settled, write the day's blog post and save it as a DRAFT in the blog_posts table.

    python blog_job.py                        today's daily post (and, on a Friday, the weekly post dated Saturday)
    python blog_job.py daily 2026-10-12       one daily post for that trading day
    python blog_job.py weekly 2026-10-17      the weekly post for the week holding that date (dated its Saturday)
    python blog_job.py both 2026-10-16        daily and weekly
    add --force to replace a draft that is already saved (a published post is never replaced)

If Blogger is set up (see blogger_publish.py), each saved draft is also created on Blogger as a DRAFT (never live): you read and fix it
there and press Publish yourself. A post you published in Blogger is noticed and marked published here.

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


def send_to_blogger(client, stored_under: str, update_existing: bool, push) -> dict:
    """Create (or refresh) the Blogger draft for a saved row. Never raises: a Blogger problem is reported, the saved draft stays safe."""
    import blogger_publish
    if push is None:
        push = blogger_publish.configured()
    if not push:
        return None
    try:
        row = client.table("blog_posts").select("*").eq("market_date", stored_under).limit(1).execute().data[0]
        result = blogger_publish.push_row(client, row, update_existing)
        result["meta_description"] = row.get("meta_description")
        return result
    except Exception as error:
        log.warning("Could not send %s to Blogger: %s", stored_under, error)
        return {"action": "failed", "detail": str(error)[:300]}


def run_post(kind: str, market_date: date, client, generate, model_name: str, force: bool = False, facts_loader=None, push=None) -> dict:
    """Write and save one post. Returns {'outcome', 'detail', 'post', 'blogger'}; 'retry' and 'failed' are the outcomes worth trying again.
    push: None = send to Blogger if it is set up, False = never (used by the tests)."""
    import blog_writer
    stored_under = post_date(kind, market_date)
    row = existing_row(client, stored_under)
    if row is not None and (row["published"] or not force):
        locked = bool(row["published"])
        blogger = None if locked else send_to_blogger(client, stored_under, False, push)       # a missing Blogger draft is created; an existing one is left alone
        return {"outcome": "locked" if locked else "exists", "detail": f"{kind} post {stored_under} is already saved", "post": None, "blogger": blogger}
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
        return {"outcome": RETRY if waiting else "nothing_to_write", "detail": refused, "post": None, "blogger": None}
    post = blog_writer.write_post(facts, generate, kind)
    if not post.get("title") or not post.get("body_markdown"):
        return {"outcome": FAILED, "detail": "the writer produced nothing: " + "; ".join(post["problems"]), "post": post, "blogger": None}
    result = save_draft(client, post, facts, model_name, force)
    blogger = send_to_blogger(client, facts["market_date"], result == "replaced", push) if result in ("saved", "replaced") else None
    return {"outcome": result, "detail": f"{kind} post {facts['market_date']}: " + ("passed all checks" if post["ok"] else "needs a close look"), "post": post, "blogger": blogger}


def tell(kind: str, market_date: date, result: dict) -> None:
    """A short Telegram note. Never raises."""
    try:
        import messages as msg
        from notify import send_telegram
        post, outcome, blogger = result["post"], result["outcome"], result.get("blogger") or {}
        if outcome in ("saved", "replaced") and post:
            send_telegram(msg.blog_draft(kind, post_date(kind, market_date), post["title"], post["ok"], post["problems"], outcome == "replaced",
                                         blogger.get("edit_url") if blogger.get("action") in ("created", "updated") else None,
                                         post["meta_description"], blogger.get("detail") if blogger.get("action") == "failed" else None))
        elif outcome == "exists" and blogger.get("action") == "created":                    # a draft that was saved earlier but never reached Blogger
            send_telegram(msg.blog_sent_late(kind, post_date(kind, market_date), blogger["edit_url"], blogger.get("meta_description")))
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
    import blogger_publish
    if blogger_publish.configured():
        try:
            live = blogger_publish.sync_status(client)             # posts you published in Blogger are marked published here
            if live:
                print(f"{live} post(s) found live on Blogger and marked published.")
        except Exception as error:
            log.warning("Could not check Blogger for published posts: %s", error)
    else:
        print("Blogger is not set up (no BLOGGER_* settings in .env): drafts are saved to the database only.")
    trouble = False
    for kind in kinds_for(args.kind, day):
        result = run_post(kind, day, client, generate, model_name, args.force)
        print(f"{kind}: {result['outcome']}. {result['detail']}")
        if result.get("blogger"):
            b = result["blogger"]
            print("   blogger: " + b["action"] + ("" if b["action"] == "already_sent" else " " + b.get("edit_url", b.get("detail", ""))))
        if result["post"] and result["post"]["problems"]:
            print("   problems: " + "; ".join(result["post"]["problems"]))
        tell(kind, day, result)
        trouble = trouble or result["outcome"] in (RETRY, FAILED) or (result.get("blogger") or {}).get("action") == "failed"
    sys.exit(1 if trouble else 0)


if __name__ == "__main__":
    main()
