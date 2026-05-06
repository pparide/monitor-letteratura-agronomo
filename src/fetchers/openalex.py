"""OpenAlex fetcher.

OpenAlex API: https://docs.openalex.org/
Rate limit polite pool: 100k req/giorno con email, 10/sec.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import requests

OPENALEX_BASE = "https://api.openalex.org/works"
USER_EMAIL = "parideporpora@gmail.com"  # polite pool
DEFAULT_TIMEOUT = 30


def _reconstruct_abstract(inverted_index: Optional[dict[str, list[int]]]) -> str:
    """OpenAlex stores abstracts as inverted_index for legal reasons.
    Reconstruct linear text by sorting word positions.
    """
    if not inverted_index:
        return ""
    word_positions: list[tuple[int, str]] = []
    for word, positions in inverted_index.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort()
    return " ".join(word for _, word in word_positions)


def _normalize_paper(work: dict[str, Any]) -> dict[str, Any]:
    """Convert an OpenAlex 'work' object to our internal paper dict."""
    primary_loc = work.get("primary_location") or {}
    source = primary_loc.get("source") or {}
    open_access = work.get("open_access") or {}

    authorships = work.get("authorships") or []
    authors = [
        (a.get("author") or {}).get("display_name", "")
        for a in authorships
        if a.get("author")
    ]

    return {
        "title": work.get("title") or "",
        "doi": (work.get("doi") or "").replace("https://doi.org/", "").lower(),
        "authors": authors,
        "year": work.get("publication_year"),
        "publication_date": work.get("publication_date"),
        "abstract": _reconstruct_abstract(work.get("abstract_inverted_index")),
        "journal": source.get("display_name") or "",
        "openalex_source_id": (source.get("id") or "").replace("https://openalex.org/", ""),
        "is_oa": bool(open_access.get("is_oa")),
        "oa_url": open_access.get("oa_url"),
        "cited_by_count": work.get("cited_by_count", 0) or 0,
        "openalex_id": (work.get("id") or "").replace("https://openalex.org/", ""),
        "source_fetcher": "openalex",
    }


def fetch_openalex(
    *,
    source_id: Optional[str] = None,
    author_id: Optional[str] = None,
    query: Optional[str] = None,
    since_days: int = 14,
    max_results: int = 50,
) -> list[dict[str, Any]]:
    """Fetch papers from OpenAlex by source/author/query.

    Pass exactly one of source_id, author_id, or query.
    Returns list of normalized paper dicts.
    """
    if not any([source_id, author_id, query]):
        raise ValueError("Must pass one of source_id, author_id, query")

    since_date = (datetime.now(timezone.utc) - timedelta(days=since_days)).strftime("%Y-%m-%d")
    filters = [f"from_publication_date:{since_date}"]

    if source_id:
        filters.append(f"primary_location.source.id:{source_id}")
    if author_id:
        filters.append(f"author.id:{author_id}")

    params: dict[str, Any] = {
        "mailto": USER_EMAIL,
        "per-page": str(min(max_results, 200)),
        "filter": ",".join(filters),
        "sort": "publication_date:desc",
    }
    if query:
        params["search"] = query

    try:
        response = requests.get(OPENALEX_BASE, params=params, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        print(f"[openalex] error fetching (params={params}): {exc}")
        return []
    except ValueError as exc:
        print(f"[openalex] JSON decode error: {exc}")
        return []

    # polite pool: 10 req/sec → small sleep between calls
    time.sleep(0.15)

    papers = [_normalize_paper(w) for w in data.get("results", [])]
    return papers
