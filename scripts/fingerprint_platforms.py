"""Fingerprint the hiring platform behind each unresolved company's careers page.

For every company with `ats: unknown`, fetch its `careers_url`, look for known platform
signatures in the redirect chain, HTML and linked URLs, then verify each guess with a live API
call. Writes data/platform_report.md and never modifies companies.yaml.

    uv run python scripts/fingerprint_platforms.py [--only "PayPal,Qualcomm"] [--delay 1.0]
"""

from __future__ import annotations

import argparse
import asyncio
import html as html_lib
import logging
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # allow `python scripts/fingerprint_platforms.py`
    sys.path.insert(0, str(ROOT))

from scripts.detect_ats import (
    ATS_SPECS,
    MAX_ATTEMPTS,
    TIMEOUT_S,
    USER_AGENT,
    Board,
    is_india,
    names_match,
)
from tracker.models import AtsType, Company, load_companies

log = logging.getLogger("fingerprint")

DEFAULT_COMPANIES = ROOT / "data" / "companies.yaml"
DEFAULT_REPORT = ROOT / "data" / "platform_report.md"

MAX_REDIRECTS = 5
MAX_HTML_CHARS = 5_000_000
MAX_VERIFY_CANDIDATES = 3  # platforms tried per company, in rank order
MAX_SAMPLE_PAGES = 5  # pages scanned for India counts on Workday / Oracle HCM

# Platforms we can verify with a live call, and platforms we only detect.
VERIFIABLE = {
    "workday",
    "eightfold",
    "oracle_hcm",
    "greenhouse",
    "lever",
    "ashby",
    "smartrecruiters",
}
DETECT_ONLY = {"phenom"}

DISPLAY_NAMES = {
    "workday": "Workday",
    "eightfold": "Eightfold",
    "oracle_hcm": "Oracle HCM",
    "phenom": "Phenom",
    "greenhouse": "Greenhouse",
    "lever": "Lever",
    "ashby": "Ashby",
    "smartrecruiters": "SmartRecruiters",
}

# Recorded but not supported yet: platform name -> host suffixes.
OTHER_PLATFORMS: dict[str, tuple[str, ...]] = {
    "icims": ("icims.com",),
    "taleo": ("taleo.net",),
    "successfactors": ("successfactors.com", "successfactors.eu"),
    "avature": ("avature.net",),
    "jobvite": ("jobvite.com",),
    "workable": ("workable.com",),
    "zoho_recruit": ("zohorecruit.com", "zohorecruit.in", "recruit.zoho.com", "recruit.zoho.in"),
    "darwinbox": ("darwinbox.in", "darwinbox.com"),
    "keka": ("keka.com", "kekahire.com"),
    "freshteam": ("freshteam.com",),
    "recruitee": ("recruitee.com",),
    "breezy": ("breezy.hr",),
}

RANK_CHAIN, RANK_LINK, RANK_MENTION = 3, 2, 1


# --- signals --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Signal:
    platform: str  # an AtsType value, or "other:<name>"
    config: dict[str, str] = field(compare=False, hash=False, default_factory=dict)
    evidence: str = field(compare=False, default="")
    rank: int = field(compare=False, default=RANK_MENTION)

    @property
    def key(self) -> tuple[str, tuple[tuple[str, str], ...]]:
        return self.platform, tuple(sorted(self.config.items()))


_URL_RE = re.compile(
    r"(?:https?:)?//[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,}(?::\d+)?(?:/[^\s\"'<>\\)]*)?"
)
_LOCALE_RE = re.compile(r"^[a-z]{2}(?:[-_][A-Za-z]{2,4})?$")


def collect_urls(html: str) -> list[str]:
    """Every absolute or protocol-relative URL in the HTML, including inside scripts and JSON."""
    text = html.replace("\\/", "/").replace("\\u002F", "/").replace("\\u002f", "/")
    text = html_lib.unescape(text)
    seen: dict[str, None] = {}
    for match in _URL_RE.finditer(text):
        url = match.group(0).rstrip(".,;:")
        if url.startswith("//"):
            url = "https:" + url
        seen.setdefault(url, None)
    return list(seen)


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _segments(url: str) -> list[str]:
    return [s for s in urlparse(url).path.split("/") if s]


