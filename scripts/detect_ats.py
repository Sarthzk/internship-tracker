"""Detect which public ATS each `ats: unknown` company in companies.yaml uses.

Tries slug guesses against Greenhouse, Lever, Ashby and SmartRecruiters, prints a summary and
writes data/ats_detection_report.md. Never modifies companies.yaml.

    uv run python scripts/detect_ats.py [--only "Stripe,Razorpay"] [--delay 1.0]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from tracker import __version__
from tracker.models import AtsType, Company, load_companies

log = logging.getLogger("detect_ats")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_COMPANIES = ROOT / "data" / "companies.yaml"
DEFAULT_REPORT = ROOT / "data" / "ats_detection_report.md"

USER_AGENT = f"internship-tracker/{__version__} (+https://github.com/Sarthzk/internship-tracker)"
TIMEOUT_S = 20.0
MAX_ATTEMPTS = 3
MAX_GUESSES = 8

# Corporate suffixes; one is stripped to produce a shorter slug guess.
SUFFIXES = ["global tech", "capital", "chase", "& co", "inc"]

# Known slug oddities that the generic rules cannot produce. Results still need human review.
SLUG_HINTS: dict[str, list[str]] = {
    "D. E. Shaw": ["deshaw", "de-shaw", "deshawresearch"],
    "Media.net": ["medianet", "media-net"],
    "CRED": ["cred", "dreamplug", "cred-club"],
    "JPMorgan Chase": ["jpmorganchase", "jpmorgan"],
    "American Express": ["americanexpress", "amex"],
    "Zomato": ["zomato", "eternal"],
    "Dream11": ["dream11", "dreamsports", "dream-sports"],
    "Walmart Global Tech": ["walmartglobaltech", "walmart"],
}

# Approximate India matcher (the real one is tracker/filters.py, Phase 1).
_INDIA_RE = re.compile(
    r"\b(india|bengaluru|bangalore|hyderabad|pune|mumbai|gurugram|gurgaon|noida|delhi|chennai"
    r"|kolkata|ahmedabad|kochi|thiruvananthapuram|jaipur|indore|chandigarh|coimbatore"
    r"|mysuru|mysore)\b",
    re.IGNORECASE,
)


def is_india(text: str | None) -> bool:
    return bool(text) and bool(_INDIA_RE.search(text))


# --- slug guesses ---------------------------------------------------------------------------


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower().replace("&", " and "))


def slug_guesses(name: str) -> list[str]:
    words = _words(name)
    guesses = ["".join(words), "-".join(words)]
    if len(words) > 1 and len(words[0]) >= 3:
        guesses.append(words[0])

    stripped = name.lower()
    for suffix in SUFFIXES:  # strip at most one suffix
        shorter = re.sub(rf"\s*{re.escape(suffix)}\s*$", "", stripped)
        if shorter != stripped:
            stripped = shorter
            break
    stripped_words = _words(stripped)
    if stripped_words and stripped_words != words:
        guesses += ["".join(stripped_words), "-".join(stripped_words)]

    guesses += SLUG_HINTS.get(name, [])
    seen: dict[str, None] = {}
    for g in guesses:
        if g:
            seen.setdefault(g, None)
    return list(seen)[:MAX_GUESSES]


# --- company name matching ----------------------------------------------------------------

_NAME_NOISE = {
    "inc", "ltd", "llc", "llp", "pvt", "private", "limited", "corp", "corporation", "co",
    "company", "the", "and", "group", "technologies", "technology", "india",
}  # fmt: skip


def _name_tokens(name: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", name.lower()) if t not in _NAME_NOISE}


def names_match(ours: str, theirs: str | None) -> bool:
    """Loose company-name match: one side's tokens contain the other's, or same compact string.

    "SWIGGY" ~ "Swiggy", "medianet" ~ "Media.net", but "AMD" !~ "AMDOCS".
    """
    if not theirs:
        return False
    a, b = _name_tokens(ours), _name_tokens(theirs)
    if not a or not b:
        return False
    if a <= b or b <= a:
        return True
    return "".join(sorted(a)) == "".join(sorted(b))


# --- per-ATS parsing ------------------------------------------------------------------------


@dataclass
class Board:
    total: int
    india: int
    partial: bool = False  # india count covers only the first page
    api_company_name: str | None = None


def parse_greenhouse(data: Any) -> Board | None:
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        return None
    jobs = data["jobs"]
    india = sum(is_india((j.get("location") or {}).get("name")) for j in jobs)
    names = {j.get("company_name") for j in jobs if j.get("company_name")}
    return Board(len(jobs), india, api_company_name=", ".join(sorted(names)) or None)


def parse_lever(data: Any) -> Board | None:
    if not isinstance(data, list):
        return None

    def india(job: dict) -> bool:
        cats = job.get("categories") or {}
        locs = [cats.get("location") or "", *(cats.get("allLocations") or [])]
        return any(is_india(loc) for loc in locs)

    return Board(len(data), sum(india(j) for j in data if isinstance(j, dict)))


def parse_ashby(data: Any) -> Board | None:
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        return None

    def india(job: dict) -> bool:
        locs = [job.get("location") or ""]
        locs += [s.get("location") or "" for s in job.get("secondaryLocations") or []]
        return any(is_india(loc) for loc in locs)

    return Board(len(data["jobs"]), sum(india(j) for j in data["jobs"]))


def parse_smartrecruiters(data: Any) -> Board | None:
    if not isinstance(data, dict) or not isinstance(data.get("content"), list):
        return None
    content = data["content"]
    total = int(data.get("totalFound") or 0)

    def india(job: dict) -> bool:
        loc = job.get("location") or {}
        if str(loc.get("country", "")).lower() == "in":
            return True
        return any(is_india(loc.get(k)) for k in ("city", "region", "fullLocation"))

    names = {(j.get("company") or {}).get("name") for j in content}
    names.discard(None)
    return Board(
        total,
        sum(india(j) for j in content),
        partial=total > len(content),
        api_company_name=", ".join(sorted(names)) or None,
    )


@dataclass(frozen=True)
class AtsSpec:
    ats: AtsType
    url: Callable[[str], str]
    parse: Callable[[Any], Board | None]
    config_key: str
    # SmartRecruiters answers 200/empty/500 for any slug, so only a board with jobs AND a
    # company name that matches ours counts; everything else is dropped from the report.
    needs_name_match: bool = False


ATS_SPECS: list[AtsSpec] = [
    AtsSpec(
        AtsType.greenhouse,
        lambda s: f"https://boards-api.greenhouse.io/v1/boards/{s}/jobs",
        parse_greenhouse,
        "board_token",
    ),
    AtsSpec(
        AtsType.lever,
        lambda s: f"https://api.lever.co/v0/postings/{s}?mode=json",
        parse_lever,
        "site",
    ),
    AtsSpec(
        AtsType.ashby,
        lambda s: f"https://api.ashbyhq.com/posting-api/job-board/{s}",
        parse_ashby,
        "site",
    ),
    AtsSpec(
        AtsType.smartrecruiters,
        lambda s: f"https://api.smartrecruiters.com/v1/companies/{s}/postings?limit=100",
        parse_smartrecruiters,
        "company_id",
        needs_name_match=True,
    ),
]


# --- probing --------------------------------------------------------------------------------


@dataclass
class ProbeResult:
    company: Company
    spec: AtsSpec
    slug: str
    board: Board | None = None  # None = no board at this slug
    error: str | None = None

    @property
    def is_match(self) -> bool:
        return self.board is not None and self.board.total > 0


class ProbeError(Exception):
    pass


async def get_json(client: httpx.AsyncClient, url: str) -> tuple[int, Any]:
    """GET with retry on network errors, 429 and 5xx. Returns (status, json-or-None)."""
    last_error = ""
    for attempt in range(MAX_ATTEMPTS):
        wait = 2.0**attempt
        try:
            resp = await client.get(url)
        except httpx.TransportError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        else:
            if resp.status_code != 429 and resp.status_code < 500:
                try:
                    return resp.status_code, resp.json()
                except ValueError:
                    return resp.status_code, None
            last_error = f"HTTP {resp.status_code}"
            retry_after = resp.headers.get("Retry-After", "")
            if retry_after.isdigit():
                wait = min(max(wait, float(retry_after)), 30.0)
        if attempt < MAX_ATTEMPTS - 1:
            log.debug("retrying %s after %s (%.0fs)", url, last_error, wait)
            await asyncio.sleep(wait)
    raise ProbeError(last_error)


async def _host_worker(
    client: httpx.AsyncClient,
    spec: AtsSpec,
    companies: list[Company],
    matched: set[str],
    delay: float,
) -> list[ProbeResult]:
    """Probe one ATS host sequentially, so there is at most one in-flight request per host."""
    results: list[ProbeResult] = []
    first = True
    for company in companies:
        for slug in slug_guesses(company.name):
            if company.slug in matched:
                break
            if not first:
                await asyncio.sleep(delay)
            first = False
            result = ProbeResult(company, spec, slug)
            try:
                status, data = await get_json(client, spec.url(slug))
                if status == 200:
                    result.board = spec.parse(data)
            except ProbeError as exc:
                result.error = str(exc)
            if spec.needs_name_match and not (
                result.is_match and names_match(company.name, result.board.api_company_name)
            ):
                result.board = result.error = None
            if result.is_match:
                matched.add(company.slug)
                log.info("%s: %s/%s (%d jobs)", company.name, spec.ats, slug, result.board.total)
            if result.board is not None or result.error:
                results.append(result)
    return results


async def detect(
    companies: list[Company], client: httpx.AsyncClient, delay: float = 1.0
) -> list[ProbeResult]:
    matched: set[str] = set()
    per_host = await asyncio.gather(
        *(_host_worker(client, spec, companies, matched, delay) for spec in ATS_SPECS)
    )
    return [r for results in per_host for r in results]


# --- report ---------------------------------------------------------------------------------


def _india_cell(board: Board) -> str:
    return f"≥{board.india}" if board.partial else str(board.india)


def _snippet(result: ProbeResult) -> str:
    return f"`ats: {result.spec.ats}, ats_config: {{{result.spec.config_key}: {result.slug}}}`"


def render_report(companies: list[Company], results: list[ProbeResult]) -> str:
    by_company: dict[str, list[ProbeResult]] = {c.slug: [] for c in companies}
    for r in results:
        by_company[r.company.slug].append(r)

    detected, weak, manual, errors = [], [], [], []
    detected_count = 0
    for company in companies:
        rs = by_company[company.slug]
        matches = sorted((r for r in rs if r.is_match), key=lambda r: -r.board.total)
        detected_count += bool(matches)
        for i, r in enumerate(matches):
            mark = "**suggested**" if i == 0 else "alternative"
            detected.append(
                f"| {company.name} | {r.spec.ats} | `{r.slug}` | {r.board.total} | "
                f"{_india_cell(r.board)} | {r.board.api_company_name or '—'} | {mark} {_snippet(r)} |"
            )
        empties = [r for r in rs if r.board is not None and not r.is_match]
        if not matches and empties:
            weak.append(
                f"| {company.name} | "
                + ", ".join(f"{r.spec.ats}/`{r.slug}`" for r in empties)
                + " |"
            )
        if not matches and not empties:
            manual.append(f"- {company.name} (`{company.slug}`)")
        errors += [
            f"| {company.name} | {r.spec.ats} | `{r.slug}` | {r.error} |" for r in rs if r.error
        ]

    lines = [
        "# ATS detection report",
        "",
        "Generated by `scripts/detect_ats.py`. Suggestions only: companies.yaml is not modified.",
        "India counts are approximate (simple regex); `≥` means only the first page was counted.",
        "Check the API company name column for slug collisions (a different company with the same slug).",
        "",
        f"## Detected ({detected_count} of {len(companies)} companies)",
        "",
        "| Company | ATS | Slug | Jobs | India jobs | API company name | Suggestion |",
        "|---|---|---|---|---|---|---|",
        *detected,
        "",
        "## Weak hits (board exists, 0 jobs)",
        "",
        "| Company | Boards |",
        "|---|---|",
        *weak,
        "",
        "## Needs manual check (likely Workday or custom portal)",
        "",
        "See docs/CUSTOM_PORTALS.md for how to document these.",
        "",
        *manual,
        "",
        "## Errors (retries exhausted)",
        "",
        "| Company | ATS | Slug | Error |",
        "|---|---|---|---|",
        *errors,
        "",
    ]
    return "\n".join(lines)


def print_summary(companies: list[Company], results: list[ProbeResult]) -> None:
    best: dict[str, ProbeResult] = {}
    for r in results:
        if r.is_match and (
            r.company.slug not in best or r.board.total > best[r.company.slug].board.total
        ):
            best[r.company.slug] = r
    width = max((len(c.name) for c in companies), default=10)
    for c in companies:
        r = best.get(c.slug)
        if r:
            print(
                f"{c.name:<{width}}  {r.spec.ats:<16} {r.slug:<24} "
                f"jobs={r.board.total:<5} india={_india_cell(r.board)}"
            )
        else:
            print(f"{c.name:<{width}}  needs manual check")
    print(f"\n{len(best)}/{len(companies)} companies detected.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--companies", type=Path, default=DEFAULT_COMPANIES)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--delay", type=float, default=1.0, help="seconds between requests per host"
    )
    parser.add_argument("--only", default="", help="comma-separated company names to probe")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    companies = [c for c in load_companies(args.companies) if c.ats == AtsType.unknown]
    if args.only:
        wanted = {n.strip().lower() for n in args.only.split(",") if n.strip()}
        companies = [c for c in companies if c.name.lower() in wanted or c.slug in wanted]
    if not companies:
        print("No companies with `ats: unknown` to probe.")
        return
    log.info("probing %d companies across %d ATS hosts", len(companies), len(ATS_SPECS))

    async def run() -> list[ProbeResult]:
        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=TIMEOUT_S,
            follow_redirects=True,
        ) as client:
            return await detect(companies, client, args.delay)

    results = asyncio.run(run())
    args.report.write_text(render_report(companies, results), encoding="utf-8")
    print_summary(companies, results)
    print(f"Report written to {args.report}")


if __name__ == "__main__":
    main()
