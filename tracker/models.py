"""Pydantic models. Keep in sync with the data model table in CLAUDE.md."""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


UtcDatetime = Annotated[AwareDatetime, AfterValidator(_to_utc)]
"""A timezone-aware datetime, normalized to UTC. Naive datetimes are rejected."""

BatchYear = Annotated[int, Field(ge=2000, le=2100)]

Source = Literal[
    "greenhouse",
    "lever",
    "ashby",
    "smartrecruiters",
    "workday",
    "eightfold",
    "oracle_hcm",
    "phenom",
    "custom",
    "community",
]

SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"

# ats_config keys a company needs once its ATS is known. `custom` and `unknown` have no schema,
# and `phenom` has no fetcher yet, so its config is free-form.
REQUIRED_ATS_CONFIG: dict[str, tuple[str, ...]] = {
    "greenhouse": ("board_token",),
    "lever": ("site",),
    "ashby": ("site",),
    "smartrecruiters": ("company_id",),
    "workday": ("host", "tenant", "site"),
    "eightfold": ("host", "domain"),
    "oracle_hcm": ("host", "site"),
}


class AtsType(StrEnum):
    greenhouse = "greenhouse"
    lever = "lever"
    ashby = "ashby"
    smartrecruiters = "smartrecruiters"
    workday = "workday"
    eightfold = "eightfold"
    oracle_hcm = "oracle_hcm"
    phenom = "phenom"
    custom = "custom"
    unknown = "unknown"


class Category(StrEnum):
    swe = "swe"
    data_ml = "data_ml"
    quant = "quant"
    hardware = "hardware"
    product = "product"
    other = "other"


class Status(StrEnum):
    open = "open"
    closed = "closed"


class Term(StrEnum):
    summer = "summer"
    winter = "winter"
    six_month = "six_month"
    other = "other"
    unknown = "unknown"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Company(_Model):
    """One entry in data/companies.yaml."""

    name: str
    slug: str = Field(pattern=SLUG_PATTERN)  # our internal id, not the ATS board token
    tier: Literal[1, 2]  # 1 = must-have, 2 = nice-to-have
    ats: AtsType
    ats_config: dict[str, Any] = Field(default_factory=dict)
    careers_url: str | None = Field(default=None, pattern=r"^https?://\S+$")
    enabled: bool = False
    notes: str | None = None

    @model_validator(mode="after")
    def _check_ats_and_config(self) -> Company:
        if self.enabled and self.ats == AtsType.unknown:
            raise ValueError(f"company {self.slug!r} is enabled but ats is 'unknown'")
        missing = [k for k in REQUIRED_ATS_CONFIG.get(self.ats, ()) if not self.ats_config.get(k)]
        if missing:
            raise ValueError(f"company {self.slug!r} ({self.ats}) is missing ats_config: {missing}")
        return self


class RawPosting(_Model):
    """A posting as returned by a fetcher, before filtering. Never persisted."""

    company_slug: str
    source: Source
    external_id: str
    title: str
    locations: list[str]
    is_remote: bool = False
    url: str
    date_posted: date | None = None
    # In-memory only, for enrichment. Excluded from serialization (CLAUDE.md rule 2).
    description: str | None = Field(default=None, exclude=True, repr=False)


class Enrichment(_Model):
    eligible_batches: list[BatchYear] | None = None
    term: Term = Term.unknown
    duration_months: int | None = Field(default=None, ge=1, le=24)
    stipend: str | None = None
    degree: str | None = None
    model: str
    enriched_at: UtcDatetime


class Listing(_Model):
    id: str
    company: str
    company_slug: str
    title: str
    category: Category
    locations: list[str]
    is_remote: bool
    url: str
    source: Source
    external_id: str
    date_posted: date | None = None
    first_seen: UtcDatetime
    # A date, not a datetime: it only changes once a day, so runs don't commit noise.
    last_seen: date
    status: Status = Status.open
    missed_runs: int = Field(default=0, ge=0)
    closed_at: UtcDatetime | None = None
    notified: bool = False
    enrichment: Enrichment | None = None

    @staticmethod
    def make_id(source: str, company_slug: str, external_id: str) -> str:
        return f"{source}:{company_slug}:{external_id}"

    @model_validator(mode="after")
    def _id_matches_parts(self) -> Listing:
        expected = self.make_id(self.source, self.company_slug, self.external_id)
        if self.id != expected:
            raise ValueError(f"id {self.id!r} does not match expected {expected!r}")
        return self


class HealthRecord(_Model):
    """Per-company fetcher health, stored in data/health.json.

    Only fields that change when something actually happens are stored (no per-run timestamps),
    so a quiet run leaves health.json byte-for-byte unchanged.
    """

    company_slug: str
    last_success: date | None = None  # day of the last successful fetch
    consecutive_failures: int = Field(default=0, ge=0)
    last_error: str | None = None
    last_count: int | None = Field(default=None, ge=0)  # postings from last SUCCESSFUL fetch
    # When a fetch first returned 0 postings after a previous non-zero one (CLAUDE.md rule 1).
    zero_since: UtcDatetime | None = None


def load_companies(path: Path) -> list[Company]:
    """Load and validate data/companies.yaml (a mapping with a `companies` list)."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [Company.model_validate(entry) for entry in raw.get("companies") or []]
