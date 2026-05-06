"""CrossRef fetcher.

CrossRef API: https://api.crossref.org
Rate limit: ~50 req/sec polite pool with mailto.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import requests

CROSSREF_BASE = "https://api.crossref.org/works"
USER_EMAIL = "parideporpora@gmail.com"
DEFAULT_TIMEOUT = 30


def _normalize_crossref(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize a CrossRef item to our internal paper dict."""
    title_list = item.get("title") or []
    title = title_list[0] if title_list else ""

    authors_list = item.get("author") or []
    authors = []
    for a in authors_list:
        given = a.get("given", "") or ""
        family = a.get("family", "") or ""
        name = (given + " " + family).strip()
        if name:
            authors.append(name)

    issued = (item.get("issued") or {}).get("date-parts") or [[None]]
    year = issued[0][0] if issued and issued[0] else None

    container_title = item.get("container-title") or []
    journal = container_title[0] if container_title else ""

    abstract = item.get("abstract") or ""
    # CrossRef abstracts often contain JATS XML — strip basic tags for readability
    if abstract:
        import re
        abstract = re.sub(r"<[^>]+>", "", abstract).strip()

    return {
        "title": title,
        "doi": (item.get("DOI") or "").lower(),
        "authors": authors,
        "year": year,
        "publication_date": None,
        "abstract": abstract,
        "journal": journal,
        "openalex_source_id": "",
        "is_oa": False,  # CrossRef doesn't reliably report OA status
        "oa_url": None,
        "cited_by_count": item.get("is-referenced-by-count", 0) or 0,
        "openalex_id": "",
        "source_fetcher": "crossref",
    }


def fetch_crossref(
    *,
    query: str,
    since_days: int = 14,
    max_results: int = 50,
) -> list[dict[str, Any]]:
    """Search CrossRef by free-text query.

    Returns normalized paper dicts.
    """
    since_date = (datetime.now(timezone.utc) - timedelta(days=since_days)).strftime("%Y-%m-%d")
    params: dict[str, Any] = {
        "query": query,
        "rows": str(min(max_results, 100)),
        "sort": "issued",
        "order": "desc",
        "filter": f"from-pub-date:{since_date}",
        "mailto": USER_EMAIL,
    }

    try:
        response = requests.get(CROSSREF_BASE, params=params, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        print(f"[crossref] error fetching (query={query!r}): {exc}")
        return []
    except ValueError as exc:
        print(f"[crossref] JSON decode error: {exc}")
        return []

    time.sleep(0.05)

    items = (data.get("message") or {}).get("items") or []
    return [_normalize_crossref(it) for it in items]
