"""Deduplicate papers by DOI (primary key) or by (title, year) fallback."""
from __future__ import annotations

from typing import Any


def deduplicate_papers(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a list with duplicates removed.

    Preference order for the kept entry:
    1. Has DOI > no DOI
    2. From OpenAlex (richer metadata) > CrossRef > EuropePMC > RSS
    3. Has abstract > no abstract
    """
    fetcher_priority = {"openalex": 0, "crossref": 1, "europepmc": 2, "rss": 3}

    by_key: dict[tuple, dict[str, Any]] = {}

    for p in papers:
        if p.get("doi"):
            key = ("doi", p["doi"].lower())
        else:
            title_short = (p.get("title", "") or "")[:120].lower().strip()
            year = p.get("year")
            if not title_short:
                # Skip entries with no DOI and no title
                continue
            key = ("title_year", title_short, year)

        existing = by_key.get(key)
        if existing is None:
            by_key[key] = p
            continue

        # Resolve conflict: prefer richer source / has abstract
        existing_pri = fetcher_priority.get(existing.get("source_fetcher", ""), 99)
        new_pri = fetcher_priority.get(p.get("source_fetcher", ""), 99)
        if new_pri < existing_pri:
            by_key[key] = p
        elif new_pri == existing_pri:
            # Tie-break on abstract presence
            if (p.get("abstract") or "") and not (existing.get("abstract") or ""):
                by_key[key] = p

    return list(by_key.values())
