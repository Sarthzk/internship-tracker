"""Which companies are due in this run. Pure and stateless: no stored "last checked" times."""

from __future__ import annotations

import zlib
from datetime import datetime

from tracker.models import Company

RUN_INTERVAL_MINUTES = 10


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
