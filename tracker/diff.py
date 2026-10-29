"""Merge fetched postings into existing listings (CLAUDE.md rule 1). Pure: no I/O."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from tracker.models import Listing, Status

CLOSE_AFTER_MISSES = 3
RETAIN_CLOSED_DAYS = 180  # the archive page shows 90; the rest is kept as a buffer


@dataclass
class MergeResult:
    listings: list[Listing]
    new_ids: list[str] = field(default_factory=list)
    closed_ids: list[str] = field(default_factory=list)
    reopened_ids: list[str] = field(default_factory=list)


def prune_closed(
    listings: list[Listing], now: datetime, days: int = RETAIN_CLOSED_DAYS
) -> list[Listing]:
    """Drop listings that closed more than `days` ago, so listings.json does not grow forever."""
    cutoff = now - timedelta(days=days)
    return [
        li
        for li in listings
        if not (li.status == Status.closed and li.closed_at is not None and li.closed_at < cutoff)
    ]


def merge(
    existing: list[Listing],
    fetched_by_company: dict[str, list[Listing]],
    succeeded_by_company: dict[str, bool],
    now: datetime,
    *,
    close_after: int = CLOSE_AFTER_MISSES,
) -> MergeResult:
    """`fetched_by_company` holds freshly built listings (already filtered) per company slug.

    Companies missing from `succeeded_by_company` were not fetched this run and are left alone.
    Companies whose fetch failed keep their listings untouched; their fetched list is ignored.
    """
    today = now.date()
    by_id = {listing.id: listing.model_copy(deep=True) for listing in existing}
    result = MergeResult(listings=[])

    for slug, succeeded in succeeded_by_company.items():
        if not succeeded:
            continue
        seen: set[str] = set()
        for fresh in fetched_by_company.get(slug, []):
            seen.add(fresh.id)
            current = by_id.get(fresh.id)
            if current is None:
                by_id[fresh.id] = fresh.model_copy(
                    update={"first_seen": now, "last_seen": today, "notified": False}
                )
                result.new_ids.append(fresh.id)
                continue
            if current.status == Status.closed:
                result.reopened_ids.append(current.id)
            current.title = fresh.title
            current.category = fresh.category
            current.locations = fresh.locations
            current.is_remote = fresh.is_remote
            current.url = fresh.url
            current.date_posted = fresh.date_posted or current.date_posted
            current.last_seen = today
            current.missed_runs = 0
            current.status = Status.open
            current.closed_at = None

        for listing in by_id.values():
            if listing.company_slug != slug or listing.id in seen:
                continue
            if listing.status != Status.open:
                continue
            listing.missed_runs += 1
            if listing.missed_runs >= close_after:
                listing.status = Status.closed
                listing.closed_at = now
                result.closed_ids.append(listing.id)

    result.listings = sorted(by_id.values(), key=lambda li: li.id)
    return result
