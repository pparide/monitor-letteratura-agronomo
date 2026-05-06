"""Entry point for the weekly literature digest.

Reads config/, calls fetchers, deduplicates, scores, writes digest, updates seen.json.
Designed to be called by GitHub Actions on a Monday cron schedule.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Allow `python -m src.main` and direct `python src/main.py`
if __package__ is None or __package__ == "":
    HERE = Path(__file__).resolve().parent
    sys.path.insert(0, str(HERE.parent))

from src.deduplicate import deduplicate_papers
from src.digest_writer import write_digest
from src.fetchers.crossref import fetch_crossref
from src.fetchers.europepmc import fetch_europepmc
from src.fetchers.openalex import fetch_openalex
from src.fetchers.rss_journals import fetch_rss
from src.scoring import score_paper
from src.seen import load_seen, save_seen


def main(*, since_days: int = 14, dry_run: bool = False) -> int:
    """Run the digest pipeline. Returns exit code.

    `dry_run=True` skips writing seen.json (used for smoke tests).
    """
    repo_root = Path(__file__).resolve().parent.parent
    config_dir = repo_root / "config"
    digest_dir = repo_root / "digest"

    # Load config
    sources = json.loads((config_dir / "sources.json").read_text(encoding="utf-8"))
    rules = json.loads((config_dir / "rules.json").read_text(encoding="utf-8"))
    seen = load_seen(config_dir / "seen.json")

    print(f"[main] starting digest run, since_days={since_days}, dry_run={dry_run}")
    print(f"[main] seen DOIs: {len(seen)}")

    fetch_summary: dict[str, int] = defaultdict(int)
    all_papers: list[dict[str, Any]] = []

    # 1. Journals: query by source_id (OpenAlex)
    for journal in sources.get("journals", []) or []:
        sid = journal.get("openalex_id")
        if sid:
            papers = fetch_openalex(source_id=sid, since_days=since_days)
            print(f"[main]   journal {journal.get('name','?')} (OpenAlex {sid}): {len(papers)} papers")
            fetch_summary["openalex_journal"] += len(papers)
            all_papers.extend(papers)

    # 2. Authors: query by author_id (OpenAlex)
    for author in sources.get("authors", []) or []:
        aid = author.get("openalex_id")
        if aid:
            # widen window for authors (paper might be slow to index)
            papers = fetch_openalex(author_id=aid, since_days=since_days * 2)
            print(f"[main]   author {author.get('name','?')} (OpenAlex {aid}): {len(papers)} papers")
            fetch_summary["openalex_author"] += len(papers)
            all_papers.extend(papers)

    # 3. Free-text queries: try OpenAlex + EuropePMC for cross-validation
    for q in sources.get("queries", []) or []:
        qstr = q.get("string")
        if not qstr:
            continue
        oa_papers = fetch_openalex(query=qstr, since_days=since_days)
        ep_papers = fetch_europepmc(query=qstr, since_days=since_days)
        print(f"[main]   query {qstr!r}: OpenAlex={len(oa_papers)}, EuropePMC={len(ep_papers)}")
        fetch_summary["openalex_query"] += len(oa_papers)
        fetch_summary["europepmc_query"] += len(ep_papers)
        all_papers.extend(oa_papers)
        all_papers.extend(ep_papers)

    # 4. RSS feeds: complementary discovery
    for rss_url in sources.get("rss_feeds", []) or []:
        papers = fetch_rss(rss_url, since_days=since_days)
        print(f"[main]   rss {rss_url}: {len(papers)} entries")
        fetch_summary["rss"] += len(papers)
        all_papers.extend(papers)

    print(f"[main] total fetched (pre-dedupe): {len(all_papers)}")

    # 5. Deduplicate by DOI
    deduped = deduplicate_papers(all_papers)
    print(f"[main] after dedupe: {len(deduped)}")

    # 6. Filter out already seen
    new_papers = [p for p in deduped if not p.get("doi") or p["doi"] not in seen]
    print(f"[main] new (not in seen): {len(new_papers)}")

    # 7. Score each paper
    for p in new_papers:
        s, area, kws = score_paper(p, rules)
        p["score"] = s
        p["area"] = area
        p["matched_keywords"] = kws

    # 8. Filter by minimum score threshold
    threshold = rules.get("min_score_threshold", 5)
    above_threshold = [p for p in new_papers if p["score"] >= threshold]
    above_threshold.sort(key=lambda p: p["score"], reverse=True)
    print(f"[main] above threshold {threshold}: {len(above_threshold)}")

    # 9. Write digest
    iso_year, iso_week, _ = datetime.now(timezone.utc).isocalendar()
    digest_filename = f"{iso_year}-W{iso_week:02d}_digest.md"
    digest_path = digest_dir / digest_filename
    write_digest(
        digest_path,
        above_threshold,
        fetch_summary=dict(fetch_summary),
        threshold=threshold,
    )
    print(f"[main] digest written: {digest_path}")

    # 10. Update seen (only DOIs of *new* papers, not just above threshold —
    #     so we don't re-show low-score paper next week)
    if not dry_run:
        for p in new_papers:
            if p.get("doi"):
                seen.add(p["doi"])
        save_seen(config_dir / "seen.json", seen)
        print(f"[main] seen.json updated: {len(seen)} DOIs total")
    else:
        print("[main] dry_run=True → seen.json NOT updated")

    return 0


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Weekly literature digest")
    parser.add_argument("--since-days", type=int, default=14,
                        help="lookback window in days (default 14)")
    parser.add_argument("--dry-run", action="store_true",
                        help="do not update seen.json (for smoke testing)")
    args = parser.parse_args()
    sys.exit(main(since_days=args.since_days, dry_run=args.dry_run))
