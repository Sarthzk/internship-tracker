"""Fetcher health tracking, and the decision whether a fetch counts as successful (rule 1)."""

from __future__ import annotations

from datetime import datetime, timedelta

from tracker.models import HealthRecord

# A suspicious result (zero postings, or a sharp drop) is treated as a failure until it has lasted
# this long. `HealthRecord.zero_since` records when it first appeared.
ZERO_GRACE = timedelta(hours=24)
MAX_ERROR_LENGTH = 300
# A fall counts as sharp when postings halve and at least this many disappear.
DROP_MIN = 10
# `last_count` is the reference level for the drop check. It is rewritten only when the count
# leaves this band (20% or at least BAND_MIN postings), so normal drift does not touch health.json.
BAND_MIN = 5


def is_suspicious_drop(last_count: int, count: int) -> bool:
    """Zero after some postings, or postings halving by at least DROP_MIN: probably a site problem,
    not real closures (CLAUDE.md rule 1)."""
    if last_count <= 0:
        return False
    return count == 0 or (last_count - count >= DROP_MIN and count * 2 < last_count)


def record_fetch(
    previous: HealthRecord | None,
    company_slug: str,
    *,
    count: int | None,
    error: str | None,
    now: datetime,
) -> tuple[HealthRecord, bool]:
    """Update a company's health after one fetch.

    `count` is the number of postings the fetcher returned (before filtering), or None if it
    raised; `error` is the error message in that case. Returns the new record and whether the
    fetch counts as SUCCESSFUL, i.e. whether missing listings may be counted as misses.
    """
    record = (previous or HealthRecord(company_slug=company_slug)).model_copy()

    if error is not None or count is None:
        record.consecutive_failures += 1
        record.last_error = (error or "unknown error")[:MAX_ERROR_LENGTH]
        return record, False

    last = record.last_count
    if last is not None and is_suspicious_drop(last, count):
        if record.zero_since is None:
            record.zero_since = now
        if now - record.zero_since < ZERO_GRACE:
            record.consecutive_failures += 1
            what = "0 postings" if count == 0 else f"only {count} postings"
            record.last_error = f"returned {what} (previously {last})"
            return record, False

    record.consecutive_failures = 0
    record.last_error = None
    # A small change in the number of postings must not rewrite health.json (that would commit on
    # most runs), so the reference level only moves when the count leaves its band.
    if last is None or (last == 0) != (count == 0) or abs(count - last) > max(BAND_MIN, last // 5):
        record.last_count = count
    record.last_success = now.date()
    record.zero_since = None
    return record, True


# The outside timer starts a run every 10 minutes; a longer gap means it stopped for a while.
RUN_GAP_ALERT = timedelta(minutes=60)


def run_gap_message(previous_start: datetime | None, now: datetime, event: str) -> str | None:
    """Admin alert text when the previous run started more than RUN_GAP_ALERT ago, else None.

    Only the first run after a gap sees the long gap, so this fires once per outage without
    storing any state. `event` is how this run was started (GITHUB_EVENT_NAME)."""
    if previous_start is None or now - previous_start <= RUN_GAP_ALERT:
        return None
    minutes = int((now - previous_start).total_seconds() // 60)
    gap = f"{minutes // 60} h {minutes % 60} min" if minutes >= 60 else f"{minutes} min"
    if event == "schedule":
        cause = "This run came from GitHub's backup cron, so the 10-minute timer looks down."
    else:
        cause = "Runs are back now; check the 10-minute timer (cron-job.org) if this repeats."
    return f"⏰ internship-tracker did not run for {gap}. {cause}"


def should_send_crash_alert(previous_conclusion: str | None) -> bool:
    """Alert on the first failed run only: while the previous run also failed, stay quiet so a
    persistent crash does not send a message every 10 minutes."""
    return previous_conclusion != "failure"


def is_recovery(previous_conclusion: str | None) -> bool:
    """True when this run succeeded right after a failed one."""
    return previous_conclusion == "failure"


def is_previous_run(previous_number: int | None, this_number: int | None) -> bool:
    """True when the run found by the GitHub API is the one right before this run.

    Run numbers are sequential, so anything else means the API returned a stale or partial list
    (an alert once claimed a 13 hour gap while runs were happening every 10 minutes). Such
    data must not trigger or suppress alerts. Unknown numbers (local runs) are trusted."""
    if previous_number is None or this_number is None:
        return True
    return previous_number == this_number - 1
