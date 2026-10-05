"""
Scheduler: runs the morning trading job and the end-of-day settlement job on every weekday (India time).

    python scheduler.py                 run forever (this is what you deploy)
    python scheduler.py --dry-run       print the next few run times and exit
    python scheduler.py --now morning   run the morning job once, right now, then exit
    python scheduler.py --now settle    run the settlement job once, right now, then exit

It starts each job as a separate program (morning_run.py and settle_day.py), so a crash in a job can never stop
the scheduler, and neither job needs to know anything about scheduling. Weekends are skipped here; market
holidays are handled by the jobs themselves (the morning job's preflight stops, settlement finds no run).

Settings (all optional, in .env or the environment):
    MORNING_TIME=09:35   SETTLE_TIME=15:40   (India time, 24-hour clock)
    MORNING_SCRIPT=morning_run.py   SETTLE_SCRIPT=settle_day.py
"""
import argparse
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from datetime import time as dtime
from pathlib import Path

import messages as msg
from notify import send_telegram

IST = timezone(timedelta(hours=5, minutes=30))          # India has no daylight saving, so a fixed offset is exact
BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
log = logging.getLogger("scheduler")


def parse_clock(text: str) -> dtime:
    hours, minutes = text.strip().split(":")
    return dtime(int(hours), int(minutes))


@dataclass
class Job:
    name: str
    script: str
    at: dtime
    timeout_minutes: float        # kill the job if it runs longer than this
    attempts: int                 # how many times to try if it fails
    retry_wait_minutes: float


def load_jobs() -> list[Job]:
    return [
        Job("morning", os.getenv("MORNING_SCRIPT", "morning_run.py"), parse_clock(os.getenv("MORNING_TIME", "09:35")),
            timeout_minutes=20, attempts=2, retry_wait_minutes=5),
        Job("settle", os.getenv("SETTLE_SCRIPT", "settle_day.py"), parse_clock(os.getenv("SETTLE_TIME", "15:40")),
            timeout_minutes=15, attempts=3, retry_wait_minutes=10),     # safe to repeat: settlement skips finished work
    ]


def next_run_time(job: Job, after: datetime) -> datetime:
    """The next weekday moment at which this job is due, strictly after 'after'."""
    candidate = after.replace(hour=job.at.hour, minute=job.at.minute, second=0, microsecond=0)
    if candidate <= after:
        candidate += timedelta(days=1)
    while candidate.weekday() >= 5:                      # 5 = Saturday, 6 = Sunday
        candidate += timedelta(days=1)
    return candidate


def child_environment() -> dict:
    """Environment for the jobs. The testing switches are forced OFF, so a leftover line in .env cannot
    make a scheduled run skip the market-closed guard (the jobs never override variables that already exist)."""
    env = dict(os.environ)
    env.update({"FORCE_RUN": "0", "FORCE_SETTLE": "0", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    return env


def run_job(job: Job) -> bool:
    """Run one job as its own program, with a time limit and retries. Returns True if it succeeded."""
    LOG_DIR.mkdir(exist_ok=True)
    for attempt in range(1, job.attempts + 1):
        started = datetime.now(IST)
        log.info("Starting %s (%s), attempt %d of %d", job.name, job.script, attempt, job.attempts)
        try:
            done = subprocess.run([sys.executable, str(BASE_DIR / job.script)], cwd=BASE_DIR, env=child_environment(),
                                  capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  timeout=job.timeout_minutes * 60)
            output, outcome, ok = done.stdout + done.stderr, f"exit code {done.returncode}", done.returncode == 0
        except subprocess.TimeoutExpired as error:
            partial = error.stdout or ""
            output = partial.decode("utf-8", "replace") if isinstance(partial, bytes) else partial
            outcome, ok = f"timed out after {job.timeout_minutes:g} minutes", False

        log_file = LOG_DIR / f"{job.name}_{started:%Y-%m-%d_%H%M}_try{attempt}.log"
        log_file.write_text(output, encoding="utf-8")
        seconds = (datetime.now(IST) - started).total_seconds()
        if ok:
            log.info("Finished %s OK in %.0f seconds (output saved to %s)", job.name, seconds, log_file.name)
            return True
        last_lines = " | ".join(output.strip().splitlines()[-3:])
        log.error("%s FAILED (%s) after %.0f seconds. Last output: %s", job.name, outcome, seconds, last_lines)
        if attempt < job.attempts:
            log.info("Trying again in %g minutes", job.retry_wait_minutes)
            time.sleep(job.retry_wait_minutes * 60)
    log.error("%s: giving up for today after %d attempts. See the log files in %s", job.name, job.attempts, LOG_DIR)
    send_telegram(msg.gave_up(job.name, job.attempts, outcome))
    return False


def run_forever(jobs: list[Job]) -> None:
    log.info("Scheduler started. %s", "; ".join(f"{j.name} at {j.at:%H:%M} IST" for j in jobs))
    while True:
        now = datetime.now(IST)
        job = min(jobs, key=lambda j: next_run_time(j, now))
        due = next_run_time(job, now)
        log.info("Next: %s at %s IST", job.name, f"{due:%A %d %b %H:%M}")
        while True:
            remaining = (due - datetime.now(IST)).total_seconds()
            if remaining <= 0:
                break
            time.sleep(min(30, remaining))               # wake often, so a VM pause or clock change cannot make us late
        run_job(job)


def main() -> None:
    parser = argparse.ArgumentParser(description="Runs the trading jobs on schedule.")
    parser.add_argument("--now", choices=["morning", "settle"], help="run one job immediately and exit")
    parser.add_argument("--dry-run", action="store_true", help="print the next run times and exit")
    args = parser.parse_args()

    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_DIR / "scheduler.log", encoding="utf-8")])
    jobs = load_jobs()

    if args.dry_run:
        moment = datetime.now(IST)
        print(f"Time now: {moment:%A %d %b %Y %H:%M} IST. Upcoming runs:")
        upcoming = []
        for _ in range(6):
            job = min(jobs, key=lambda j: next_run_time(j, moment))
            moment = next_run_time(job, moment)
            upcoming.append(f"   {moment:%A %d %b %H:%M}  {job.name:<8} ({job.script})")
        print("\n".join(upcoming))
        return
    if args.now:
        sys.exit(0 if run_job(next(j for j in jobs if j.name == args.now)) else 1)
    try:
        run_forever(jobs)
    except KeyboardInterrupt:
        log.info("Scheduler stopped.")


if __name__ == "__main__":
    main()