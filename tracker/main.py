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
from tracker.models import Company, HealthRecord, Listing, RawPosting, Status, load_companies
from tracker.notify import (
    CallMeBot,
    Sender,
    deliver,
    deliver_health_alerts,
    format_crash,
    format_tracking_started,
    plan_alerts,
    plan_health_alerts,
)
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
    alerts_sent: int = 0  # listings delivered to WhatsApp this run
    alerts_pending: int = 0  # listings still waiting (no sender, or a send failed)

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
    sender: Sender | None = None,
    pause: float = 2.0,
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
    first_fetch: set[str] = set()  # companies fetched successfully for the very first time

    for outcome in outcomes:
        slug = outcome.company.slug
        count = None if outcome.postings is None else len(outcome.postings)
        previous = health.get(slug)
        record, ok = record_fetch(previous, slug, count=count, error=outcome.error, now=now)
        health[slug] = record
        succeeded[slug] = ok
        if ok and (previous is None or previous.last_success is None):
            first_fetch.add(slug)
        if ok and outcome.postings is not None:
            fetched[slug] = build_listings(outcome.company, outcome.postings, now)
            summary.ok.append(slug)
        else:
            summary.failed[slug] = record.last_error or "unknown error"
            log.warning("%s: fetch failed: %s", slug, record.last_error)

    summary.merge = merge(existing, fetched, succeeded, now)
    if not dry_run:
        await _notify(summary, health, enabled, first_fetch, sender, pause)
        changed = save_listings(listings_path, summary.merge.listings)
        changed |= save_health(health_path, health)
        summary.wrote = changed
    return summary


async def _notify(
    summary: RunSummary,
    health: dict[str, HealthRecord],
    enabled: Sequence[Company],
    first_fetch: set[str],
    sender: Sender | None,
    pause: float,
) -> None:
    """Send WhatsApp alerts and record `notified` / `failure_alerted` before the data is saved."""
    listings = summary.merge.listings
    names = {c.slug: c.name for c in enabled}

    # A company seen for the first time gets one summary instead of one message per listing.
    if first_fetch:
        counts = {names[s]: 0 for s in first_fetch}
        for li in listings:
            if li.company_slug in first_fetch and li.status == Status.open and not li.notified:
                li.notified = True
                counts[li.company] += 1
        if sender is not None and not await sender.send(format_tracking_started(counts)):
            log.warning("could not send the 'now tracking' summary")

    pending = [li for li in listings if li.status == Status.open and not li.notified]
    if sender is None:
        summary.alerts_pending = len(pending)
        return
    delivered = await deliver(sender, plan_alerts(pending), pause)
    for li in pending:
        if li.id in delivered:
            li.notified = True
    summary.alerts_sent = len(delivered)
    summary.alerts_pending = len(pending) - len(delivered)

    await deliver_health_alerts(sender, plan_health_alerts(health, names), health, pause)


def print_summary(summary: RunSummary, dry_run: bool) -> None:
    prefix = "[dry run] " if dry_run else ""
    print(f"{prefix}companies OK: {len(summary.ok)}, failed: {len(summary.failed)}")
    for slug, error in sorted(summary.failed.items()):
        print(f"  FAILED {slug}: {error}")
    print(
        f"{prefix}new: {len(summary.merge.new_ids)}, closed: {len(summary.merge.closed_ids)}, "
        f"reopened: {len(summary.merge.reopened_ids)}, total open: {summary.open_count}"
    )
    if not dry_run:
        print(f"WhatsApp: {summary.alerts_sent} sent, {summary.alerts_pending} waiting")
    by_id = {li.id: li for li in summary.merge.listings}
    for listing_id in summary.merge.new_ids:
        li = by_id[listing_id]
        print(f"  NEW {li.company}: {li.title} ({'; '.join(li.locations)}) {li.url}")


async def _run_cli(dry_run: bool, data_dir: Path) -> int:
    companies = load_companies(data_dir / "companies.yaml")
    async with make_client() as client:
        sender = None if dry_run else CallMeBot.from_env(client)
        try:
            summary = await run(companies, client, data_dir, dry_run=dry_run, sender=sender)
        except Exception as exc:
            if sender is not None:
                await sender.send(format_crash(exc))
            raise
    print_summary(summary, dry_run)
    return 0


async def _check_cli(slugs: list[str], data_dir: Path) -> int:
    """Fetch the named companies (enabled or not) and print counts. Saves and sends nothing.

    Used by the cloud-check workflow to see whether a site answers from GitHub's servers.
    """
    companies = {c.slug: c for c in load_companies(data_dir / "companies.yaml")}
    unknown = [s for s in slugs if s not in companies]
    if unknown:
        print(f"unknown company slugs: {', '.join(unknown)}")
        return 2
    async with make_client() as client:
        outcomes = await asyncio.gather(*(fetch_company(companies[s], client) for s in slugs))
    failed = 0
    for outcome in outcomes:
        c = outcome.company
        if outcome.postings is None:
            failed += 1
            print(f"FAIL {c.slug}: {outcome.error}")
            continue
        kept = [p for p in outcome.postings if keep(p) is not None]
        print(
            f"OK   {c.slug}: {len(outcome.postings)} postings, {len(kept)} India tech internships"
        )
    return 1 if failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tracker", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run", help="fetch, filter, diff and save")
    run_parser.add_argument("--dry-run", action="store_true", help="do not write any files")
    run_parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    check_parser = sub.add_parser("check", help="fetch some companies and print counts only")
    check_parser.add_argument("--companies", required=True, help="comma-separated company slugs")
    check_parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    for p in (run_parser, check_parser):
        p.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    # httpx logs every request URL at INFO, and CallMeBot URLs contain the API key.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    if args.command == "check":
        slugs = [s.strip() for s in args.companies.split(",") if s.strip()]
        return asyncio.run(_check_cli(slugs, args.data_dir))
    return asyncio.run(_run_cli(args.dry_run, args.data_dir))
