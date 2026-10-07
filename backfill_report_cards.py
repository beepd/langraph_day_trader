"""
Backfill: work out the report card for past days that do not have one yet.

    python backfill_report_cards.py            grade every past day that is missing its report card
    python backfill_report_cards.py --force    redo them all (safe: existing rows are replaced, never duplicated)

Yahoo keeps only about 60 days of 5-minute prices, so older days cannot be graded. Today is skipped: the settlement
job makes today's report card after 3:35 PM. Needs migration 004 on the database it points at.
"""
import sys
from datetime import date, datetime

from settle_day import IST, record_report_card
from storage import get_client

MAX_AGE_DAYS = 55            # Yahoo's 5-minute history is limited to about 60 days


def main() -> None:
    force = "--force" in sys.argv
    client = get_client()
    runs = (client.table("runs").select("id, market_date, started_at").eq("status", "finished")
            .eq("data_is_live", True).order("id", desc=True).execute().data)
    official = {}
    for run in runs:                                   # newest first, so the first one seen per day is the official run
        official.setdefault(run["market_date"], run)
    done = {row["run_id"] for row in client.table("candidate_outcomes").select("run_id").execute().data}
    today = datetime.now(IST).date()

    graded = 0
    for day in sorted(official):
        run, day_date = official[day], date.fromisoformat(day)
        label = f"{day} (run #{run['id']})"
        if day_date >= today:
            print(f"{label}: skipped, the day is not over (settlement does it after 3:35 PM)")
        elif (today - day_date).days > MAX_AGE_DAYS:
            print(f"{label}: skipped, too old for Yahoo's 5-minute data")
        elif run["id"] in done and not force:
            print(f"{label}: already has a report card (use --force to redo)")
        else:
            print(f"{label}:", end=" ")
            try:
                started_at = datetime.fromisoformat(run["started_at"]).astimezone(IST)
                record_report_card(run["id"], day_date, started_at, period="60d")
                graded += 1
            except Exception as error:                 # one bad day must not stop the others
                print(f"FAILED ({type(error).__name__}: {error})")
    print(f"\nDone: {graded} day(s) graded.")


if __name__ == "__main__":
    main()
