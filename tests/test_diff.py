from datetime import UTC, date, datetime, timedelta

from tracker.diff import merge
from tracker.models import Listing, Status

T0 = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


def listing(ext_id: str = "1", slug: str = "acme", **overrides) -> Listing:
    data = {
        "id": f"lever:{slug}:{ext_id}",
        "company": slug.title(),
        "company_slug": slug,
        "title": "Software Engineer Intern",
        "category": "swe",
        "locations": ["Bengaluru"],
        "is_remote": False,
        "url": f"https://example.com/{ext_id}",
        "source": "lever",
        "external_id": ext_id,
        "first_seen": T0,
        "last_seen": T0.date(),
    }
    data.update(overrides)
    return Listing.model_validate(data)


def test_new_posting_is_added_open_and_unnotified():
    now = T0 + timedelta(days=1)
    result = merge([], {"acme": [listing("1")]}, {"acme": True}, now)
    assert result.new_ids == ["lever:acme:1"]
    new = result.listings[0]
    assert new.status is Status.open and new.notified is False
    assert new.first_seen == now and new.last_seen == now.date()


def test_existing_posting_refreshes_and_resets_misses():
    old = listing("1", missed_runs=2, notified=True)
    now = T0 + timedelta(days=2)
    result = merge([old], {"acme": [listing("1", title="SWE Intern 2027")]}, {"acme": True}, now)
    assert result.new_ids == []
    got = result.listings[0]
    assert got.missed_runs == 0 and got.last_seen == now.date()
    assert got.title == "SWE Intern 2027"
    assert got.first_seen == T0 and got.notified is True


def test_absent_after_success_counts_a_miss_and_closes_at_three():
    current = [listing("1")]
    for i in range(1, 4):
        result = merge(current, {"acme": []}, {"acme": True}, T0 + timedelta(minutes=15 * i))
        current = result.listings
        if i < 3:
            assert current[0].status is Status.open and current[0].missed_runs == i
    closed = current[0]
    assert closed.status is Status.closed and closed.missed_runs == 3
    assert closed.closed_at == T0 + timedelta(minutes=45)
    assert result.closed_ids == ["lever:acme:1"]


def test_absent_after_failed_fetch_changes_nothing():
    old = listing("1", missed_runs=2)
    result = merge([old], {"acme": []}, {"acme": False}, T0 + timedelta(hours=1))
    assert result.listings[0] == old


def test_failed_fetch_ignores_fetched_list():
    result = merge([], {"acme": [listing("1")]}, {"acme": False}, T0)
    assert result.listings == [] and result.new_ids == []


def test_company_not_fetched_this_run_is_untouched():
    old = listing("1", slug="other", missed_runs=1)
    result = merge([old], {"acme": []}, {"acme": True}, T0)
    assert result.listings[0] == old


def test_closed_posting_that_reappears_is_reopened():
    closed = listing("1", status="closed", missed_runs=3, closed_at=T0)
    result = merge([closed], {"acme": [listing("1")]}, {"acme": True}, T0 + timedelta(days=3))
    got = result.listings[0]
    assert got.status is Status.open and got.missed_runs == 0 and got.closed_at is None
    assert result.reopened_ids == ["lever:acme:1"] and result.new_ids == []


def test_already_closed_listing_is_not_closed_again():
    closed = listing("1", status="closed", missed_runs=3, closed_at=T0)
    result = merge([closed], {"acme": []}, {"acme": True}, T0 + timedelta(days=1))
    assert result.listings[0] == closed and result.closed_ids == []


def test_input_is_not_mutated():
    old = listing("1")
    merge([old], {"acme": []}, {"acme": True}, T0)
    assert old.missed_runs == 0


def test_date_posted_kept_when_fresh_has_none():
    old = listing("1", date_posted=date(2026, 10, 1))
    result = merge([old], {"acme": [listing("1")]}, {"acme": True}, T0)
    assert result.listings[0].date_posted == date(2026, 10, 1)