def _host_is(host: str, *suffixes: str) -> bool:
    return any(host == s or host.endswith("." + s) for s in suffixes)


_WD_HOST_RE = re.compile(r"^(?P<tenant>[a-z0-9-]+)\.(?P<wd>wd\d+)\.myworkdayjobs\.com$")
_WD_NOT_SITES = {"job", "jobs", "details", "login", "userhome", "apply", "wday", "search"}


def _workday(url: str) -> dict[str, str] | None:
    match = _WD_HOST_RE.match(_host(url))
    if not match:
        return None
    tenant, host = match["tenant"], _host(url)
    segs = _segments(url)
    if len(segs) >= 4 and segs[0] == "wday" and segs[1] == "cxs":
        return {"host": host, "tenant": segs[2], "site": segs[3]}
    if segs and _LOCALE_RE.match(segs[0]):
        segs = segs[1:]
    config = {"host": host, "tenant": tenant}
    if segs and segs[0].lower() not in _WD_NOT_SITES:
        config["site"] = segs[0]
    return config


_ORACLE_RE = re.compile(
    r"^https?://(?P<host>[a-z0-9.-]+\.oraclecloud\.com)/hcmUI/CandidateExperience"
    r"(?:/[a-z]{2}(?:[-_][A-Za-z]{2,4})?)?/sites/(?P<site>[A-Za-z0-9_-]+)",
    re.IGNORECASE,
)

_GH_BOARD_HOSTS = ("boards.greenhouse.io", "job-boards.greenhouse.io",
                   "boards.eu.greenhouse.io", "job-boards.eu.greenhouse.io")  # fmt: skip
_GH_RESERVED = {"embed", "blog", "jobs", "api", "v1", "assets", "static", "favicon.ico"}


def _greenhouse(url: str) -> dict[str, str] | None:
    host, segs = _host(url), _segments(url)
    if host == "boards-api.greenhouse.io" and len(segs) >= 3 and segs[:2] == ["v1", "boards"]:
        return {"board_token": segs[2]}
    if host not in _GH_BOARD_HOSTS:
        return None
    if segs and segs[0] == "embed":
        slug = (parse_qs(urlparse(url).query).get("for") or [""])[0]
        return {"board_token": slug} if slug else None
    if segs and segs[0].lower() not in _GH_RESERVED:
        return {"board_token": segs[0]}
    return None


def _lever(url: str) -> dict[str, str] | None:
    host, segs = _host(url), _segments(url)
    if host == "jobs.lever.co" and segs:
        return {"site": segs[0]}
    if host == "api.lever.co" and len(segs) >= 3 and segs[:2] == ["v0", "postings"]:
        return {"site": segs[2]}
    return None


def _ashby(url: str) -> dict[str, str] | None:
    host, segs = _host(url), _segments(url)
    if host == "jobs.ashbyhq.com" and segs and segs[0] not in {"api", "embed"}:
        return {"site": segs[0]}
    if host == "api.ashbyhq.com" and len(segs) >= 3 and segs[:2] == ["posting-api", "job-board"]:
        return {"site": segs[2]}
    return None


def _smartrecruiters(url: str) -> dict[str, str] | None:
    host, segs = _host(url), _segments(url)
    if host in {"jobs.smartrecruiters.com", "careers.smartrecruiters.com"} and segs:
        if segs[0] == "oneclick-ui" and len(segs) >= 3 and segs[1] == "company":
            return {"company_id": segs[2]}
        return {"company_id": segs[0]}
    if host == "api.smartrecruiters.com" and len(segs) >= 3 and segs[:2] == ["v1", "companies"]:
        return {"company_id": segs[2]}
    return None


