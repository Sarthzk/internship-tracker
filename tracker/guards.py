"""Safety checks on a run's results. Pure functions: no I/O."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Collection

from tracker.diff import MergeResult
from tracker.models import Status

# Fewer than this many new AND vanished listings at one company is ordinary turnover.
CHURN_MIN = 5


def find_id_churn(
    result: MergeResult, first_fetch: Collection[str], min_count: int = CHURN_MIN
) -> dict[str, tuple[list[str], int]]:
    """Companies whose listings were replaced wholesale in one run:
    slug -> (ids of the new listings, how many known listings vanished).

    A burst of new internships alone is legitimate (a company opens its whole summer program).
    New ones appearing while just as many known ones vanish means the site probably changed its
    ids or a fetcher changed, and alerting on each "new" listing would be a flood of repeats.
    A company fetched for the first time is never churn (it gets one summary instead)."""
    by_id = {li.id: li for li in result.listings}
    new_by_company: dict[str, list[str]] = defaultdict(list)
    for listing_id in result.new_ids:
        listing = by_id[listing_id]
        if listing.company_slug not in first_fetch:
            new_by_company[listing.company_slug].append(listing_id)
    vanished = Counter(
        li.company_slug for li in result.listings if li.status == Status.open and li.missed_runs > 0
    )
    return {
        slug: (ids, vanished[slug])
        for slug, ids in new_by_company.items()
        if len(ids) >= min_count and vanished[slug] >= min_count
    }
