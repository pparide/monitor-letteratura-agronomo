"""EuropePMC fetcher.

EuropePMC REST API: https://europepmc.org/RestfulWebService
Bias toward life sciences: utile per fitopatologia, ecologia, biologia.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

EUROPEPMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
DEFAULT_TIMEOUT = 30


def _normalize_epmc(result: dict[str, Any]) -> dict[str, Any]:
    """Normalize an EuropePMC result to our internal paper dict."""
    authors_str = result.get("authorString") or ""
    authors = [a.strip() for a in authors_str.split(",") if a.strip()]

    pub_year = result.get("pubYear")
    try:
        year = int(pub_year) if pub_year else None
    except (TypeError, ValueError):
        year = None

    return {
        "title": result.get("title") or "",
        "doi": (result.get("doi") or "").lower(),
        "authors": authors,
        "year": year,
        "publication_date": result.get("firstPublicationDate"),
        "abstract": result.get("abstractText") or "",
        "journal": result.get("journalTitle") or "",
        "openalex_source_id": "",
        "is_oa": result.get("isOpenAccess") == "Y",
        "oa_url": (
            f"https://europepmc.org/article/{result.get('source', 'MED')}/{result.get('id', '')}"
            if result.get("isOpenAccess") == "Y" else None
        ),
        "cited_by_count": int(result.get("citedByCount", 0) or 0),
        "openalex_id": "",
        "source_fetcher": "europepmc",
    }


def fetch_europepmc(
    *,
    query: str,
    since_days: int = 14,
    max_results: int = 50,
) -> list[dict[str, Any]]:
    """Search EuropePMC by query.

    Returns normalized paper dicts.
    """
    since_date = (datetime.now(timezone.utc) - timedelta(days=since_days)).strftime("%Y-%m-%d")
    # EuropePMC query syntax: query string + filter on FIRST_PDATE
    epmc_query = f'({query}) AND FIRST_PDATE:[{since_date} TO 3000-12-31]'

    params: dict[str, Any] = {
        "query": epmc_query,
        "format": "json",
        "pageSize": str(min(max_results, 100)),
        "resultType": "core",
        "sort": "FIRST_PDATE_D desc",
    }

    try:
        response = requests.get(EUROPEPMC_BASE, params=params, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        print(f"[europepmc] error fetching (query={query!r}): {exc}")
        return []
    except ValueError as exc:
        print(f"[europepmc] JSON decode error: {exc}")
        return []

    time.sleep(0.1)

    results = (data.get("resultList") or {}).get("result") or []
    return [_normalize_epmc(r) for r in results]
