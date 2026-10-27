"""Orchestration + CLI (python -m tracker)."""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx

from tracker import fetchers
from tracker.diff import MergeResult, merge
from tracker.filters import keep
from tracker.health import record_fetch
from tracker.http import make_client
from tracker.models import Company, Listing, RawPosting, load_companies
from tracker.storage import load_health, load_listings, save_health, save_listings

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@dataclass
class FetchOutcome:
    company: Company
    postings: list[RawPosting] | None = None
    error: str | None = None


@dataclass
class RunSummary:
    ok: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    merge: MergeResult = field(default_factory=lambda: MergeResult(listings=[]))
    wrote: bool = False

    @property
    def open_count(self) -> int:
        return sum(1 for li in self.merge.listings if li.status == "open")


async def fetch_company(company: Company, client: httpx.AsyncClient) -> FetchOutcome:
    """Never raises: one company failing must not crash the run (CLAUDE.md rule 8)."""
    fetch = fetchers.get_fetcher(company)
    if fetch is None:
        return FetchOutcome(company, error=f"no fetcher for ats={company.ats}")
    try:
        return FetchOutcome(company, postings=await fetch(company, client))
    except Exception as exc:  # noqa: BLE001 - deliberately broad, see docstring
        # Message only: httpx errors can embed request URLs.
        return FetchOutcome(company, error=f"{type(exc).__name__}: {exc}"[:300])


def build_listings(company: Company, postings: list[RawPosting], now: datetime) -> list[Listing]:
    """Filter to India tech internships and turn them into (not yet merged) Listings."""
    listings: dict[str, Listing] = {}
    for posting in postings:
        category = keep(posting)
        if category is None:
            continue
        listing_id = Listing.make_id(posting.source, company.slug, posting.external_id)
        listings[listing_id] = Listing(
            id=listing_id,
            company=company.name,
            company_slug=company.slug,
            title=posting.title,
            category=category,
            locations=posting.locations,
            is_remote=posting.is_remote,
            url=posting.url,
            source=posting.source,
            external_id=posting.external_id,
            date_posted=posting.date_posted,
            first_seen=now,
            last_seen=now.date(),
        )
    return list(listings.values())


async def run(
    companies: Sequence[Company],
    client: httpx.AsyncClient,
    data_dir: Path,
    *,
    dry_run: bool = False,
    now: datetime | None = None,
) -> RunSummary:
    now = now or datetime.now(UTC)
    enabled = [c for c in companies if c.enabled]
    outcomes = await asyncio.gather(*(fetch_company(c, client) for c in enabled))

    listings_path, health_path = data_dir / "listings.json", data_dir / "health.json"
    existing = load_listings(listings_path)
    health = load_health(health_path)
    summary = RunSummary()
    fetched: dict[str, list[Listing]] = {}
    succeeded: dict[str, bool] = {}

    for outcome in outcomes:
        slug = outcome.company.slug
        count = None if outcome.postings is None else len(outcome.postings)
        record, ok = record_fetch(health.get(slug), slug, count=count, error=outcome.error, now=now)
        health[slug] = record
        succeeded[slug] = ok
        if ok and outcome.postings is not None:
            fetched[slug] = build_listings(outcome.company, outcome.postings, now)
            summary.ok.append(slug)
        else:
            summary.failed[slug] = record.last_error or "unknown error"
            log.warning("%s: fetch failed: %s", slug, record.last_error)

    summary.merge = merge(existing, fetched, succeeded, now)
    if not dry_run:
        changed = save_listings(listings_path, summary.merge.listings)
        changed |= save_health(health_path, health)
        summary.wrote = changed
    return summary


def print_summary(summary: RunSummary, dry_run: bool) -> None:
    prefix = "[dry run] " if dry_run else ""
    print(f"{prefix}companies OK: {len(summary.ok)}, failed: {len(summary.failed)}")
    for slug, error in sorted(summary.failed.items()):
        print(f"  FAILED {slug}: {error}")
    print(
        f"{prefix}new: {len(summary.merge.new_ids)}, closed: {len(summary.merge.closed_ids)}, "
        f"reopened: {len(summary.merge.reopened_ids)}, total open: {summary.open_count}"
    )
    by_id = {li.id: li for li in summary.merge.listings}
    for listing_id in summary.merge.new_ids:
        li = by_id[listing_id]
        print(f"  NEW {li.company}: {li.title} ({'; '.join(li.locations)}) {li.url}")


async def _run_cli(dry_run: bool, data_dir: Path) -> int:
    companies = load_companies(data_dir / "companies.yaml")
    async with make_client() as client:
        summary = await run(companies, client, data_dir, dry_run=dry_run)
    print_summary(summary, dry_run)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tracker", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run", help="fetch, filter, diff and save")
    run_parser.add_argument("--dry-run", action="store_true", help="do not write any files")
    run_parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    run_parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return asyncio.run(_run_cli(args.dry_run, args.data_dir))