def _url_signals(url: str, rank: int) -> list[Signal]:
    found: list[Signal] = []
    host = _host(url)

    if config := _workday(url):
        found.append(Signal("workday", config, url, rank))
    if _host_is(host, "eightfold.ai"):
        found.append(Signal("eightfold", {"host": host}, url, rank))
    if match := _ORACLE_RE.match(url):
        config = {"host": match["host"].lower(), "site": match["site"]}
        found.append(Signal("oracle_hcm", config, url, rank))
    for platform, extract in (
        ("greenhouse", _greenhouse),
        ("lever", _lever),
        ("ashby", _ashby),
        ("smartrecruiters", _smartrecruiters),
    ):
        if config := extract(url):
            found.append(Signal(platform, config, url, rank))
    for name, suffixes in OTHER_PLATFORMS.items():
        if _host_is(host, *suffixes):
            found.append(Signal(f"other:{name}", {"host": host}, url, rank))
    return found


def extract_signals(final_url: str, chain: list[str], html: str) -> list[Signal]:
    """Find platform signatures in the redirect chain, final URL, linked URLs and page text.

    Evidence from the redirect chain outranks links in the HTML, which outrank bare text
    mentions. Duplicates keep their highest rank. Result is sorted best-first.
    """
    best: dict[Any, Signal] = {}
    order: list[Any] = []

    def add(signal: Signal) -> None:
        if signal.key not in best:
            order.append(signal.key)
        if signal.key not in best or signal.rank > best[signal.key].rank:
            best[signal.key] = signal

    for url in [*chain, final_url]:
        for signal in _url_signals(url, RANK_CHAIN):
            add(signal)
    for url in collect_urls(html):
        for signal in _url_signals(url, RANK_LINK):
            add(signal)

    page_host = _host(final_url)
    lowered = html.lower()
    if page_host and ("/api/pcsx/" in lowered or re.search(r"\bpcsx\b", lowered)):
        add(Signal("eightfold", {"host": page_host}, "text mention of pcsx", RANK_MENTION))
    if page_host and "phenompeople" in lowered:
        rank = RANK_LINK if "phenompeople.com" in lowered else RANK_MENTION
        add(Signal("phenom", {"host": page_host}, "text mention of phenompeople", rank))

    return sorted((best[k] for k in order), key=lambda s: -s.rank)


_BLOCK_RE = re.compile(r"<(script|style|noscript|template)\b.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_SPA_MARKERS = (
    'id="root"', "id='root'", 'id="__next"', "__next_data__", "ng-app", "<app-root",
    'id="app"', "window.__initial_state__", "data-reactroot",
)  # fmt: skip


def visible_text_length(html: str) -> int:
    text = _TAG_RE.sub(" ", _BLOCK_RE.sub(" ", html))
    return len(" ".join(html_lib.unescape(text).split()))


def classify_empty_page(html: str) -> str:
    """`js-rendered` if the static HTML has (almost) no content of its own, else `no-signal`."""
    length = visible_text_length(html)
    spa = any(marker in html.lower() for marker in _SPA_MARKERS)
    return "js-rendered" if length < 400 or (spa and length < 1500) else "no-signal"


# --- polite HTTP ----------------------------------------------------------------------------


class PoliteClient:
    """One request at a time, a minimum delay between requests to the same host, and retries
    with exponential backoff on network errors, 429 and 5xx only (CLAUDE.md rule 4)."""

    def __init__(self, client: httpx.AsyncClient, delay: float = 1.0) -> None:
        self._client = client
        self._delay = delay
        self._lock = asyncio.Lock()
        self._last: dict[str, float] = {}

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        async with self._lock:
            host = _host(url)
            for attempt in range(MAX_ATTEMPTS):
                loop = asyncio.get_running_loop()
                wait = self._last.get(host, float("-inf")) + self._delay - loop.time()
                if wait > 0:
                    await asyncio.sleep(wait)
                try:
                    resp = await self._client.request(method, url, **kwargs)
                except httpx.TransportError:
                    self._last[host] = loop.time()
                    if attempt == MAX_ATTEMPTS - 1:
                        raise
                    await asyncio.sleep(2.0**attempt)
                    continue
                self._last[host] = loop.time()
                if (resp.status_code != 429 and resp.status_code < 500) or (
                    attempt == MAX_ATTEMPTS - 1
                ):
                    return resp
                retry_after = resp.headers.get("Retry-After", "")
                backoff = float(retry_after) if retry_after.isdigit() else 2.0**attempt
                await asyncio.sleep(min(backoff, 30.0))
            raise AssertionError("unreachable")

    async def json(self, method: str, url: str, **kwargs: Any) -> tuple[int, Any]:
        resp = await self.request(method, url, **kwargs)
        try:
            return resp.status_code, resp.json()
        except ValueError:
            return resp.status_code, None


