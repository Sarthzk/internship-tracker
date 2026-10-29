from datetime import UTC, datetime
from pathlib import Path

import pytest
import respx

from tests.test_main import GH, LV, FakeSender, go
from tracker.main import main
from tracker.models import HealthRecord, Listing
from tracker.storage import save_health, save_listings
from tracker.validate import DataError, check_files, check_listings

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


def listing(n: int = 1, **overrides) -> Listing:
    data = {
        "id": f"greenhouse:acme:{n}",
        "company": "Acme",
        "company_slug": "acme",
        "title": f"Software Engineer Intern {n}",
        "category": "swe",
        "locations": ["Pune"],
        "is_remote": False,
        "url": f"https://example.com/{n}",
        "source": "greenhouse",
        "external_id": str(n),
        "first_seen": NOW,
        "last_seen": NOW.date(),
    }
    data.update(overrides)
    return Listing.model_validate(data)


def write_good_data(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "companies.yaml").write_text(
        "companies:\n"
        "  - {name: Acme, slug: acme, tier: 1, ats: greenhouse, ats_config: {board_token: acme},"
        " enabled: true}\n",
        encoding="utf-8",
    )
    save_listings(data_dir / "listings.json", [listing(2), listing(1)])
    save_health(data_dir / "health.json", {"acme": HealthRecord(company_slug="acme", last_count=2)})


def test_good_data_passes(tmp_path):
    write_good_data(tmp_path)
    assert check_files(tmp_path) == ([], [])


def test_listing_problems_are_errors_or_warnings():
    errors, warnings = check_listings(
        [
            listing(1),
            listing(1),
            listing(2, url="http://example.com/2"),
            listing(3, title="x" * 400),
        ],
        {"acme"},
    )
    assert "duplicate listing id greenhouse:acme:1" in errors
    assert "greenhouse:acme:2: url is not https" in errors
    assert any("suspiciously long" in e for e in errors)
    _, warnings = check_listings([listing(1)], {"other"})
    assert warnings == ["greenhouse:acme:1: company 'acme' is not in companies.yaml"]


def test_hand_edited_or_corrupt_files_are_caught(tmp_path):
    write_good_data(tmp_path)
    path = tmp_path / "listings.json"
    path.write_text(path.read_text("utf-8").replace('"category": "swe"', '"category":"swe"', 1))
    errors, _ = check_files(tmp_path)
    assert errors == ["listings.json is not in canonical form"]
    path.write_text("[{broken")
    errors, _ = check_files(tmp_path)
    assert errors and errors[0].startswith("data file:")


def test_a_stored_description_field_is_rejected(tmp_path):
    write_good_data(tmp_path)
    path = tmp_path / "listings.json"
    path.write_text(
        path.read_text("utf-8").replace(
            '"company": "Acme"', '"description": "x", "company": "Acme"', 1
        )
    )
    errors, _ = check_files(tmp_path)
    assert errors and errors[0].startswith("data file:")


def test_cli_validate_exit_codes(tmp_path, capsys):
    write_good_data(tmp_path)
    assert main(["validate", "--data-dir", str(tmp_path)]) == 0
    assert "data OK" in capsys.readouterr().out
    (tmp_path / "health.json").write_text("not json")
    assert main(["validate", "--data-dir", str(tmp_path)]) == 1
    assert "ERROR" in capsys.readouterr().out


async def test_run_stops_before_notifying_or_saving_when_data_is_bad(tmp_path):
    sender = FakeSender()
    bad = {
        "jobs": [
            {
                "id": 1,
                "title": "Software Engineer Intern",
                "absolute_url": "http://insecure.example/1",
                "location": {"name": "Pune"},
            }
        ]
    }
    with respx.mock:
        respx.get(GH).respond(200, json=bad)
        respx.get(LV).respond(200, json=[])
        with pytest.raises(DataError):
            await go(tmp_path, sender=sender, pause=0)
    assert sender.sent == [] and not (tmp_path / "listings.json").exists()
