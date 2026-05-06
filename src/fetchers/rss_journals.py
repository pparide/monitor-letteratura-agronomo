"""RSS feed fetcher for journal alerts.

Uses feedparser to parse RSS/Atom feeds of OA journals.
Note: RSS feeds usually only give title + link + (sometimes) abstract,
not full metadata. Use OpenAlex/CrossRef for richer data; RSS is for
quick discovery and as fallback when OpenAlex source ID is unavailable.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from email.utils import parsedate_to_datetime

import feedparser


def _extract_doi_from_link(link: str) -> str:
    """Best-effort DOI extraction from a typical journal article URL."""
    if not link:
        return ""
    # Pattern: https://doi.org/10.xxxx/yyyy
    if "doi.org/" in link:
        return link.split("doi.org/", 1)[1].lower()
    # Pattern MDPI: https://www.mdpi.com/2073-445X/14/5/1234
    # → no DOI in URL, return empty
    return ""


def _normalize_rss_entry(entry: Any, feed_title: str) -> dict[str, Any]:
    """Convert a feedparser entry to our internal paper dict."""
    link = entry.get("link", "") or ""
    doi = _extract_doi_from_link(link)

    # RSS feeds rarely include separate authors; if present, parse:
    authors = []
    if "authors" in entry and entry["authors"]:
        authors = [a.get("name", "") for a in entry["authors"] if a.get("name")]
    elif "author" in entry and entry["author"]:
        authors = [entry["author"]]

    # Try to extract a year from published date
    year = None
    published_str = entry.get("published") or entry.get("updated") or ""
    if published_str:
        try:
            dt = parsedate_to_datetime(published_str)
            year = dt.year if dt else None
        except (TypeError, ValueError):
            pass

    abstract = entry.get("summary", "") or entry.get("description", "") or ""
    # Strip HTML tags (basic)
    if abstract:
        import re
        abstract = re.sub(r"<[^>]+>", "", abstract).strip()

    return {
        "title": entry.get("title", "") or "",
        "doi": doi,
        "authors": authors,
        "year": year,
        "publication_date": published_str or None,
        "abstract": abstract,
        "journal": feed_title or "",
        "openalex_source_id": "",
        "is_oa": True,  # RSS feeds we follow are OA journals
        "oa_url": link,
        "cited_by_count": 0,  # not available from RSS
        "openalex_id": "",
        "source_fetcher": "rss",
    }


def fetch_rss(rss_url: str, since_days: int = 14) -> list[dict[str, Any]]:
    """Fetch and parse an RSS feed, return normalized paper dicts.

    Filters entries published in last `since_days` days.
    """
    try:
        parsed = feedparser.parse(rss_url)
    except Exception as exc:
        print(f"[rss] error parsing {rss_url}: {exc}")
        return []

    if parsed.bozo and not parsed.entries:
        print(f"[rss] feed possibly malformed: {rss_url}")
        return []

    feed_title = (parsed.feed or {}).get("title", "") or ""
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)

    papers: list[dict[str, Any]] = []
    for entry in parsed.entries:
        # Filter by publication date if available
        published_str = entry.get("published") or entry.get("updated") or ""
        keep = True
        if published_str:
            try:
                dt = parsedate_to_datetime(published_str)
                if dt and dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt and dt < cutoff:
                    keep = False
            except (TypeError, ValueError):
                pass
        if keep:
            papers.append(_normalize_rss_entry(entry, feed_title))

    return papers
