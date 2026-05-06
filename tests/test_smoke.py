"""Smoke test E2E del motore.

Test offline: non chiama API esterne, simula i dati.
Verifica che la pipeline (deduplicate → score → write_digest → save_seen)
funzioni end-to-end con dati sintetici.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

# Add repo root to path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from src.deduplicate import deduplicate_papers
from src.digest_writer import write_digest
from src.scoring import score_paper
from src.seen import load_seen, save_seen


def _sample_paper(doi: str, title: str, abstract: str, authors: list[str],
                  is_oa: bool = True, journal: str = "Forests",
                  year: int = 2026, source: str = "openalex") -> dict:
    return {
        "title": title,
        "doi": doi.lower() if doi else "",
        "authors": authors,
        "year": year,
        "publication_date": f"{year}-04-01",
        "abstract": abstract,
        "journal": journal,
        "openalex_source_id": "S71324801",
        "is_oa": is_oa,
        "oa_url": f"https://doi.org/{doi}" if is_oa and doi else None,
        "cited_by_count": 3,
        "openalex_id": "",
        "source_fetcher": source,
    }


def test_deduplicate_by_doi():
    """Two entries with same DOI should collapse to one."""
    papers = [
        _sample_paper("10.3390/f17050533", "Title A", "abstract", ["Author A"],
                     source="openalex"),
        _sample_paper("10.3390/F17050533", "Title A duplicate", "abstract2",
                     ["Author A"], source="crossref"),  # uppercase DOI
    ]
    deduped = deduplicate_papers(papers)
    assert len(deduped) == 1, f"expected 1 paper after dedupe, got {len(deduped)}"
    # Should prefer OpenAlex (priority 0 < CrossRef 1)
    assert deduped[0]["source_fetcher"] == "openalex"
    print("  ✓ test_deduplicate_by_doi")


def test_deduplicate_no_doi():
    """Entries without DOI should dedupe by (title, year)."""
    papers = [
        _sample_paper("", "Identical title here", "abs1", ["X"], source="rss"),
        _sample_paper("", "Identical title here", "abs2", ["X"], source="rss"),
    ]
    deduped = deduplicate_papers(papers)
    assert len(deduped) == 1
    print("  ✓ test_deduplicate_no_doi")


def test_scoring_high_priority_keyword():
    """Paper with 'urban forestry' (high priority +3) + 'urban tree' (+2) + Italy (+1)
       should score at least 6 + bonuses."""
    rules = {
        "areas": {
            "verde_urbano": {
                "positive_high": ["urban forestry"],
                "positive_medium": ["urban tree"],
                "positive_low": ["Italy"],
                "negative": [],
            }
        },
        "key_authors": [],
    }
    paper = _sample_paper(
        "10.1234/test1",
        "Urban forestry in Italy",
        "This paper studies urban tree species in Italy.",
        ["Anonymous Author"],
    )
    score, area, kws = score_paper(paper, rules)
    # +3 (urban forestry) +2 (urban tree) +1 (italy) +1 (OA bonus) = 7
    assert score == 7, f"expected score 7, got {score}: kws={kws}"
    assert area == "verde_urbano"
    print(f"  ✓ test_scoring_high_priority_keyword (score={score})")


def test_scoring_key_author_bonus():
    """Paper by Sjöman should get +5 author bonus."""
    rules = {
        "areas": {
            "verde_urbano": {
                "positive_high": ["urban tree species"],
                "positive_medium": [],
                "positive_low": [],
                "negative": [],
            }
        },
        "key_authors": [
            {"name": "Henrik Sjöman", "openalex_id": "A5017961344",
             "areas": ["verde_urbano"]}
        ],
    }
    paper = _sample_paper(
        "10.1234/test2",
        "Urban tree species selection",
        "Selection criteria.",
        ["Henrik Sjöman", "Other"],
    )
    score, area, kws = score_paper(paper, rules)
    # +3 (urban tree species) +1 (OA) +5 (Sjöman) = 9
    assert score == 9, f"expected score 9, got {score}: kws={kws}"
    assert any("author=Henrik" in kw for kw in kws), f"author bonus missing: {kws}"
    print(f"  ✓ test_scoring_key_author_bonus (score={score})")


def test_scoring_negative_keyword():
    """Negative keyword should subtract."""
    rules = {
        "areas": {
            "verde_urbano": {
                "positive_high": ["urban forestry"],
                "positive_medium": [],
                "positive_low": [],
                "negative": ["tropical rainforest"],
            }
        },
        "key_authors": [],
    }
    paper = _sample_paper(
        "10.1234/test3",
        "Urban forestry vs tropical rainforest comparison",
        "abstract here",
        ["Anon"],
    )
    score, _, _ = score_paper(paper, rules)
    # +3 - 2 + 1 (OA) = 2
    assert score == 2, f"expected score 2, got {score}"
    print(f"  ✓ test_scoring_negative_keyword (score={score})")


def test_seen_roundtrip():
    """Save and load seen DOIs."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "seen.json"
        original = {"10.1234/abc", "10.5678/def"}
        save_seen(path, original)
        loaded = load_seen(path)
        assert loaded == original, f"roundtrip failed: {loaded} != {original}"
        print("  ✓ test_seen_roundtrip")


