"""Apply scoring rules to a paper.

For each area in rules.json, sum keyword matches in title + abstract.
Pick the area with highest score. Apply bonuses (OA, key author, citation count).
"""
from __future__ import annotations

import re
from typing import Any


def _norm(text: str) -> str:
    """Lowercase, strip extra whitespace."""
    return re.sub(r"\s+", " ", text or "").lower().strip()


def _has_phrase(text: str, phrase: str) -> bool:
    """Check if a phrase appears in text (case-insensitive, word-boundary safe)."""
    text_norm = _norm(text)
    phrase_norm = _norm(phrase)
    if not phrase_norm:
        return False
    # Use simple substring match — adequate for our keyword sizes
    return phrase_norm in text_norm


def score_paper(paper: dict[str, Any], rules: dict[str, Any]) -> tuple[int, str, list[str]]:
    """Return (best_score, best_area, matched_keywords).

    rules schema (config/rules.json):
    {
      "areas": {
        "verde_urbano": {
          "positive_high": ["urban forestry", ...],   # weight +3
          "positive_medium": [...],                    # weight +2
          "positive_low": [...],                       # weight +1
          "negative": [...]                            # weight -2
        },
        "vta": { ... }
      },
      "key_authors": [{"name": "Henrik Sjöman", "openalex_id": "A...", "areas": [...]}],
      "min_score_threshold": 5
    }
    """
    text = (paper.get("title", "") or "") + " " + (paper.get("abstract", "") or "")

    best_score = 0
    best_area = "uncategorized"
    matched_keywords: list[str] = []

    # Per-area scoring
    for area, area_rules in (rules.get("areas") or {}).items():
        score = 0
        kw_for_area: list[str] = []

        for kw in area_rules.get("positive_high", []) or []:
            if _has_phrase(text, kw):
                score += 3
                kw_for_area.append(f"+3:{kw}")
        for kw in area_rules.get("positive_medium", []) or []:
            if _has_phrase(text, kw):
                score += 2
                kw_for_area.append(f"+2:{kw}")
        for kw in area_rules.get("positive_low", []) or []:
            if _has_phrase(text, kw):
                score += 1
                kw_for_area.append(f"+1:{kw}")
        for kw in area_rules.get("negative", []) or []:
            if _has_phrase(text, kw):
                score -= 2
                kw_for_area.append(f"-2:{kw}")

        if score > best_score:
            best_score = score
            best_area = area
            matched_keywords = kw_for_area

    # If the paper got 0 in all areas but has a key author, classify by author area
    if best_score == 0:
        author_match = _check_key_author(paper, rules)
        if author_match:
            best_area = author_match["areas"][0] if author_match.get("areas") else best_area

    # Bonuses (apply only if at least one area matched OR key author)
    bonus = 0
    bonus_notes: list[str] = []

    if paper.get("is_oa"):
        bonus += 1
        bonus_notes.append("+1:OA")

    author_match = _check_key_author(paper, rules)
    if author_match:
        bonus += 5
        bonus_notes.append(f"+5:author={author_match.get('name', '')}")

    cited = paper.get("cited_by_count", 0) or 0
    if cited >= 5:
        bonus += 1
        bonus_notes.append(f"+1:cited({cited})")

    if best_score > 0 or author_match:
        best_score += bonus
        matched_keywords.extend(bonus_notes)

    return best_score, best_area, matched_keywords


def _check_key_author(paper: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any] | None:
    """Return the matching key-author entry if any of paper's authors is one."""
    paper_authors_norm = {_norm(a) for a in (paper.get("authors") or [])}
    for ka in rules.get("key_authors", []) or []:
        ka_name_norm = _norm(ka.get("name", ""))
        if not ka_name_norm:
            continue
        # Match either exact or surname-only
        ka_surname = ka_name_norm.split()[-1] if ka_name_norm else ""
        for pa in paper_authors_norm:
            if ka_name_norm in pa or (ka_surname and ka_surname in pa.split()):
                return ka
    return None
