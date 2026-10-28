"""README + archive generation.

Everything here is a pure function of the listings and `now`, so a quiet run reproduces the
same text. The only things that change without a real change are the "last updated" date and
the Age column, both at most once a day.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

from tracker.models import Category, Listing, Status
from tracker.storage import load_listings

START = "<!-- LISTINGS:START -->"
END = "<!-- LISTINGS:END -->"
ARCHIVE_DAYS = 90
IST = timezone(timedelta(hours=5, minutes=30))
MAX_LOCATIONS = 3
NONE = "—"

HEADINGS: dict[Category, str] = {
    Category.swe: "Software Engineering",
    Category.data_ml: "Data & ML",
    Category.quant: "Quant & Trading",
    Category.hardware: "Hardware & Silicon",
    Category.product: "Product",
    Category.other: "Other",
}

_ESCAPES = str.maketrans(
    {
        "\\": "\\\\",
        "|": "\\|",
        "`": "\\`",
        "*": "\\*",
        "_": "\\_",
        "<": "&lt;",
        ">": "&gt;",
        "[": "\\[",
        "]": "\\]",
        "\n": " ",
        "\r": " ",
    }
)


def cell(text: object) -> str:
    """Text safe to put inside a markdown table cell."""
    return " ".join(str(text).translate(_ESCAPES).split()) or NONE


def link(url: str) -> str:
    """`[Apply](url)` with the characters that would end the link target percent-encoded."""
    target = url.replace(" ", "%20").replace("(", "%28").replace(")", "%29")
    return f"[Apply]({target})"


def _location(listing: Listing) -> str:
    unique = list(dict.fromkeys(listing.locations))
    places = unique[:MAX_LOCATIONS]
    text = "; ".join(places)
    extra = len(unique) - len(places)
    if extra > 0:
        text += f" +{extra} more"
    if listing.is_remote and "remote" not in text.lower():
        text = f"{text} (Remote)" if text else "Remote"
    return cell(text)


def _batch(listing: Listing) -> str:
    batches = listing.enrichment.eligible_batches if listing.enrichment else None
    return cell(", ".join(str(b) for b in batches)) if batches else NONE


def _duration(listing: Listing) -> str:
    months = listing.enrichment.duration_months if listing.enrichment else None
    return f"{months} mo" if months else NONE


def _local(moment: datetime) -> date:
    return moment.astimezone(IST).date()


def _posted(listing: Listing) -> date:
    return listing.date_posted or _local(listing.first_seen)


def _age(listing: Listing, today: date) -> str:
    return f"{max(0, (today - _posted(listing)).days)}d"


def _count(n: int, singular: str, plural: str | None = None) -> str:
    return f"{n} {singular if n == 1 else plural or singular + 's'}"


def _table(rows: list[str], header: str) -> list[str]:
    columns = header.count("|") - 1
    return [header, "|" + "---|" * columns, *rows]


OPEN_HEADER = "| Company | Role | Location | Batch | Duration | Apply | Age |"
ARCHIVE_HEADER = "| Company | Role | Location | Batch | Duration | Apply | Posted | Closed |"


def render_listings(listings: Iterable[Listing], now: datetime) -> str:
    """The generated section (without the markers): summary line plus one table per category."""
    today = _local(now)
    open_listings = [li for li in listings if li.status == Status.open]
    companies = len({li.company_slug for li in open_listings})
    lines = [
        (
            f"**{_count(len(open_listings), 'open internship')}** across "
            f"{_count(companies, 'company', 'companies')} "
            f"· Last updated: {today.isoformat()} (IST)"
        ),
        "",
    ]
    if not open_listings:
        lines.append("No open internships right now. Check back soon.")
    for category, heading in HEADINGS.items():
        group = [li for li in open_listings if li.category == category]
        if not group:
            continue
        group.sort(key=lambda li: (-_posted(li).toordinal(), li.company, li.title, li.id))
        rows = [
            f"| {cell(li.company)} | {cell(li.title)} | {_location(li)} | {_batch(li)} | "
            f"{_duration(li)} | {link(li.url)} | {_age(li, today)} |"
            for li in group
        ]
        lines += [f"### {heading} ({len(group)})", "", *_table(rows, OPEN_HEADER), ""]
    return "\n".join(lines).rstrip() + "\n"


def render_archive(listings: Iterable[Listing], now: datetime) -> str:
    """The whole README-archive.md: listings closed in the last ARCHIVE_DAYS days."""
    cutoff = now - timedelta(days=ARCHIVE_DAYS)
    closed = [
        li
        for li in listings
        if li.status == Status.closed and li.closed_at is not None and li.closed_at >= cutoff
    ]
    closed.sort(key=lambda li: (-(li.closed_at or now).timestamp(), li.company, li.id))
    lines = [
        "# Closed internships (last 90 days)",
        "",
        (
            "Listings that are no longer on the company's career page. "
            "[Back to the open internships](README.md)."
        ),
        "",
        f"**{len(closed)} closed** · Last updated: {_local(now).isoformat()} (IST)",
        "",
    ]
    if closed:
        rows = [
            f"| {cell(li.company)} | {cell(li.title)} | {_location(li)} | {_batch(li)} | "
            f"{_duration(li)} | {link(li.url)} | {_posted(li).isoformat()} | "
            f"{_local(li.closed_at or now).isoformat()} |"
            for li in closed
        ]
        lines += _table(rows, ARCHIVE_HEADER)
    else:
        lines.append("Nothing closed in the last 90 days.")
    return "\n".join(lines).rstrip() + "\n"


def replace_section(readme: str, section: str) -> str:
    """Put `section` between the markers, leaving every other character of `readme` alone.

    A README without markers gets them appended, so hand-written text is never lost."""
    block = f"{START}\n{section}{END}"
    start, end = readme.find(START), readme.find(END)
    if start == -1 or end == -1 or end < start:
        return readme.rstrip("\n") + f"\n\n{block}\n"
    return readme[:start] + block + readme[end + len(END) :]


def write_if_changed(path: Path, text: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def generate(data_dir: Path, root: Path, now: datetime | None = None) -> bool:
    """Regenerate README.md (generated section only) and README-archive.md. True if changed."""
    now = now or datetime.now(UTC)
    listings = load_listings(data_dir / "listings.json")
    readme_path = root / "README.md"
    current = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""
    changed = write_if_changed(
        readme_path, replace_section(current, render_listings(listings, now))
    )
    changed |= write_if_changed(root / "README-archive.md", render_archive(listings, now))
    return changed