@dataclass
class Page:
    status: str  # ok | blocked | not-found | http-error | error | no-careers-url
    http_status: int | None = None
    final_url: str | None = None
    chain: list[str] = field(default_factory=list)
    html: str = ""
    detail: str = ""


async def fetch_page(pc: PoliteClient, url: str | None) -> Page:
    if not url:
        return Page("no-careers-url")
    try:
        resp = await pc.request("GET", url, headers={"Accept": "text/html,*/*"})
    except httpx.HTTPError as exc:
        return Page("error", detail=f"{type(exc).__name__}: {exc}")
    chain = [str(r.url) for r in resp.history]
    page = Page("ok", resp.status_code, str(resp.url), chain, detail="")
    if resp.status_code in (401, 403, 429):
        page.status = "blocked"
    elif resp.status_code in (404, 410):
        page.status = "not-found"
    elif resp.status_code >= 400:
        page.status = "http-error"
    else:
        page.html = resp.text[:MAX_HTML_CHARS]
    if page.status != "ok":
        page.detail = f"HTTP {resp.status_code}"
    return page


# --- verification ---------------------------------------------------------------------------


@dataclass
class Verification:
    verified: bool
    total: int | None = None
    india: int | None = None
    partial: bool = False  # india count covers only a sample of the board
    note: str = ""
    config: dict[str, str] | None = None  # resolved config (e.g. the Eightfold domain)


def _not_verified(note: str) -> Verification:
    return Verification(False, note=note)


async def verify_simple(pc: PoliteClient, signal: Signal, company: Company) -> Verification:
    """Greenhouse / Lever / Ashby / SmartRecruiters: reuse the Phase 0 endpoints and parsers."""
    spec = next(s for s in ATS_SPECS if s.ats.value == signal.platform)
    slug = signal.config[spec.config_key]
    status, data = await pc.json("GET", spec.url(slug))
    if status != 200:
        return _not_verified(f"HTTP {status} from {spec.ats} board {slug!r}")
    board: Board | None = spec.parse(data)
    if board is None:
        return _not_verified("unexpected response shape")
    if board.total <= 0:
        return _not_verified(f"board {slug!r} exists but has 0 jobs")
    if spec.needs_name_match and not names_match(company.name, board.api_company_name):
        return _not_verified(f"company name mismatch: API says {board.api_company_name!r}")
    note = f"API company: {board.api_company_name}" if board.api_company_name else ""
    return Verification(True, board.total, board.india, board.partial, note, signal.config)


async def verify_workday(pc: PoliteClient, signal: Signal) -> Verification:
    cfg = signal.config
    if not all(cfg.get(k) for k in ("host", "tenant", "site")):
        return _not_verified("incomplete config: could not read the Workday site from the URL")
    url = f"https://{cfg['host']}/wday/cxs/{cfg['tenant']}/{cfg['site']}/jobs"
    body = {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""}
    status, data = await pc.json("POST", url, json=body)
    if status != 200 or not isinstance(data, dict):
        return _not_verified(f"HTTP {status} from {url}")
    postings, total = data.get("jobPostings"), data.get("total")
    if not isinstance(postings, list) or not isinstance(total, int):
        return _not_verified("unexpected response shape")
    if total <= 0:
        return _not_verified("board has 0 jobs")
    india, scanned = 0, 0
    page = postings
    for page_no in range(MAX_SAMPLE_PAGES):
        india += sum(is_india(p.get("locationsText")) for p in page if isinstance(p, dict))
        scanned += len(page)
        if scanned >= total or page_no == MAX_SAMPLE_PAGES - 1:
            break
        status, data = await pc.json("POST", url, json={**body, "offset": scanned})
        page = data.get("jobPostings") if status == 200 and isinstance(data, dict) else None
        if not isinstance(page, list) or not page:
            break
    note = "India count is approximate: 'N Locations' entries are not expanded"
    return Verification(True, total, india, scanned < total, note, cfg)


