"""Which companies are due in this run. Pure and stateless: no stored "last checked" times."""

from __future__ import annotations

import zlib
from datetime import datetime

from tracker.models import Company, HealthRecord

RUN_INTERVAL_MINUTES = 10
# A company that failed is tried again in the very next run, not at its next slot, for this many
# failures in a row (about an hour). Beyond that it is left to its normal schedule, so a site that
# is really down is not hammered every ten minutes.
RETRY_SOON_FAILURES = 6


def is_due(company: Company, now: datetime) -> bool:
    """True if `company` should be fetched in the run that starts at `now`.

    The day is cut into 10-minute slots; a company with `check_every_minutes: 30` runs in one slot
    out of three. A per-company offset (a stable hash of its slug) spreads such companies over
    the slots so they do not all land in the same run. Companies on the default interval are
    always due."""
    every = company.check_every_minutes // RUN_INTERVAL_MINUTES
    if every <= 1:
        return True
    slot = (now.hour * 60 + now.minute) // RUN_INTERVAL_MINUTES
    return (slot + zlib.crc32(company.slug.encode())) % every == 0


def retry_soon(record: HealthRecord | None) -> bool:
    """True if the company's last fetch failed recently enough to be worth trying again now.

    Sites that throttle shared addresses (Workday answers HTTP 429 to GitHub's runners about half
    the time) succeed on a later attempt, so waiting 30-60 minutes for the next slot only delays
    postings."""
    return record is not None and 0 < record.consecutive_failures <= RETRY_SOON_FAILURES
