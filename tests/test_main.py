from datetime import UTC, datetime, timedelta

import respx

from tracker.http import make_client
from tracker.main import main, run
from tracker.models import Company
from tracker.storage import load_health, load_listings

T0 = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)

GH = "https://boards-api.greenhouse.io/v1/boards/acme/jobs"
LV = "https://api.lever.co/v0/postings/beta"


def companies() -> list[Company]:
    return [
        Company(
            name="Acme",
            slug="acme",
            tier=1,
            ats="greenhouse",
            ats_config={"board_token": "acme"},
            enabled=True,
        ),
        Company(
            name="Beta", slug="beta", tier=1, ats="lever", ats_config={"site": "beta"}, enabled=True
        ),
        Company(
            name="Off", slug="off", tier=1, ats="lever", ats_config={"site": "off"}, enabled=False
        ),
    ]


def gh_jobs(*jobs: tuple[str, str], first_id: int = 100) -> dict:
    return {
        "jobs": [
            {
                "id": first_id + i,
                "title": title,
                "absolute_url": f"https://gh.example/{first_id + i}",
                "location": {"name": location},
            }
            for i, (title, location) in enumerate(jobs)
        ]
    }


async def go(tmp_path, now=T0, **kwargs):
    async with make_client(delay=0, backoff=0) as client:
        return await run(companies(), client, tmp_path, now=now, **kwargs)


async def test_end_to_end_filters_saves_and_survives_one_failure(tmp_path):
    with respx.mock:
        respx.get(GH).respond(
            200,
            json=gh_jobs(
                ("Software Engineer Intern", "Bengaluru, India"),
                ("Software Engineer Intern", "Indianapolis, IN"),
                ("Senior Engineer", "Pune"),
                ("Marketing Intern", "Mumbai"),
            ),
        )
        respx.get(LV).respond(500)
        summary = await go(tmp_path)
    assert summary.ok == ["acme"] and list(summary.failed) == ["beta"]
    listings = load_listings(tmp_path / "listings.json")
    assert [li.external_id for li in listings] == ["100"]
    health = load_health(tmp_path / "health.json")
    assert health["acme"].last_count == 4 and health["beta"].consecutive_failures == 1
    assert "off" not in health


async def test_second_run_same_day_changes_nothing(tmp_path):
    jobs = gh_jobs(("Software Engineer Intern", "Pune"))
    with respx.mock:
        respx.get(GH).respond(200, json=jobs)
        respx.get(LV).respond(200, json=[])
        first = await go(tmp_path)
        before = {p.name: p.read_bytes() for p in tmp_path.glob("*.json")}
        second = await go(tmp_path, now=T0 + timedelta(minutes=15))
    assert first.wrote is True and second.wrote is False
    assert second.merge.new_ids == []
    assert {p.name: p.read_bytes() for p in tmp_path.glob("*.json")} == before


async def test_failed_fetch_does_not_close_listings(tmp_path):
    with respx.mock:
        gh = respx.get(GH).respond(200, json=gh_jobs(("Software Engineer Intern", "Pune")))
        respx.get(LV).respond(200, json=[])
        await go(tmp_path)
        gh.respond(503)
        for i in range(1, 6):
            summary = await go(tmp_path, now=T0 + timedelta(minutes=15 * i))
    assert "acme" in summary.failed
    [li] = load_listings(tmp_path / "listings.json")
    assert li.status == "open" and li.missed_runs == 0


async def test_listing_closes_after_three_successful_misses(tmp_path):
    with respx.mock:
        gh = respx.get(GH).respond(
            200, json=gh_jobs(("Software Engineer Intern", "Pune"), ("Data Intern", "Pune"))
        )
        respx.get(LV).respond(200, json=[])
        await go(tmp_path)
        gh.respond(200, json=gh_jobs(("Data Intern", "Pune"), first_id=101))
        for i in range(1, 4):
            summary = await go(tmp_path, now=T0 + timedelta(minutes=15 * i))
    by_id = {li.external_id: li for li in load_listings(tmp_path / "listings.json")}
    assert by_id["100"].status == "closed" and by_id["101"].status == "open"
    assert summary.merge.closed_ids == ["greenhouse:acme:100"]


async def test_dry_run_writes_nothing(tmp_path):
    with respx.mock:
        respx.get(GH).respond(200, json=gh_jobs(("Software Engineer Intern", "Pune")))
        respx.get(LV).respond(200, json=[])
        summary = await go(tmp_path, dry_run=True)
    assert len(summary.merge.new_ids) == 1
    assert list(tmp_path.iterdir()) == []


async def test_company_without_fetcher_is_a_recorded_failure(tmp_path):
    custom = Company(name="Cust", slug="cust", tier=1, ats="custom", enabled=True)
    async with make_client(delay=0, backoff=0) as client:
        summary = await run([custom], client, tmp_path, now=T0)
    assert "no fetcher" in summary.failed["cust"]


def test_cli_dry_run_prints_summary(tmp_path, capsys):
    (tmp_path / "companies.yaml").write_text(
        "companies:\n  - {name: Acme, slug: acme, tier: 1, ats: greenhouse,"
        " ats_config: {board_token: acme}, enabled: true}\n"
    )
    with respx.mock:
        respx.get(GH).respond(200, json=gh_jobs(("Software Engineer Intern", "Pune")))
        code = main(["run", "--dry-run", "--data-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0 and "companies OK: 1" in out and "NEW Acme" in out
    assert not (tmp_path / "listings.json").exists()
