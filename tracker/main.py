"""Orchestration + CLI (python -m tracker)."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from tracker import fetchers, readme
from tracker.diff import MergeResult, merge, prune_closed
from tracker.filters import keep
from tracker.guards import find_id_churn
from tracker.health import is_recovery, record_fetch, run_gap_message, should_send_crash_alert
from tracker.http import make_client
from tracker.models import Company, HealthRecord, Listing, RawPosting, Status, load_companies
from tracker.notify import (
    MAX_ALERT_MESSAGES,
    Sender,
    Telegram,
    deliver,
    deliver_health_alerts,
    digest_due,
    format_churn,
    format_crash,
    format_daily_digest,
    format_recovered,
    format_tracking_started,
    plan_alerts,
    plan_health_alerts,
)
from tracker.storage import load_health, load_listings, save_health, save_listings
from tracker.validate import DataError, check_files, check_listings

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
GITHUB_API = "https://api.github.com"
FETCH_TIMEOUT = 120.0  # seconds one company may take, including paging and retries


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
    alerts_sent: int = 0  # listings delivered to Telegram this run
    alerts_pending: int = 0  # listings still waiting (no sender, or a send failed)

    @property
    def open_count(self) -> int:
        return sum(1 for li in self.merge.listings if li.status == "open")


async def fetch_company(
    company: Company, client: httpx.AsyncClient, timeout: float = FETCH_TIMEOUT
) -> FetchOutcome:
    """Never raises: one company failing must not crash the run (CLAUDE.md rule 8).

    A company that takes longer than `timeout` seconds counts as failed, so one stuck site
    cannot use up the whole run's time limit."""
    fetch = fetchers.get_fetcher(company)
    if fetch is None:
        return FetchOutcome(company, error=f"no fetcher for ats={company.ats}")
    try:
        postings = await asyncio.wait_for(fetch(company, client), timeout)
        return FetchOutcome(company, postings=postings)
    except TimeoutError:
        return FetchOutcome(company, error=f"TimeoutError: no answer within {timeout:.0f}s")
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
    summary.merge.listings = prune_closed(summary.merge.listings, now)
    errors, _ = check_listings(summary.merge.listings, {c.slug for c in companies})
    if errors:  # before anything is sent or saved
        raise DataError("; ".join(errors[:5]))
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
    """Send Telegram alerts and record `notified` / `failure_alerted` before the data is saved."""
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

    # Listings replaced wholesale (ids changed) are not alerts; tell the owner once instead.
    churn = find_id_churn(summary.merge, first_fetch)
    if churn:
        held = {listing_id for ids, _ in churn.values() for listing_id in ids}
        for li in listings:
            if li.id in held:
                li.notified = True
        report = {names.get(slug, slug): (len(ids), gone) for slug, (ids, gone) in churn.items()}
        if sender is not None and not await sender.send(format_churn(report)):
            log.warning("could not send the 'possible site change' message")

    pending = [li for li in listings if li.status == Status.open and not li.notified]
    if sender is None:
        summary.alerts_pending = len(pending)
        return
    # At most MAX_ALERT_MESSAGES per run; the rest stay un-notified and go out next run.
    alerts = plan_alerts(pending)[:MAX_ALERT_MESSAGES]
    delivered = await deliver(sender, alerts, pause)
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
        print(f"Telegram: {summary.alerts_sent} sent, {summary.alerts_pending} waiting")
    by_id = {li.id: li for li in summary.merge.listings}
    for listing_id in summary.merge.new_ids:
        li = by_id[listing_id]
        print(f"  NEW {li.company}: {li.title} ({'; '.join(li.locations)}) {li.url}")


@dataclass
class PreviousRun:
    started: datetime
    conclusion: str | None  # "success", "failure", "cancelled", ...


async def previous_run(
    client: httpx.AsyncClient, env: Mapping[str, str] | None = None
) -> PreviousRun | None:
    """The last finished scrape run other than this one, from the GitHub API.

    Only works inside GitHub Actions (GITHUB_TOKEN, GITHUB_REPOSITORY); returns None otherwise or
    on any error, since a missing check must never break a run."""
    env = os.environ if env is None else env
    token, repo = env.get("GITHUB_TOKEN", ""), env.get("GITHUB_REPOSITORY", "")
    if not token or not repo:
        return None
    try:
        response = await client.get(
            f"{GITHUB_API}/repos/{repo}/actions/workflows/scrape.yml/runs",
            params={"status": "completed", "per_page": 5},
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        response.raise_for_status()
        runs = response.json()["workflow_runs"]
        this_run = env.get("GITHUB_RUN_ID", "")
        for run in runs:
            if str(run["id"]) != this_run:
                started = datetime.fromisoformat(run["run_started_at"])
                return PreviousRun(started, run.get("conclusion"))
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        log.warning("could not look up the previous run: %s", type(exc).__name__)
    return None


def digest_text(summary: RunSummary, companies: Sequence[Company], now: datetime) -> str:
    """The 9 AM message built from this run's results."""
    names = {c.slug: c.name for c in companies}
    failing = {names.get(slug, slug): error for slug, error in summary.failed.items()}
    since = now - timedelta(hours=24)
    new_last_day = sum(
        1 for li in summary.merge.listings if li.status == Status.open and li.first_seen >= since
    )
    enabled = sum(1 for c in companies if c.enabled)
    return format_daily_digest(enabled, failing, summary.open_count, new_last_day)


async def _run_cli(dry_run: bool, data_dir: Path) -> int:
    companies = load_companies(data_dir / "companies.yaml")
    async with make_client() as client:
        sender = None if dry_run else Telegram.from_env(client)
        previous = await previous_run(client) if sender is not None else None
        conclusion = previous.conclusion if previous else None
        if sender is not None:
            event = os.environ.get("GITHUB_EVENT_NAME", "unknown")
            gap = run_gap_message(previous.started if previous else None, datetime.now(UTC), event)
            if gap:
                await sender.send(gap)
        try:
            summary = await run(companies, client, data_dir, dry_run=dry_run, sender=sender)
        except Exception as exc:
            # Only the first failed run alerts; while it keeps failing, stay quiet.
            if sender is not None and should_send_crash_alert(conclusion):
                await sender.send(format_crash(exc))
            raise
        if sender is not None:
            now = datetime.now(UTC)
            if is_recovery(conclusion):
                await sender.send(format_recovered())
            if digest_due(now, previous.started if previous else None):
                await sender.send(digest_text(summary, companies, now))
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
    validate_parser = sub.add_parser("validate", help="check the data files; exit 1 on errors")
    validate_parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    readme_parser = sub.add_parser("readme", help="regenerate README.md and README-archive.md")
    readme_parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    for p in (run_parser, check_parser, readme_parser, validate_parser):
        p.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    # httpx logs every request URL at INFO, and Telegram URLs contain the bot token.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    if args.command == "validate":
        errors, warnings = check_files(args.data_dir)
        for line in warnings:
            print(f"warning: {line}")
        for line in errors:
            print(f"ERROR: {line}")
        print("data OK" if not errors else f"{len(errors)} error(s)")
        return 1 if errors else 0
    if args.command == "readme":
        changed = readme.generate(args.data_dir, args.data_dir.parent)
        print("README updated." if changed else "README already up to date.")
        return 0
    if args.command == "check":
        slugs = [s.strip() for s in args.companies.split(",") if s.strip()]
        return asyncio.run(_check_cli(slugs, args.data_dir))
    return asyncio.run(_run_cli(args.dry_run, args.data_dir))