def test_digest_writer_creates_file():
    """write_digest creates a markdown file with expected sections."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test_digest.md"
        papers = [
            {**_sample_paper("10.3390/f17050533", "Important paper",
                            "Urban heat island study", ["Sjöman H."]),
             "score": 9, "area": "verde_urbano",
             "matched_keywords": ["+3:urban heat island", "+5:author=Sjöman"]},
        ]
        write_digest(path, papers, fetch_summary={"openalex_journal": 5},
                    threshold=5)
        content = path.read_text(encoding="utf-8")
        assert "# Letteratura — settimana" in content
        assert "Verde Urbano" in content
        assert "Important paper" in content
        assert "10.3390/f17050533" in content
        assert "⭐" in content  # score >= 8
        print(f"  ✓ test_digest_writer_creates_file ({len(content)} chars)")


def test_digest_writer_empty():
    """write_digest handles empty list gracefully."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "empty_digest.md"
        write_digest(path, [])
        content = path.read_text(encoding="utf-8")
        assert "Nessun paper sopra la soglia" in content
        print("  ✓ test_digest_writer_empty")


def test_config_files_valid_json():
    """sources.json and rules.json should be valid JSON with required keys."""
    repo_root = HERE.parent
    sources = json.loads((repo_root / "config" / "sources.json").read_text())
    assert "journals" in sources
    assert "authors" in sources
    assert "queries" in sources
    assert len(sources["journals"]) >= 1
    assert len(sources["authors"]) >= 1
    assert all("openalex_id" in j for j in sources["journals"]
               if not j.get("name", "").startswith("_"))
    print(f"  ✓ test_config_files_valid_json (journals={len(sources['journals'])}, "
          f"authors={len(sources['authors'])}, queries={len(sources['queries'])})")

    rules = json.loads((repo_root / "config" / "rules.json").read_text())
    assert "areas" in rules
    assert "key_authors" in rules
    assert "verde_urbano" in rules["areas"]
    assert "vta" in rules["areas"]
    print(f"  ✓ rules.json: {len(rules['areas'])} areas, "
          f"{len(rules['key_authors'])} key authors")


if __name__ == "__main__":
    print("=== Smoke test E2E monitor-letteratura-agronomo ===\n")
    tests = [
        test_deduplicate_by_doi,
        test_deduplicate_no_doi,
        test_scoring_high_priority_keyword,
        test_scoring_key_author_bonus,
        test_scoring_negative_keyword,
        test_seen_roundtrip,
        test_digest_writer_creates_file,
        test_digest_writer_empty,
        test_config_files_valid_json,
    ]
    failed = []
    for t in tests:
        try:
            t()
        except AssertionError as e:
            print(f"  ✗ {t.__name__}: {e}")
            failed.append(t.__name__)
        except Exception as e:
            print(f"  ✗ {t.__name__}: unexpected error: {e}")
            failed.append(t.__name__)

    print(f"\n=== {len(tests) - len(failed)}/{len(tests)} passed ===")
    sys.exit(1 if failed else 0)
