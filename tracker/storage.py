"""Load/save data/listings.json and data/health.json.

Output is deterministic (sorted keys, 2-space indent, records sorted by id / slug, trailing
newline), so saving unchanged data produces identical bytes and the workflow commits nothing.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from pydantic import BaseModel

from tracker.models import HealthRecord, Listing


def _dumps(records: list[BaseModel]) -> str:
    data = [r.model_dump(mode="json") for r in records]
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _write_if_changed(path: Path, text: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return True


def load_listings(path: Path) -> list[Listing]:
    if not path.exists():
        return []
    return [Listing.model_validate(item) for item in json.loads(path.read_text(encoding="utf-8"))]


def save_listings(path: Path, listings: list[Listing]) -> bool:
    """Returns True if the file changed."""
    return _write_if_changed(path, _dumps(sorted(listings, key=lambda li: li.id)))


def load_health(path: Path) -> dict[str, HealthRecord]:
    if not path.exists():
        return {}
    records = [HealthRecord.model_validate(i) for i in json.loads(path.read_text("utf-8"))]
    return {r.company_slug: r for r in records}


def save_health(path: Path, health: dict[str, HealthRecord]) -> bool:
    """Returns True if the file changed."""
    return _write_if_changed(path, _dumps([health[slug] for slug in sorted(health)]))
