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
