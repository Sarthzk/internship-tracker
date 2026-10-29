from datetime import UTC, datetime

from tracker.diff import MergeResult
from tracker.guards import find_id_churn
from tracker.models import Listing

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


def listing(slug: str, n: int, **overrides) -> Listing:
    data = {
        "id": f"lever:{slug}:{n}",
        "company": slug.title(),
        "company_slug": slug,
        "title": f"Intern {n}",
        "category": "swe",
        "locations": ["Pune"],
        "is_remote": False,
        "url": f"https://example.com/{slug}/{n}",
        "source": "lever",
        "external_id": str(n),
        "first_seen": NOW,
        "last_seen": NOW.date(),
    }
    data.update(overrides)
    return Listing.model_validate(data)


def result(new: int, vanished: int, slug: str = "acme") -> MergeResult:
    news = [listing(slug, 100 + i) for i in range(new)]
    gone = [listing(slug, i, missed_runs=1) for i in range(vanished)]
    return MergeResult(listings=news + gone, new_ids=[li.id for li in news])


def test_wholesale_replacement_is_churn():
    churn = find_id_churn(result(new=6, vanished=7), first_fetch=set())
    ids, vanished = churn["acme"]
    assert list(churn) == ["acme"] and len(ids) == 6 and vanished == 7


def test_a_burst_of_genuinely_new_listings_is_not_churn():
    assert find_id_churn(result(new=20, vanished=0), first_fetch=set()) == {}


def test_ordinary_turnover_is_not_churn():
    assert find_id_churn(result(new=3, vanished=3), first_fetch=set()) == {}


def test_first_fetch_is_never_churn():
    assert find_id_churn(result(new=9, vanished=9), first_fetch={"acme"}) == {}


def test_closed_listings_do_not_count_as_vanished():
    res = result(new=6, vanished=0)
    res.listings += [listing("acme", i, status="closed", missed_runs=3) for i in range(8)]
    assert find_id_churn(res, first_fetch=set()) == {}
