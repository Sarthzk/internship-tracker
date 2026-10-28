"""Fetcher health tracking, and the decision whether a fetch counts as successful (rule 1)."""

from __future__ import annotations

from datetime import datetime, timedelta

from tracker.models import HealthRecord

# A zero-postings result after a non-zero one is treated as a failure until it has lasted this long.
ZERO_GRACE = timedelta(hours=24)
MAX_ERROR_LENGTH = 300


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

    if count == 0 and (record.last_count or 0) > 0:
        if record.zero_since is None:
            record.zero_since = now
        if now - record.zero_since < ZERO_GRACE:
            record.consecutive_failures += 1
            record.last_error = f"returned 0 postings (previously {record.last_count})"
            return record, False

    record.consecutive_failures = 0
    record.last_error = None
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
