import logging
import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
IST = timezone(timedelta(hours=5, minutes=30))
log = logging.getLogger("storage")


def get_client():
    """Connect only when we actually save, so a bad key never stops the research."""
    return create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))


def get_available_balance(default_balance: float) -> tuple[float, str]:
    """Latest ending balance from daily_equity. If there is no history yet, the starting balance."""
    rows = (get_client().table("daily_equity").select("market_date, ending_balance")
            .order("market_date", desc=True).limit(1).execute().data)
    if not rows:
        return float(default_balance), "no history yet, using the starting balance"
    return float(rows[0]["ending_balance"]), f"ending balance of {rows[0]['market_date']}"


def _money(value):
    return None if value is None else float(round(value, 2))


def start_run(started_at: datetime, model_name: str):
    """Create the run's row at the very start, so even a crashed run leaves a trace. Returns its id, or None."""
    try:
        row = {"market_date": started_at.astimezone(IST).date().isoformat(), "started_at": started_at.isoformat(),
               "status": "running", "model_name": model_name}
        return get_client().table("runs").insert(row).execute().data[0]["id"]
    except Exception as error:
        log.warning("Could not create the run record in Supabase: %s", error)
        return None


def mark_run(run_id, status: str, note: str | None = None, error: str | None = None) -> None:
    """Give a run its final status ('failed' or 'skipped'). Never raises: the app must keep going."""
    if run_id is None:
        return
    try:
        values = {"status": status, "finished_at": datetime.now(IST).isoformat(),
                  "note": note, "error": error[:500] if error else None}
        # only a run that is still 'running' can be changed, so a finished run is never overwritten
        get_client().table("runs").update(values).eq("id", run_id).eq("status", "running").execute()
    except Exception as exc:
        log.warning("Could not update run #%s in Supabase: %s", run_id, exc)


def _verdict_row(run_id: int, symbol: str, v, on_watchlist: bool) -> dict:
    row = {
        "run_id": run_id, "symbol": symbol,
        "has_catalyst": v.has_catalyst, "bullish": v.bullish,
        "strength": v.strength, "catalyst_type": v.catalyst_type,
        "reason": v.reason, "cited_positions": v.source_numbers,
        "overruled_by_code": (v.reason or "").startswith("REJECTED by code"),
        "on_watchlist": on_watchlist,
    }
    if hasattr(v, "event_status"):          # a checklist verdict: its extra answers need migration 006 on the database
        row.update({"event_status": v.event_status, "has_number": v.has_number, "checklist_notes": v.checklist_notes})
    return row


def check_checklist_columns() -> None:
    """The checklist analyst saves three extra columns. Stop BEFORE any trading if the database does not have them yet,
    because a run that cannot be saved cannot be settled."""
    try:
        get_client().table("verdicts").select("event_status, has_number, checklist_notes").limit(1).execute()
    except Exception as error:
        raise RuntimeError("The checklist analyst needs sql/migration_006_checklist.sql applied to this database "
                           f"(could not read the new verdicts columns: {error})") from error


def save_run_details(run_id: int, result: dict, settings: dict) -> None:
    """Save everything a finished run produced, then mark it 'finished'. If anything fails, it is marked 'failed'."""
    client = get_client()
    stats = result.get("stats", {})
    try:
        candidate_rows = [{
            "run_id": run_id, "symbol": symbol, "rank": rank,
            "price": _money(result["prices"][symbol]),
            "change_pct": _money(result["changes"][symbol]),
            "rel_volume": _money(result["rel_volumes"][symbol]),
            "avg_range": _money(result["avg_ranges"][symbol]),
        } for rank, symbol in enumerate(result["stocks"], start=1)]

        headline_rows = [{
            "run_id": run_id, "symbol": symbol, "position": position,
            "title": h["title"], "source": h["source"] or None,
            "published_at": h["published_at"], "url": h["url"] or None,
        } for symbol, items in result["headlines"].items() for position, h in enumerate(items, start=1)]

        verdict_rows = [_verdict_row(run_id, symbol, v, symbol in result["watchlist"])
                        for symbol, v in result["verdicts"].items()]

        plan_rows = [{
            "run_id": run_id, "symbol": p["symbol"], "status": p["status"],
            "rejection_reason": p.get("rejection_reason"),
            "entry": _money(p.get("entry")), "stop": _money(p.get("stop")), "target": _money(p.get("target")),
            "shares": p.get("shares"), "cost": _money(p.get("cost")),
            "max_loss": _money(p.get("max_loss")), "max_gain": _money(p.get("max_gain")),
            "gemini_reason": p.get("gemini_reason"),
        } for p in result.get("plan_log", [])]

        for table, rows in [("candidates", candidate_rows), ("headlines", headline_rows),
                            ("verdicts", verdict_rows), ("plans", plan_rows)]:
            if rows:
                client.table(table).insert(rows).execute()

        client.table("runs").update({
            "status": "finished", "finished_at": datetime.now(IST).isoformat(),
            "data_is_live": bool(stats.get("live", 0)), "universe_size": stats.get("universe"),
            "passed_screen": stats.get("passed_screen"), "settings": settings,
        }).eq("id", run_id).execute()
    except Exception as error:
        mark_run(run_id, "failed", error=str(error))
        raise


def get_candidates(run_id: int) -> list:
    """The stocks the screener passed for a run (symbol, price, avg_range, rank), best first."""
    return (get_client().table("candidates").select("symbol, price, avg_range, rank")
            .eq("run_id", run_id).order("rank").execute().data)


def save_candidate_outcomes(run_id: int, reports: dict) -> int:
    """Save (or replace) the report-card rows of a run. reports = {symbol: report}. Returns how many rows were saved."""
    if not reports:
        return 0

    def as_text(value):                        # a time becomes ISO text, so it can travel as JSON
        return value.isoformat() if hasattr(value, "isoformat") else value

    rows = [{
        "run_id": run_id, "symbol": symbol,
        "entry_price": r.get("entry_price"), "close_price": r["close_price"],
        "return_pct": r["return_pct"], "max_up_pct": r["max_up_pct"], "max_down_pct": r["max_down_pct"],
        "candles_used": r["candles_used"],
        "std_stop": r["std_stop"], "std_target": r["std_target"], "std_outcome": r["std_outcome"],
        "std_exit_price": r["std_exit_price"], "std_exit_time": as_text(r["std_exit_time"]),
        "std_return_pct": r["std_return_pct"],
    } for symbol, r in reports.items()]
    get_client().table("candidate_outcomes").upsert(rows, on_conflict="run_id,symbol").execute()
    return len(rows)


def get_watchlist_symbols(run_id: int) -> set:
    """The stocks the analyst put on the watchlist in a run."""
    rows = (get_client().table("verdicts").select("symbol").eq("run_id", run_id)
            .eq("on_watchlist", True).execute().data)
    return {row["symbol"] for row in rows}