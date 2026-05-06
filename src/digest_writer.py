"""Write the markdown digest grouped by area, sorted by score descending."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


AREA_LABELS = {
    "verde_urbano": "Verde Urbano",
    "vta": "VTA / Arboricoltura ornamentale",
    "viticoltura": "Viticoltura",
    "olivicoltura": "Olivicoltura",
    "fitopatologia": "Fitopatologia ornamentale e mediterranea",
    "garden_design": "Garden design",
    "uncategorized": "Non classificati",
}


def write_digest(
    filepath: Path,
    papers: list[dict[str, Any]],
    *,
    fetch_summary: dict[str, int] | None = None,
    threshold: int = 5,
) -> None:
    """Write a markdown digest file at `filepath`.

    Papers are grouped by area, sorted by score descending.
    Papers with score >= 8 are marked with a star.
    """
    iso_year, iso_week, _ = datetime.now(timezone.utc).isocalendar()
    today = datetime.now(timezone.utc).strftime("%d/%m/%Y")

    by_area: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in papers:
        by_area[p.get("area", "uncategorized")].append(p)

    summary_line = ""
    if fetch_summary:
        parts = [f"{src}: {n}" for src, n in sorted(fetch_summary.items())]
        summary_line = f"Fonti chiamate: {', '.join(parts)}. "

    lines: list[str] = []
    lines.append(f"# Letteratura — settimana W{iso_week:02d}/{iso_year}")
    lines.append("")
    lines.append(
        f"*Generato {today}. {summary_line}"
        f"Score >= {threshold} mostrati. {len(papers)} hits totali sopra soglia.*"
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    if not papers:
        lines.append("**Nessun paper sopra la soglia di rilevanza questa settimana.**")
        lines.append("")
        lines.append("Possibili motivi:")
        lines.append("")
        lines.append("- finestra temporale troppo stretta (default 14 giorni)")
        lines.append("- soglia di score alta (`min_score_threshold` in `rules.json`)")
        lines.append("- keyword troppo restrittive (rivedere `00_glossario_keywords.md`)")
        lines.append("- API in errore (controllare i log del workflow)")
        lines.append("")
    else:
        # Order areas: those with most papers first, "uncategorized" last
        ordered = sorted(
            by_area.items(),
            key=lambda kv: (kv[0] == "uncategorized", -len(kv[1])),
        )
        for area, area_papers in ordered:
            area_label = AREA_LABELS.get(area, area)
            area_papers.sort(key=lambda p: p.get("score", 0), reverse=True)
            lines.append(f"## {area_label} ({len(area_papers)} hits)")
            lines.append("")
            for p in area_papers:
                score = p.get("score", 0)
                star = "⭐ " if score >= 8 else ""
                oa_emoji = "✅" if p.get("is_oa") else "🔒"
                title = (p.get("title") or "(senza titolo)").strip()

                lines.append(f"### {star}Score {score} — {title}")
                doi = p.get("doi") or ""
                if doi:
                    lines.append(f"- **DOI**: [{doi}](https://doi.org/{doi})")
                else:
                    lines.append("- **DOI**: N/A")
                journal = p.get("journal") or "rivista non specificata"
                lines.append(f"- **Rivista**: {journal}")
                year = p.get("year")
                if year:
                    lines.append(f"- **Anno**: {year}")
                authors = p.get("authors") or []
                if authors:
                    if len(authors) > 6:
                        authors_str = ", ".join(authors[:6]) + ", ..."
                    else:
                        authors_str = ", ".join(authors)
                    lines.append(f"- **Autori**: {authors_str}")
                oa_url = p.get("oa_url") or ""
                if oa_url:
                    lines.append(f"- **OA**: {oa_emoji} [PDF]({oa_url})")
                else:
                    lines.append(f"- **OA**: {oa_emoji}")
                cited = p.get("cited_by_count", 0) or 0
                if cited > 0:
                    lines.append(f"- **Citazioni**: {cited}")
                matched = p.get("matched_keywords") or []
                if matched:
                    matched_str = ", ".join(matched[:6])
                    if len(matched) > 6:
                        matched_str += ", ..."
                    lines.append(f"- **Match**: {matched_str}")
                source_f = p.get("source_fetcher", "")
                if source_f:
                    lines.append(f"- **Fonte**: {source_f}")
                lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "*Convenzione triage: 👍 da indicizzare (scarica PDF se OA + droppa in `_inbox/`); "
        "📌 salvo per dopo (annota qui sotto con `<<<`); 🗑️ ignoro (entra in `seen.json`).*"
    )
    lines.append("")

    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text("\n".join(lines), encoding="utf-8")