def registrable_domain(host: str) -> str:
    labels = host.lower().split(".")
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in {"co", "com", "org", "net"}:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def eightfold_domain_candidates(company: Company, final_url: str | None, html: str) -> list[str]:
    """Eightfold's `domain` cannot be read from a URL, so guess it and let the API decide."""
    candidates: list[str] = []
    for url in collect_urls(html):
        candidates += parse_qs(urlparse(url).query).get("domain", [])
    for url in (company.careers_url, final_url):
        host = _host(url or "")
        if not host:
            continue
        if _host_is(host, "eightfold.ai"):
            candidates.append(host.split(".")[0] + ".com")
        else:
            candidates.append(registrable_domain(host))
    candidates.append(company.slug.replace("-", "") + ".com")
    return list(dict.fromkeys(c.lower() for c in candidates if c))[:MAX_VERIFY_CANDIDATES]


async def verify_eightfold(
    pc: PoliteClient, signal: Signal, company: Company, page: Page
) -> Verification:
    host = signal.config["host"]
    notes = []
    for domain in eightfold_domain_candidates(company, page.final_url, page.html):
        base = f"https://{host}/api/pcsx/search?domain={domain}&start=0"
        status, data = await pc.json("GET", base)
        body = data.get("data") if isinstance(data, dict) else None
        positions = body.get("positions") if isinstance(body, dict) else None
        if status == 200 and isinstance(positions, list) and positions:
            total = body.get("count") if isinstance(body.get("count"), int) else len(positions)
            status, data = await pc.json("GET", base + "&location=India")
            body = data.get("data") if isinstance(data, dict) else None
            india = body.get("count") if isinstance(body, dict) else None
            return Verification(
                True, total, india if isinstance(india, int) else None, False,
                "" if isinstance(india, int) else "India count call failed",
                {"host": host, "domain": domain},
            )  # fmt: skip
        notes.append(f"{domain}: HTTP {status}" if status != 200 else f"{domain}: no jobs")
    return _not_verified("no domain worked (" + "; ".join(notes) + ")")


async def verify_oracle_hcm(pc: PoliteClient, signal: Signal) -> Verification:
    host, site = signal.config["host"], signal.config["site"]
    base = (
        f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
        "?onlyData=true&expand=requisitionList.secondaryLocations"
        f"&finder=findReqs;siteNumber={site},limit=25,offset={{offset}},sortBy=POSTING_DATES_DESC"
    )
    total, scanned, india = 0, 0, 0
    for page_no in range(MAX_SAMPLE_PAGES):
        status, data = await pc.json(
            "GET", base.format(offset=scanned), headers={"Accept": "application/json"}
        )
        items = data.get("items") if isinstance(data, dict) else None
        item = items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else {}
        reqs = item.get("requisitionList")
        if status != 200 or not isinstance(reqs, list):
            if page_no == 0:
                return _not_verified(f"HTTP {status} or unexpected response shape")
            break
        if page_no == 0:
            total = item.get("TotalJobsCount") if isinstance(item.get("TotalJobsCount"), int) else 0
            if total <= 0:
                return _not_verified("board has 0 jobs")
        india += sum(_oracle_is_india(r) for r in reqs if isinstance(r, dict))
        scanned += len(reqs)
        if not reqs or scanned >= total:
            break
    note = f"India count is a sample: first {scanned} of {total} jobs, newest first"
    return Verification(True, total, india, scanned < total, note, signal.config)


def _oracle_is_india(req: dict) -> bool:
    country = str(req.get("PrimaryLocationCountry") or "").strip().lower()
    return country in {"in", "india"} or is_india(req.get("PrimaryLocation"))


