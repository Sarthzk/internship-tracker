import logging
from datetime import UTC, datetime, timedelta

import httpx
import respx

from tracker.health import RUN_GAP_ALERT, run_gap_message
from tracker.http import make_client
from tracker.main import GITHUB_API, PreviousRun, previous_run

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
ENV = {"GITHUB_TOKEN": "ghs_s3cr3t", "GITHUB_REPOSITORY": "me/tracker", "GITHUB_RUN_ID": "99"}
RUNS_URL = f"{GITHUB_API}/repos/me/tracker/actions/workflows/scrape.yml/runs"


# --- message ---


def test_no_alert_for_normal_gap_or_unknown_previous():
    assert run_gap_message(NOW - timedelta(minutes=12), NOW, "workflow_dispatch") is None
    assert run_gap_message(NOW - RUN_GAP_ALERT, NOW, "workflow_dispatch") is None
    assert run_gap_message(None, NOW, "schedule") is None


def test_alert_after_long_gap_names_the_cause():
    text = run_gap_message(NOW - timedelta(hours=3, minutes=5), NOW, "schedule")
    assert "3 h 5 min" in text and "backup cron" in text
    text = run_gap_message(NOW - timedelta(minutes=75), NOW, "workflow_dispatch")
    assert "1 h 15 min" in text and "cron-job.org" in text


# --- previous run lookup ---


async def lookup(env=ENV):
    async with make_client(delay=0, backoff=0) as client:
        return await previous_run(client, env)


async def test_skipped_outside_github_actions():
    assert await lookup({}) is None


async def test_returns_start_of_previous_run_skipping_this_one():
    runs = {
        "workflow_runs": [
            {"id": 99, "run_started_at": "2026-10-29T11:58:00Z"},
            {"id": 98, "run_started_at": "2026-10-29T11:48:00Z", "conclusion": "success"},
        ]
    }
    with respx.mock:
        route = respx.get(RUNS_URL).respond(200, json=runs)
        started = await lookup()
    assert started == PreviousRun(datetime(2026, 10, 29, 11, 48, tzinfo=UTC), "success")
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer ghs_s3cr3t"
    assert request.url.params["status"] == "completed"


async def test_errors_return_none_and_never_log_the_token(caplog):
    caplog.set_level(logging.DEBUG)
    with respx.mock:
        respx.get(RUNS_URL).respond(403, json={"message": "no"})
        assert await lookup() is None
    with respx.mock:
        respx.get(RUNS_URL).respond(200, json={"unexpected": True})
        assert await lookup() is None
    with respx.mock:
        respx.get(RUNS_URL).mock(side_effect=httpx.ConnectError("boom"))
        assert await lookup() is None
    assert "s3cr3t" not in caplog.text
