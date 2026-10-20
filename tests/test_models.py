from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from tracker.models import (
    Category,
    Company,
    Enrichment,
    HealthRecord,
    Listing,
    RawPosting,
    Status,
    Term,
)

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
NAIVE = datetime(2026, 10, 20, 12, 0)
IST = timezone(timedelta(hours=5, minutes=30))


def listing_data(**overrides) -> dict:
    data = {
        "id": "greenhouse:stripe:123",
        "company": "Stripe",
        "company_slug": "stripe",
        "title": "Software Engineer Intern",
        "category": "swe",
        "locations": ["Bengaluru, India"],
        "is_remote": False,
        "url": "https://stripe.com/jobs/123",
        "source": "greenhouse",
        "external_id": "123",
        "date_posted": "2026-10-01",
        "first_seen": NOW,
        "last_seen": NOW,
    }
    data.update(overrides)
    return data


def enrichment_data(**overrides) -> dict:
    data = {"model": "llama-test", "enriched_at": NOW}
    data.update(overrides)
    return data


def company_data(**overrides) -> dict:
    data = {"name": "D. E. Shaw", "slug": "de-shaw", "tier": 1, "ats": "unknown"}
    data.update(overrides)
    return data


# --- Listing ---


def test_listing_defaults():
    listing = Listing.model_validate(listing_data())
    assert listing.status is Status.open
    assert listing.missed_runs == 0
    assert listing.notified is False
    assert listing.closed_at is None
    assert listing.enrichment is None
    assert listing.date_posted == date(2026, 10, 1)


@pytest.mark.parametrize(
    "field,value",
    [("category", "marketing"), ("status", "paused"), ("source", "indeed")],
)
def test_listing_rejects_bad_enum_values(field, value):
    with pytest.raises(ValidationError):
        Listing.model_validate(listing_data(**{field: value}))


@pytest.mark.parametrize("field", ["first_seen", "last_seen", "closed_at"])
def test_listing_rejects_naive_datetimes(field):
    with pytest.raises(ValidationError):
        Listing.model_validate(listing_data(**{field: NAIVE}))


def test_listing_normalizes_datetimes_to_utc():
    ist_time = datetime(2026, 10, 20, 17, 30, tzinfo=IST)
    listing = Listing.model_validate(listing_data(first_seen=ist_time))
    assert listing.first_seen == NOW
    assert listing.first_seen.utcoffset() == timedelta(0)


def test_listing_accepts_iso_string_with_offset():
    listing = Listing.model_validate(listing_data(last_seen="2026-10-20T12:00:00Z"))
    assert listing.last_seen == NOW


def test_listing_rejects_mismatched_id():
    with pytest.raises(ValidationError, match="does not match"):
        Listing.model_validate(listing_data(id="lever:stripe:123"))


def test_make_id():
    assert Listing.make_id("lever", "cred", "abc") == "lever:cred:abc"


def test_listing_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        Listing.model_validate(listing_data(description="full JD text"))


def test_listing_rejects_negative_missed_runs():
    with pytest.raises(ValidationError):
        Listing.model_validate(listing_data(missed_runs=-1))


def test_listing_json_round_trip():
    listing = Listing.model_validate(
        listing_data(enrichment=enrichment_data(eligible_batches=[2027], term="summer"))
    )
    assert Listing.model_validate_json(listing.model_dump_json()) == listing


def test_all_category_values():
    assert {c.value for c in Category} == {
        "swe",
        "data_ml",
        "quant",
        "hardware",
        "product",
        "other",
    }


# --- Enrichment ---


def test_enrichment_defaults_are_unknown():
    enrichment = Enrichment.model_validate(enrichment_data())
    assert enrichment.term is Term.unknown
    assert enrichment.eligible_batches is None
    assert enrichment.duration_months is None
    assert enrichment.stipend is None
    assert enrichment.degree is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"term": "spring"},
        {"enriched_at": NAIVE},
        {"duration_months": 0},
        {"eligible_batches": [27]},
        {"invented": "x"},
    ],
)
def test_enrichment_rejects_invalid(overrides):
    with pytest.raises(ValidationError):
        Enrichment.model_validate(enrichment_data(**overrides))


# --- RawPosting ---


def test_raw_posting_never_serializes_description():
    posting = RawPosting(
        company_slug="stripe",
        source="greenhouse",
        external_id="1",
        title="Intern",
        locations=["Pune"],
        url="https://example.com/1",
        description="secret full job description",
    )
    assert posting.description == "secret full job description"
    assert "description" not in posting.model_dump()
    assert "secret" not in posting.model_dump_json()
    assert "secret" not in repr(posting)


# --- HealthRecord ---


def test_health_record_defaults():
    record = HealthRecord(company_slug="stripe")
    assert record.consecutive_failures == 0
    assert record.last_success is None
    assert record.last_count is None


@pytest.mark.parametrize("field", ["last_attempt", "last_success"])
def test_health_record_rejects_naive_datetimes(field):
    with pytest.raises(ValidationError):
        HealthRecord.model_validate({"company_slug": "stripe", field: NAIVE})


# --- Company ---


def test_company_defaults():
    company = Company.model_validate(company_data())
    assert company.enabled is False
    assert company.ats_config == {}
    assert company.notes is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"ats": "taleo"},
        {"tier": 3},
        {"slug": "D. E. Shaw"},
        {"slug": "de_shaw"},
        {"enabled": True},  # ats is still unknown
        {"atsconfig": {}},
    ],
)
def test_company_rejects_invalid(overrides):
    with pytest.raises(ValidationError):
        Company.model_validate(company_data(**overrides))


def test_company_enabled_with_known_ats():
    company = Company.model_validate(
        company_data(ats="workday", enabled=True, ats_config={"host": "x", "tenant": "y"})
    )
    assert company.enabled
