import httpx
import pytest
import respx

from tracker.http import USER_AGENT, make_client

URL = "https://api.example.com/jobs"


async def test_sends_user_agent_and_returns_json():
    with respx.mock:
        route = respx.get(URL).respond(200, json={"ok": True})
        async with make_client(delay=0, backoff=0) as client:
            resp = await client.get(URL)
    assert resp.json() == {"ok": True}
    assert route.calls.last.request.headers["User-Agent"] == USER_AGENT
    assert "github.com/Sarthzk/internship-tracker" in USER_AGENT


async def test_retries_on_503_then_succeeds():
    with respx.mock:
        route = respx.get(URL).mock(
            side_effect=[httpx.Response(503), httpx.Response(503), httpx.Response(200, json=[])]
        )
        async with make_client(delay=0, backoff=0) as client:
            resp = await client.get(URL)
    assert resp.status_code == 200
    assert route.call_count == 3


async def test_gives_up_after_three_attempts():
    with respx.mock:
        route = respx.get(URL).respond(503)
        async with make_client(delay=0, backoff=0) as client:
            resp = await client.get(URL)
    assert resp.status_code == 503
    assert route.call_count == 3


async def test_retries_on_429():
    with respx.mock:
        route = respx.get(URL).mock(side_effect=[httpx.Response(429), httpx.Response(200)])
        async with make_client(delay=0, backoff=0) as client:
            resp = await client.get(URL)
    assert resp.status_code == 200
    assert route.call_count == 2


@pytest.mark.parametrize("status", [400, 403, 404])
async def test_no_retry_on_4xx(status):
    with respx.mock:
        route = respx.get(URL).respond(status)
        async with make_client(delay=0, backoff=0) as client:
            resp = await client.get(URL)
    assert resp.status_code == status
    assert route.call_count == 1


async def test_retries_network_errors_then_raises():
    with respx.mock:
        route = respx.get(URL).mock(side_effect=httpx.ConnectError("boom"))
        async with make_client(delay=0, backoff=0) as client:
            with pytest.raises(httpx.ConnectError):
                await client.get(URL)
    assert route.call_count == 3


async def test_one_request_at_a_time_per_host():
    import asyncio

    active = 0
    peak = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return httpx.Response(200, json={})

    async with make_client(inner=httpx.MockTransport(handler), delay=0, backoff=0) as client:
        await asyncio.gather(*(client.get(f"{URL}?n={i}") for i in range(5)))
    assert peak == 1


async def test_429_waits_five_times_longer_than_a_server_error(monkeypatch):
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr("tracker.http.asyncio.sleep", fake_sleep)
    with respx.mock:
        respx.get(URL).mock(
            side_effect=[httpx.Response(429), httpx.Response(429), httpx.Response(200)]
        )
        async with make_client(delay=0, backoff=1.0) as client:
            assert (await client.get(URL)).status_code == 200
        respx.get(URL).mock(
            side_effect=[httpx.Response(503), httpx.Response(503), httpx.Response(200)]
        )
        async with make_client(delay=0, backoff=1.0) as client:
            assert (await client.get(URL)).status_code == 200
    assert [w for w in waits if w >= 1] == [5.0, 10.0, 1.0, 2.0]


async def test_retry_after_header_still_wins(monkeypatch):
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr("tracker.http.asyncio.sleep", fake_sleep)
    with respx.mock:
        respx.get(URL).mock(
            side_effect=[httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200)]
        )
        async with make_client(delay=0, backoff=1.0) as client:
            await client.get(URL)
    assert [w for w in waits if w >= 1] == [7.0]
