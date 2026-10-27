from datetime import UTC, datetime, timedelta

from tracker.health import record_fetch
from tracker.models import HealthRecord

T0 = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


def test_first_success():
    record, ok = record_fetch(None, "acme", count=5, error=None, now=T0)
    assert ok and record.last_count == 5 and record.last_success == T0.date()
    assert record.consecutive_failures == 0 and record.last_error is None


def test_error_is_a_failure_and_keeps_last_count():
    prev = HealthRecord(company_slug="acme", last_count=5)
    record, ok = record_fetch(prev, "acme", count=None, error="HTTP 500", now=T0)
    assert not ok and record.consecutive_failures == 1 and record.last_count == 5
    assert record.last_error == "HTTP 500"


def test_failures_accumulate_and_recovery_resets():
    record = None
    for _ in range(3):
        record, _ = record_fetch(record, "acme", count=None, error="boom", now=T0)
    assert record.consecutive_failures == 3
    record, ok = record_fetch(record, "acme", count=2, error=None, now=T0)
    assert ok and record.consecutive_failures == 0 and record.last_error is None


def test_zero_after_nonzero_is_a_failure_at_first():
    prev = HealthRecord(company_slug="acme", last_count=5)
    record, ok = record_fetch(prev, "acme", count=0, error=None, now=T0)
    assert not ok and record.zero_since == T0 and record.last_count == 5


def test_zero_stays_a_failure_within_24_hours():
    prev = HealthRecord(company_slug="acme", last_count=5, zero_since=T0)
    _, ok = record_fetch(prev, "acme", count=0, error=None, now=T0 + timedelta(hours=23))
    assert not ok


def test_zero_accepted_after_24_hours():
    prev = HealthRecord(company_slug="acme", last_count=5, zero_since=T0)
    record, ok = record_fetch(prev, "acme", count=0, error=None, now=T0 + timedelta(hours=24))
    assert ok and record.last_count == 0 and record.zero_since is None


def test_nonzero_clears_zero_since():
    prev = HealthRecord(company_slug="acme", last_count=5, zero_since=T0)
    record, ok = record_fetch(prev, "acme", count=3, error=None, now=T0 + timedelta(hours=1))
    assert ok and record.zero_since is None


def test_zero_on_first_ever_fetch_is_a_success():
    _, ok = record_fetch(None, "acme", count=0, error=None, now=T0)
    assert ok


def test_long_error_is_truncated():
    record, _ = record_fetch(None, "acme", count=None, error="x" * 1000, now=T0)
    assert len(record.last_error) == 300
