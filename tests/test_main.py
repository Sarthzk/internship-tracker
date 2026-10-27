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


# --- WhatsApp wiring ---


class FakeSender:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.ok = True

    async def send(self, text: str) -> bool:
        if self.ok:
            self.sent.append(text)
        return self.ok


def old_health(tmp_path) -> None:
    """Pretend both companies were fetched successfully before, so it is not a first run."""
    from tracker.models import HealthRecord
    from tracker.storage import save_health

    save_health(
        tmp_path / "health.json",
        {
            "acme": HealthRecord(company_slug="acme", last_success=T0.date(), last_count=1),
            "beta": HealthRecord(company_slug="beta", last_success=T0.date(), last_count=0),
        },
    )


async def test_new_listing_is_sent_once_and_marked_notified(tmp_path):
    old_health(tmp_path)
    sender = FakeSender()
    with respx.mock:
        respx.get(GH).respond(200, json=gh_jobs(("Software Engineer Intern", "Pune")))
        respx.get(LV).respond(200, json=[])
        first = await go(tmp_path, sender=sender, pause=0)
        second = await go(tmp_path, now=T0 + timedelta(minutes=15), sender=sender, pause=0)
    assert len(sender.sent) == 1 and "Software Engineer Intern" in sender.sent[0]
    assert first.alerts_sent == 1 and second.alerts_sent == 0
    [li] = load_listings(tmp_path / "listings.json")
    assert li.notified is True


async def test_failed_send_is_retried_next_run(tmp_path):
    old_health(tmp_path)
    sender = FakeSender()
    sender.ok = False
    with respx.mock:
        respx.get(GH).respond(200, json=gh_jobs(("Software Engineer Intern", "Pune")))
        respx.get(LV).respond(200, json=[])
        down = await go(tmp_path, sender=sender, pause=0)
        [li] = load_listings(tmp_path / "listings.json")
        assert li.notified is False and down.alerts_pending == 1
        sender.ok = True
        await go(tmp_path, now=T0 + timedelta(minutes=15), sender=sender, pause=0)
    assert len(sender.sent) == 1
    assert load_listings(tmp_path / "listings.json")[0].notified is True


async def test_no_sender_leaves_listings_unnotified(tmp_path):
    old_health(tmp_path)
    with respx.mock:
        respx.get(GH).respond(200, json=gh_jobs(("Software Engineer Intern", "Pune")))
        respx.get(LV).respond(200, json=[])
        summary = await go(tmp_path, sender=None)
    assert summary.alerts_pending == 1
    assert load_listings(tmp_path / "listings.json")[0].notified is False


async def test_first_fetch_sends_one_summary_not_one_per_listing(tmp_path):
    sender = FakeSender()
    with respx.mock:
        respx.get(GH).respond(
            200,
            json=gh_jobs(("Software Engineer Intern", "Pune"), ("Data Science Intern", "Mumbai")),
        )
        respx.get(LV).respond(200, json=[])
        await go(tmp_path, sender=sender, pause=0)
        await go(tmp_path, now=T0 + timedelta(minutes=15), sender=sender, pause=0)
    assert len(sender.sent) == 1 and "Now tracking 2 companies" in sender.sent[0]
    assert "Acme (2)" in sender.sent[0]
    assert all(li.notified for li in load_listings(tmp_path / "listings.json"))


async def test_company_failing_on_first_try_is_not_a_first_fetch_yet(tmp_path):
    sender = FakeSender()
    with respx.mock:
        gh = respx.get(GH).respond(503)
        respx.get(LV).respond(200, json=[])
        await go(tmp_path, sender=sender, pause=0)
        gh.respond(200, json=gh_jobs(("Software Engineer Intern", "Pune")))
        await go(tmp_path, now=T0 + timedelta(minutes=15), sender=sender, pause=0)
    assert any("Acme (1)" in m for m in sender.sent)


async def test_admin_alert_once_after_three_failures_and_once_on_recovery(tmp_path):
    old_health(tmp_path)
    sender = FakeSender()
    with respx.mock:
        gh = respx.get(GH).respond(503)
        respx.get(LV).respond(200, json=[])
        for i in range(6):
            await go(tmp_path, now=T0 + timedelta(minutes=15 * i), sender=sender, pause=0)
        down = [m for m in sender.sent if "failed" in m]
        assert len(down) == 1 and "Acme has failed 3 runs" in down[0]
        gh.respond(200, json=gh_jobs(("Software Engineer Intern", "Pune")))
        for i in range(6, 9):
            await go(tmp_path, now=T0 + timedelta(minutes=15 * i), sender=sender, pause=0)
    assert len([m for m in sender.sent if "working again" in m]) == 1


async def test_dry_run_never_sends(tmp_path):
    sender = FakeSender()
    with respx.mock:
        respx.get(GH).respond(200, json=gh_jobs(("Software Engineer Intern", "Pune")))
        respx.get(LV).respond(200, json=[])
        await go(tmp_path, dry_run=True, sender=sender, pause=0)
    assert sender.sent == []


def test_check_command_prints_counts_and_writes_nothing(tmp_path, capsys):
    (tmp_path / "companies.yaml").write_text(
        "companies:\n  - {name: Acme, slug: acme, tier: 1, ats: greenhouse,"
        " ats_config: {board_token: acme}, enabled: false}\n"
    )
    with respx.mock:
        respx.get(GH).respond(
            200, json=gh_jobs(("Software Engineer Intern", "Pune"), ("Chef", "Pune"))
        )
        code = main(["check", "--companies", "acme", "--data-dir", str(tmp_path)])
    assert code == 0
    assert "OK   acme: 2 postings, 1 India tech internships" in capsys.readouterr().out
    assert [p.name for p in tmp_path.iterdir()] == ["companies.yaml"]


def test_check_command_fails_loudly(tmp_path, capsys):
    (tmp_path / "companies.yaml").write_text(
        "companies:\n  - {name: Acme, slug: acme, tier: 1, ats: greenhouse,"
        " ats_config: {board_token: acme}, enabled: true}\n"
    )
    with respx.mock:
        respx.get(GH).respond(404)
        assert main(["check", "--companies", "acme", "--data-dir", str(tmp_path)]) == 1
    assert main(["check", "--companies", "nope", "--data-dir", str(tmp_path)]) == 2
