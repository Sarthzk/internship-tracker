"""Which website a company's posting links may point to.

A job board that is hacked, or a fake posting slipped into one, could send students to a phishing
site. So every alert link must be on a host we expect for that company: the hosts in its
`ats_config`, the job board's own domain, or the company's `link_hosts` in companies.yaml. A
listing on any other host is held back and the owner is asked to review it. Pure: no I/O.
"""

from __future__ import annotations

from urllib.parse import urlparse

from tracker.models import Company, Listing

# The job board's own domain, for boards whose links the board itself supplies.
BOARD_HOSTS: dict[str, tuple[str, ...]] = {
    "greenhouse": ("greenhouse.io",),
    "lever": ("jobs.lever.co",),
    "ashby": ("jobs.ashbyhq.com",),
    "smartrecruiters": ("jobs.smartrecruiters.com",),
}


def allowed_hosts(company: Company) -> set[str]:
    hosts = {
        str(company.ats_config[key]).lower()
        for key in ("host", "public_host")
        if company.ats_config.get(key)
    }
    hosts.update(BOARD_HOSTS.get(company.ats.value, ()))
    hosts.update(host.lower() for host in company.link_hosts)
    return hosts


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def is_allowed(url: str, company: Company) -> bool:
    """https, and the host is an allowed host or a subdomain of one."""
    if not url.startswith("https://"):
        return False
    host = host_of(url)
    return any(host == ok or host.endswith("." + ok) for ok in allowed_hosts(company))


def unexpected(listings: list[Listing], companies: dict[str, Company]) -> list[Listing]:
    """The listings whose link is not on a host we expect for their company."""
    return [
        li
        for li in listings
        if li.company_slug not in companies or not is_allowed(li.url, companies[li.company_slug])
    ]
