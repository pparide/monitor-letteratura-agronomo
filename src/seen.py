"""Manage seen.json — set of DOIs already processed in past digests."""
from __future__ import annotations

import json
from pathlib import Path


def load_seen(filepath: Path) -> set[str]:
    """Load set of seen DOIs (lowercase). Empty set if file doesn't exist."""
    if not filepath.exists():
        return set()
    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return {d.lower() for d in data if d}
        if isinstance(data, dict) and "seen" in data:
            return {d.lower() for d in data["seen"] if d}
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[seen] error loading {filepath}: {exc}")
    return set()


def save_seen(filepath: Path, seen: set[str]) -> None:
    """Save sorted list of DOIs to JSON."""
    sorted_seen = sorted(seen)
    filepath.write_text(
        json.dumps(sorted_seen, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