async def verify(pc: PoliteClient, signal: Signal, company: Company, page: Page) -> Verification:
    try:
        if signal.platform == "workday":
            return await verify_workday(pc, signal)
        if signal.platform == "eightfold":
            return await verify_eightfold(pc, signal, company, page)
        if signal.platform == "oracle_hcm":
            return await verify_oracle_hcm(pc, signal)
        if signal.platform in VERIFIABLE:
            return await verify_simple(pc, signal, company)
    except httpx.HTTPError as exc:
        return _not_verified(f"{type(exc).__name__}: {exc}")
    return _not_verified("no verifier for this platform")


# --- per-company flow -----------------------------------------------------------------------


@dataclass
class CompanyResult:
    company: Company
    page: Page
    outcome: str  # a platform value, "other:<name>", or a page status / js-rendered / no-signal
    signals: list[Signal] = field(default_factory=list)
    chosen: Signal | None = None
    verification: Verification | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def verified(self) -> bool:
        return bool(self.verification and self.verification.verified)


async def fingerprint_company(pc: PoliteClient, company: Company) -> CompanyResult:
    page = await fetch_page(pc, company.careers_url)
    if page.status != "ok":
        return CompanyResult(company, page, page.status, notes=[page.detail] if page.detail else [])

    signals = extract_signals(page.final_url or "", page.chain, page.html)
    result = CompanyResult(company, page, "no-signal", signals)
    if not signals:
        result.outcome = classify_empty_page(page.html)
        return result

    candidates = [s for s in signals if s.platform in VERIFIABLE][:MAX_VERIFY_CANDIDATES]
    for signal in candidates:
        verification = await verify(pc, signal, company, page)
        result.chosen, result.verification = signal, verification
        if verification.verified:
            break
        result.notes.append(f"{signal.platform}: {verification.note}")
    if not candidates:
        result.chosen = signals[0]
    result.outcome = result.chosen.platform
    others = sorted({s.platform for s in signals if s != result.chosen})
    if others:
        result.notes.append("also seen: " + ", ".join(others))
    return result


async def run(pc: PoliteClient, companies: list[Company]) -> list[CompanyResult]:
    results = []
    for company in companies:
        try:
            result = await fingerprint_company(pc, company)
        except Exception as exc:  # one company must never crash the run
            log.exception("fingerprinting %s failed", company.name)
            result = CompanyResult(
                company, Page("error"), "error", notes=[f"{type(exc).__name__}: {exc}"]
            )
        log.info("%s: %s%s", company.name, result.outcome, " (verified)" if result.verified else "")
        results.append(result)
    return results


# --- report ---------------------------------------------------------------------------------

NEEDS_LOOK = {"js-rendered", "no-signal", "blocked", "not-found", "http-error", "error",
              "no-careers-url"}  # fmt: skip


