"""Telegram alerts: new internships to the owner, plus health alerts.

The Telegram Bot API takes the bot token in the URL path, so request URLs must never be logged.
Everything here logs only exception class names and HTTP status codes, and `tracker.main`
silences the httpx request logger.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

import httpx

from tracker.models import HealthRecord, Listing
from tracker.readme import IST

log = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"
COMBINE_AT = 5  # this many new listings at once -> a few combined messages instead of many
MAX_CHARS = 3500  # Telegram allows 4096 characters per message
FAILURE_ALERT_AFTER = 3  # consecutive failures before the owner is told


class Sender(Protocol):
    async def send(self, text: str) -> bool: ...


class Telegram:
    def __init__(self, client: httpx.AsyncClient, token: str, chat_id: str) -> None:
        self._client = client
        self._token = token
        self._chat_id = chat_id

    @classmethod
    def from_env(
        cls, client: httpx.AsyncClient, env: Mapping[str, str] | None = None
    ) -> Telegram | None:
        env = os.environ if env is None else env
        token, chat_id = env.get("TELEGRAM_BOT_TOKEN", ""), env.get("TELEGRAM_CHAT_ID", "")
        if not token or not chat_id:
            log.warning(
                "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set: Telegram alerts are skipped"
            )
            return None
        return cls(client, token, chat_id)

    async def send(self, text: str) -> bool:
        body = {
            "chat_id": self._chat_id,
            "text": text,
            "link_preview_options": {"is_disabled": True},
        }
        try:
            response = await self._client.post(
                f"{TELEGRAM_API}/bot{self._token}/sendMessage", json=body
            )
        except httpx.HTTPError as exc:
            log.warning("Telegram request failed: %s", type(exc).__name__)
            return False
        try:
            ok = response.status_code == 200 and response.json().get("ok") is True
        except ValueError:
            ok = False
        if not ok:
            log.warning("Telegram rejected the message: HTTP %d", response.status_code)
        return ok


@dataclass
class Alert:
    text: str
    ids: list[str] = field(default_factory=list)  # listing ids this message covers


def _where(listing: Listing) -> str:
    return "; ".join(listing.locations) or "location not stated"


def format_listing(listing: Listing) -> str:
    return f"🆕 {listing.company}: {listing.title[:150]}\n📍 {_where(listing)}\n🔗 {listing.url}"


def plan_alerts(listings: Iterable[Listing]) -> list[Alert]:
    """One message per listing, or a few combined messages once there are COMBINE_AT or more."""
    pending = sorted(listings, key=lambda li: (li.company, li.title, li.id))
    if len(pending) < COMBINE_AT:
        return [Alert(format_listing(li), [li.id]) for li in pending]

    chunks: list[list[Listing]] = [[]]
    size = 0
    for li in pending:
        entry = f"• {li.company}: {li.title[:150]} ({_where(li)})\n  {li.url}"
        if chunks[-1] and size + len(entry) > MAX_CHARS:
            chunks.append([])
            size = 0
        chunks[-1].append(li)
        size += len(entry) + 1
    alerts = []
    for n, chunk in enumerate(chunks, start=1):
        header = f"🆕 {len(pending)} new internships" + (
            f" ({n}/{len(chunks)})" if len(chunks) > 1 else ""
        )
        lines = [f"• {li.company}: {li.title[:150]} ({_where(li)})\n  {li.url}" for li in chunk]
        alerts.append(Alert(header + "\n\n" + "\n".join(lines), [li.id for li in chunk]))
    return alerts


def format_tracking_started(open_counts: Mapping[str, int]) -> str:
    """One summary for companies fetched successfully for the first time (no per-job flood)."""
    total = sum(open_counts.values())
    parts = ", ".join(f"{name} ({n})" for name, n in sorted(open_counts.items()))
    return (
        f"📋 Now tracking {len(open_counts)} companies. "
        f"{total} India tech internships already open: {parts}. "
        "You'll only be alerted about new ones from now on."
    )


async def deliver(sender: Sender, alerts: list[Alert], pause: float = 2.0) -> set[str]:
    """Send alerts in order; returns the listing ids delivered.

    Stops at the first failure so a down or rate-limited service isn't hammered; the remaining
    listings stay un-notified and are retried on the next run.
    """
    delivered: set[str] = set()
    for n, alert in enumerate(alerts):
        if n and pause:
            await asyncio.sleep(pause)
        if not await sender.send(alert.text):
            break
        delivered.update(alert.ids)
    return delivered


@dataclass
class HealthAlert:
    slug: str
    text: str
    alerted: bool  # value of HealthRecord.failure_alerted once this message is delivered


def plan_health_alerts(
    health: Mapping[str, HealthRecord], names: Mapping[str, str]
) -> list[HealthAlert]:
    """Tell the owner once when a company starts failing, and once when it recovers."""
    alerts = []
    for slug in sorted(names):
        record = health.get(slug)
        if record is None:
            continue
        name = names[slug]
        if record.consecutive_failures >= FAILURE_ALERT_AFTER and not record.failure_alerted:
            text = (
                f"⚠️ {name} has failed {record.consecutive_failures} runs in a row: "
                f"{record.last_error or 'unknown error'}"
            )
            alerts.append(HealthAlert(slug, text, alerted=True))
        elif record.consecutive_failures == 0 and record.failure_alerted:
            alerts.append(HealthAlert(slug, f"✅ {name} is working again.", alerted=False))
    return alerts


async def deliver_health_alerts(
    sender: Sender,
    alerts: list[HealthAlert],
    health: dict[str, HealthRecord],
    pause: float = 2.0,
) -> None:
    for n, alert in enumerate(alerts):
        if n and pause:
            await asyncio.sleep(pause)
        if await sender.send(alert.text):
            health[alert.slug].failure_alerted = alert.alerted


def format_crash(error: BaseException) -> str:
    return f"🚨 internship-tracker run crashed: {type(error).__name__}: {str(error)[:300]}"


MAX_ALERT_MESSAGES = 10  # per run; anything beyond stays un-notified and goes out next run
DIGEST_HOUR_IST = 9


def digest_due(now: datetime, previous_start: datetime | None) -> bool:
    """True for the first run of the day inside 09:00-09:09 IST.

    No stored state: with a run every 10 minutes the window holds one or two runs, so the digest
    is skipped when the previous run already started inside this window or later."""
    local = now.astimezone(IST)
    if local.hour != DIGEST_HOUR_IST or local.minute >= 10:
        return False
    window_start = local.replace(minute=0, second=0, microsecond=0)
    return previous_start is None or previous_start.astimezone(IST) < window_start


def format_churn(churn: Mapping[str, tuple[int, int]]) -> str:
    """One admin message for companies whose listings were replaced wholesale (name -> (new, gone))."""
    lines = [
        f"• {name}: {new} new while {gone} known ones vanished"
        for name, (new, gone) in sorted(churn.items())
    ]
    return (
        "⚠️ Possible site change, so these were NOT sent as new internships "
        "(they are in the README):\n" + "\n".join(lines)
    )


def format_recovered() -> str:
    return "✅ internship-tracker is running normally again."


def format_daily_digest(
    enabled: int,
    failing: Mapping[str, str],
    open_count: int,
    new_last_day: int,
) -> str:
    """The 9 AM status message: reassurance that the tracker is alive, and what is wrong."""
    lines = [
        "☀️ Daily report",
        f"{enabled - len(failing)} of {enabled} companies OK",
    ]
    for name, error in sorted(failing.items()):
        lines.append(f"  ⚠️ {name}: {error[:80]}")
    lines.append(f"{open_count} open India internships, {new_last_day} new in the last 24 hours")
    return "\n".join(lines)
