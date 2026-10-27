import json
from datetime import UTC, datetime

from tracker.models import HealthRecord, Listing
from tracker.storage import load_health, load_listings, save_health, save_listings

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


def listing(ext_id: str) -> Listing:
    return Listing(
        id=f"lever:acme:{ext_id}",
        company="Acme",
        company_slug="acme",
        title="Intern",
        category="swe",
        locations=["Pune"],
        is_remote=False,
        url="https://e.com/1",
        source="lever",
        external_id=ext_id,
        first_seen=NOW,
        last_seen=NOW.date(),
    )


def test_missing_files_are_empty(tmp_path):
    assert load_listings(tmp_path / "listings.json") == []
    assert load_health(tmp_path / "health.json") == {}


def test_listings_round_trip_sorted_and_formatted(tmp_path):
    path = tmp_path / "data" / "listings.json"
    assert save_listings(path, [listing("b"), listing("a")]) is True
    text = path.read_text()
    assert text.endswith("\n") and '\n  {\n    "category"' in text
    assert [item["id"] for item in json.loads(text)] == ["lever:acme:a", "lever:acme:b"]
    assert load_listings(path) == [listing("a"), listing("b")]


def test_saving_unchanged_data_is_a_no_op(tmp_path):
    path = tmp_path / "listings.json"
    save_listings(path, [listing("a")])
    before = path.read_bytes()
    mtime = path.stat().st_mtime_ns
    assert save_listings(path, [listing("a")]) is False
    assert path.read_bytes() == before and path.stat().st_mtime_ns == mtime


def test_health_round_trip(tmp_path):
    path = tmp_path / "health.json"
    health = {
        "b": HealthRecord(company_slug="b"),
        "a": HealthRecord(company_slug="a", last_count=2),
    }
    assert save_health(path, health) is True
    assert [i["company_slug"] for i in json.loads(path.read_text())] == ["a", "b"]
    assert load_health(path) == health
    assert save_health(path, health) is False
