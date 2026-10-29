"""Checks that data is sane before anything is sent or committed. Errors block; warnings do not."""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Iterable
from pathlib import Path

from pydantic import ValidationError

from tracker.models import HealthRecord, Listing, load_companies
from tracker.storage import health_text, listings_text, load_health, load_listings

MAX_TEXT = 300  # a title or location longer than this is probably scraped page text


class DataError(Exception):
    """The data failed validation: do not notify, save or commit."""


def check_listings(
    listings: Iterable[Listing], company_slugs: Collection[str]
) -> tuple[list[str], list[str]]:
    """(errors, warnings) for a set of listings."""
    listings = list(listings)
    errors: list[str] = []
    warnings: list[str] = []
    for listing_id, n in Counter(li.id for li in listings).items():
        if n > 1:
            errors.append(f"duplicate listing id {listing_id}")
    for li in listings:
        if not li.url.startswith("https://"):
            errors.append(f"{li.id}: url is not https")
        if len(li.title) > MAX_TEXT or any(len(loc) > MAX_TEXT for loc in li.locations):
            errors.append(f"{li.id}: title or location is suspiciously long")
        if li.company_slug not in company_slugs:
            warnings.append(f"{li.id}: company {li.company_slug!r} is not in companies.yaml")
    return errors, sorted(set(warnings))


def check_health(
    health: dict[str, HealthRecord], company_slugs: Collection[str]
) -> tuple[list[str], list[str]]:
    warnings = [
        f"health record for {slug!r}, which is not in companies.yaml"
        for slug in sorted(health)
        if slug not in company_slugs
    ]
    return [], warnings


def check_files(data_dir: Path) -> tuple[list[str], list[str]]:
    """Load the three data files and check them, including that listings.json and health.json
    are in the canonical form (sorted keys, sorted records), so a hand edit cannot sneak in."""
    errors: list[str] = []
    warnings: list[str] = []
    try:
        companies = load_companies(data_dir / "companies.yaml")
    except (ValidationError, ValueError, OSError) as exc:
        return [f"companies.yaml: {type(exc).__name__}: {str(exc)[:200]}"], []
    slugs = {c.slug for c in companies}
    if len(slugs) != len(companies):
        errors.append("companies.yaml: duplicate slugs")

    listings_path, health_path = data_dir / "listings.json", data_dir / "health.json"
    try:
        listings = load_listings(listings_path)
        health = load_health(health_path)
    except (ValidationError, ValueError, OSError) as exc:
        return errors + [f"data file: {type(exc).__name__}: {str(exc)[:200]}"], warnings

    e, w = check_listings(listings, slugs)
    errors += e
    warnings += w
    e, w = check_health(health, slugs)
    errors += e
    warnings += w
    if listings_path.exists() and listings_path.read_text("utf-8") != listings_text(listings):
        errors.append("listings.json is not in canonical form")
    if health_path.exists() and health_path.read_text("utf-8") != health_text(health):
        errors.append("health.json is not in canonical form")
    return errors, warnings
