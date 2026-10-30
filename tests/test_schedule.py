from datetime import UTC, datetime, timedelta

import pytest
import respx
from pydantic import ValidationError

from tests.test_main import GH, LV, T0, companies, gh_jobs
from tracker.http import make_client
from tracker.main import run
from tracker.models import Company
from tracker.schedule import is_due
from tracker.storage import load_health, load_listings

DAY = datetime(2026, 10, 30, tzinfo=UTC)


def company(slug: str = "acme", every: int = 10) -> Company:
    return Company(
        name=slug.title(),
        slug=slug,
        tier=1,
        ats="greenhouse",
        ats_config={"board_token": slug},
        enabled=True,
        check_every_minutes=every,
    )


def slots(c: Company) -> list[bool]:
    return [is_due(c, DAY + timedelta(minutes=10 * n)) for n in range(144)]


def test_default_interval_is_always_due():
    assert all(slots(company()))


def test_thirty_minutes_means_one_run_in_three():
    due = slots(company(every=30))
    assert sum(due) == 48
    assert all(sum(due[i : i + 3]) == 1 for i in range(0, 144, 3))


def test_sixty_minutes_means_one_run_in_six_and_is_stable():
    c = company(every=60)
    assert sum(slots(c)) == 24 and slots(c) == slots(c)


def test_runs_with_normal_jitter_stay_in_their_slot():
    c = company(every=30)
    base = next(
        DAY + timedelta(minutes=10 * n)
        for n in range(144)
        if is_due(c, DAY + timedelta(minutes=10 * n))
    )
    assert is_due(c, base + timedelta(seconds=9 * 60 + 59 - 0)) is True  # still inside the slot


def test_companies_are_spread_over_the_three_slots():
    first_due = {
        next(n for n in range(3) if is_due(company(slug, 30), DAY + timedelta(minutes=10 * n)))
        for slug in ("microsoft", "qualcomm", "paypal", "nvidia", "intel", "visa")
    }
    assert len(first_due) > 1


@pytest.mark.parametrize("value", [5, 15, 25, 0, -10, 2000])
def test_invalid_interval_is_rejected(value):
    with pytest.raises(ValidationError):
        company(every=value)


async def test_a_company_that_is_not_due_is_left_untouched(tmp_path):
    slow = companies()[0].model_copy(update={"check_every_minutes": 30})
    not_due = next(
        T0.replace(hour=0, minute=0) + timedelta(minutes=10 * n)
        for n in range(3)
        if not is_due(slow, T0.replace(hour=0, minute=0) + timedelta(minutes=10 * n))
    )
    others = [slow, *companies()[1:]]
    with respx.mock:
        gh = respx.get(GH).respond(200, json=gh_jobs(("Software Engineer Intern", "Pune")))
        respx.get(LV).respond(200, json=[])
        async with make_client(delay=0, backoff=0) as client:
            summary = await run(others, client, tmp_path, now=not_due)
    assert not gh.called
    assert "acme" not in summary.ok and "acme" not in summary.failed
    assert "acme" not in load_health(tmp_path / "health.json")
    assert load_listings(tmp_path / "listings.json") == []