def _cell(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _flow(config: dict[str, str]) -> str:
    return "{" + ", ".join(f"{k}: {v}" for k, v in config.items()) + "}" if config else "—"


def _display(outcome: str) -> str:
    if outcome.startswith("other:"):
        return outcome.split(":", 1)[1] + " (unsupported)"
    return DISPLAY_NAMES.get(outcome, outcome)


def _final_config(result: CompanyResult) -> dict[str, str]:
    if result.verified and result.verification and result.verification.config:
        return result.verification.config
    return result.chosen.config if result.chosen else {}


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{(parsed.hostname or '').lower()}{parsed.path.rstrip('/')}"


def _count_cell(value: int | None, partial: bool = False) -> str:
    if value is None:
        return "—"
    return f"≥{value}" if partial else str(value)


def render_report(results: list[CompanyResult], now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    counts: Counter[str] = Counter()
    verified_counts: Counter[str] = Counter()
    for r in results:
        counts[r.outcome] += 1
        verified_counts[r.outcome] += r.verified

    summary = []
    for key in [*DISPLAY_NAMES, *sorted(k for k in counts if k.startswith("other:"))]:
        if counts[key]:
            if key in VERIFIABLE:
                detail = f" ({verified_counts[key]} verified, {counts[key] - verified_counts[key]} unverified)"
            else:
                detail = ""
            summary.append(f"- {_display(key)}: {counts[key]}{detail}")
    for key in sorted(NEEDS_LOOK):
        if counts[key]:
            summary.append(f"- {key}: {counts[key]}")

    rows = []
    for r in results:
        if r.outcome in NEEDS_LOOK:
            rows.append(
                f"| {_cell(r.company.name)} | {r.outcome} | — | — | — | — | {_cell('; '.join(r.notes))} |"
            )
            continue
        v = r.verification
        status = "✅ verified" if r.verified else "⚠️ unverified guess"
        if v is None:
            status = "— (detected only)"
        notes = list(r.notes)
        if v and v.verified and v.note:
            notes.insert(0, v.note)
        if r.chosen and r.chosen.evidence:
            notes.append(f"evidence: {r.chosen.evidence[:100]}")
        rows.append(
            f"| {_cell(r.company.name)} | {_cell(_display(r.outcome))} | "
            f"{_cell(_flow(_final_config(r)))} | {status} | "
            f"{_count_cell(v.total) if v and v.verified else '—'} | "
            f"{_count_cell(v.india, v.partial) if v and v.verified else '—'} | "
            f"{_cell('; '.join(notes))} |"
        )

    suggestions = [
        f"- {r.company.name} (`{r.company.slug}`): `ats: {r.outcome}, ats_config: "
        f"{_flow(_final_config(r))}`"
        for r in results
        if r.verified
    ]
    redirects = [
        f"- {r.company.name}: `{r.company.careers_url}` → `{r.page.final_url}`"
        for r in results
        if r.page.final_url
        and r.company.careers_url
        and _normalize_url(r.page.final_url) != _normalize_url(r.company.careers_url)
    ]
    look = [
        f"- {r.company.name} (`{r.company.slug}`): {r.outcome}"
        + (f" — {'; '.join(r.notes)}" if r.notes else "")
        for r in results
        if r.outcome in NEEDS_LOOK or (r.chosen and not r.verified)
    ]

    return "\n".join(
        [
            "# Platform fingerprint report",
            "",
            f"Generated {now:%Y-%m-%d %H:%M} UTC by `scripts/fingerprint_platforms.py`. "
            + "Suggestions only: companies.yaml is not modified.",
            "",
            f"{len(results)} companies covered. Verified = a live API call returned HTTP 200 and at "
            + "least one job. Job counts are for the whole board; India counts are approximate "
            + "(`≥` = counted from a sample).",
            "",
            "## Summary",
            "",
            *(summary or ["- (nothing processed)"]),
            "",
            "## Results",
            "",
            "| Company | Platform | Config | Verified? | Jobs | India jobs | Notes |",
            "|---|---|---|---|---|---|---|",
            *rows,
            "",
            "## Suggested companies.yaml updates (verified only)",
            "",
            *(suggestions or ["- none"]),
            "",
            "## Suggested careers_url changes (redirects)",
            "",
            *(redirects or ["- none"]),
            "",
            "## Needs a human look (js-rendered, blocked, unverified, unsupported...)",
            "",
            *(look or ["- none"]),
            "",
        ]
    )


# --- CLI ------------------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--companies", type=Path, default=DEFAULT_COMPANIES)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--delay", type=float, default=1.0, help="seconds between requests per host"
    )
    parser.add_argument("--only", default="", help="comma-separated company names or slugs")
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
        print("No companies with `ats: unknown` to fingerprint.")
        return
    log.info("fingerprinting %d companies", len(companies))

    async def go() -> list[CompanyResult]:
        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT_S,
            follow_redirects=True,
            max_redirects=MAX_REDIRECTS,
        ) as client:
            return await run(PoliteClient(client, args.delay), companies)

    results = asyncio.run(go())
    args.report.write_text(render_report(results), encoding="utf-8")
    verified = sum(r.verified for r in results)
    print(f"{len(results)} companies, {verified} verified. Report written to {args.report}")


if __name__ == "__main__":
    main()
