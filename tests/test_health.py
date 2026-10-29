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


def test_last_count_is_not_rewritten_by_small_changes():
    prev = HealthRecord(company_slug="acme", last_count=5)
    record, ok = record_fetch(prev, "acme", count=7, error=None, now=T0)
    assert ok and record.last_count == 5
    assert record == record_fetch(record, "acme", count=6, error=None, now=T0)[0]


def test_last_count_follows_zero_changes():
    prev = HealthRecord(company_slug="acme", last_count=0)
    record, ok = record_fetch(prev, "acme", count=3, error=None, now=T0)
    assert ok and record.last_count == 3


# --- sharp drops (CLAUDE.md rule 1) ---


def test_sharp_drop_is_a_failure_at_first():
    prev = HealthRecord(company_slug="acme", last_count=100)
    record, ok = record_fetch(prev, "acme", count=30, error=None, now=T0)
    assert not ok and record.zero_since == T0 and record.last_count == 100
    assert record.last_error == "returned only 30 postings (previously 100)"


def test_sharp_drop_accepted_after_24_hours_and_moves_the_reference():
    prev = HealthRecord(company_slug="acme", last_count=100, zero_since=T0)
    record, ok = record_fetch(prev, "acme", count=30, error=None, now=T0 + timedelta(hours=24))
    assert ok and record.last_count == 30 and record.zero_since is None


def test_drop_that_recovers_clears_the_grace_clock():
    prev = HealthRecord(company_slug="acme", last_count=100, zero_since=T0)
    record, ok = record_fetch(prev, "acme", count=96, error=None, now=T0 + timedelta(hours=1))
    assert ok and record.zero_since is None and record.last_count == 100


def test_moderate_or_small_drops_are_normal():
    for count in (60, 51, 95):  # not below half
        _, ok = record_fetch(
            HealthRecord(company_slug="a", last_count=100), "a", count=count, error=None, now=T0
        )
        assert ok, count
    _, ok = record_fetch(  # halved, but only 8 postings: below DROP_MIN
        HealthRecord(company_slug="a", last_count=16), "a", count=7, error=None, now=T0
    )
    assert ok


def test_reference_moves_when_count_leaves_its_band():
    prev = HealthRecord(company_slug="acme", last_count=100)
    assert record_fetch(prev, "acme", count=115, error=None, now=T0)[0].last_count == 100
    assert record_fetch(prev, "acme", count=130, error=None, now=T0)[0].last_count == 130


# --- crash alert de-duplication ---


def test_crash_alert_only_on_first_failure():
    from tracker.health import is_recovery, should_send_crash_alert

    assert should_send_crash_alert(None) and should_send_crash_alert("success")
    assert should_send_crash_alert("cancelled")
    assert not should_send_crash_alert("failure")
    assert is_recovery("failure") and not is_recovery("success") and not is_recovery(None)
